"""
AgentEngine - 统一编排引擎
整合 LiteLLM + LangGraph + MCP + Casbin
"""
import asyncio
import functools
import json
import time
import uuid
from typing import AsyncGenerator, Optional

from langchain_core.messages import (
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.base import RunnableSequence
from langchain_core.tools import StructuredTool
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from core.model_hub import ModelHub
from core.skill_manager import SkillManager
from core.mcp_manager import MCPManager
from auth.auth_manager import AuthManager
from config import settings


WORKSPACE_TOOL_NAMES = frozenset(
    {
        "list_files",
        "read_file",
        "write_file",
        "edit_file",
        "read_csv",
        "run_python",
        "make_xlsx",
        "make_docx",
        "make_chart",
        "read_file_base64",
        # 版本快照与租户目录同生命周期，因此受同一道开关与范围约束。
        "list_file_versions",
        "read_file_version",
    }
)
TOOL_TRACE_MAX_EVENTS = 64
TOOL_TRACE_RESULT_LIMIT = 2_000
USAGE_MESSAGE_LIMIT = 512

# 五档运行模式。chat/plan/agent 的图形态与引入模式前完全一致，
# 只有 goal/loop 会多挂一个监督节点。
AGENT_MODES = ("chat", "plan", "agent", "goal", "loop")
SUPERVISED_MODES = frozenset({"goal", "loop"})
SUPERVISOR_NODE_NAME = "supervisor"
# plan 模式的产物是计划而不是改动，因此只给只读工具。
PLAN_MODE_TOOL_NAMES = frozenset(
    {
        "list_files",
        "read_file",
        "read_csv",
        "web_search",
        "fetch_url",
        "list_file_versions",
        "read_file_version",
    }
)
ITERATION_TRACE_MAX_EVENTS = 32
JUDGE_CONTEXT_LIMIT = 6_000
JUDGE_REASON_LIMIT = 1_000
SUBAGENT_TOOL_NAME = "dispatch_subagent"
SUBAGENT_USAGE_LIMIT = 64
SUBAGENT_RESULT_LIMIT = 20_000
# 监督模式下每轮可能伴随多次工具调用，递归上限需要随轮次放宽，
# 但必须有硬顶，否则一个大的 max_iterations 就能让一次请求跑很久。
MAX_SUPERVISED_RECURSION = 200

PLAN_OUTPUT_CONTRACT = """当前为规划模式：只调研与拆解，不要改写任何文件、不要生成交付物。
请先用可用的只读工具核实事实，然后仅输出一段 JSON，不要附加其他文字：
{"objective": "一句话目标", "steps": [{"title": "步骤标题", "instructions": "该步骤具体要做什么"}]}
步骤控制在 1 到 12 个，每个 instructions 不超过 400 字。"""

GOAL_MODE_CONTRACT = """当前为目标驱动模式：请自主拆解并推进，直到达成标准。
每轮结束时用一句话说明：已完成什么、还差什么。不要反复重做已经满足的标准。"""

LOOP_MODE_CONTRACT = """当前为循环迭代模式：每一轮都基于上一轮的结果继续改进。
每轮结束时用一句话说明本轮改进了什么、距停止条件还差什么。"""

JUDGE_CONTRACT = """你是执行质量监督者。根据目标、停止条件与最新产出，判断是否已达成。
只输出一行 JSON，不要附加其他文字：{"met": true 或 false, "reason": "简短中文说明"}
若未达成，reason 必须写成可直接交给执行者的下一步指令。"""


class State(MessagesState):
    """监督模式需要的轮次与判定字段。

    非监督模式不会写入这些键，节点内一律用 ``.get()`` 读取，因此
    chat/plan/agent 三档不需要构造完整初始状态。
    """

    mode: str
    goal: str
    success_criteria: str
    iteration: int
    max_iterations: int
    verdict: str


class AgentEngine:
    """
    统一 Agent 引擎
    整合: LiteLLM(模型) + LangGraph(编排) + MCP(工具) + Casbin(权限)
    """

    def __init__(
        self,
        model_hub: Optional[ModelHub] = None,
        mcp_manager: Optional[MCPManager] = None,
        skill_manager: Optional[SkillManager] = None,
        auth_manager: Optional[AuthManager] = None,
    ):
        self.model_hub = model_hub or ModelHub()
        self.mcp_manager = mcp_manager or MCPManager()
        self.skill_manager = skill_manager or SkillManager()
        self.auth_manager = auth_manager or AuthManager()

    def _agent_factory(
        self,
        llm,
        tools: list[StructuredTool],
        system_prompt: str,
    ) -> RunnableSequence:
        # 系统提示词是字面文本，不是模板：传入 SystemMessage 实例避开
        # 变量插值。规划模式的 JSON 输出契约、以及用户自建技能里的
        # 花括号，都不应被当成模板变量解析。
        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(content=system_prompt),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        if tools:
            agent = prompt | llm.bind_tools(tools)
        else:
            agent = prompt | llm
        return agent

    async def _agent_node_factory(
        self,
        state: State,
        agent: RunnableSequence,
    ) -> State:
        result = await agent.ainvoke(state)
        return dict(messages=[result])

    def _graph_factory(
        self,
        agent_node: functools.partial,
        tools: list[StructuredTool],
        checkpointer: AsyncPostgresSaver | None = None,
        name: str = "agent_node",
        supervisor_node=None,
    ) -> CompiledStateGraph:
        """装配执行图。

        没有 ``supervisor_node`` 时（chat/plan/agent）图形态与引入模式前
        逐字一致，仍然直接复用 ``tools_condition``，以保证零回归。
        监督模式（goal/loop）把“无工具调用”的出口从 END 改接到监督节点，
        由它决定再迭代一轮还是结束。
        """
        graph_builder = StateGraph(State)
        graph_builder.add_node(name, agent_node)
        if tools:
            graph_builder.add_node("tools", ToolNode(tools))

        if supervisor_node is not None:
            graph_builder.add_node(SUPERVISOR_NODE_NAME, supervisor_node)
            destinations = ["tools", SUPERVISOR_NODE_NAME] if tools else [SUPERVISOR_NODE_NAME]
            graph_builder.add_conditional_edges(
                name, self._agent_router(supervised=True), destinations
            )
            if tools:
                graph_builder.add_edge("tools", name)
            graph_builder.add_conditional_edges(
                SUPERVISOR_NODE_NAME, self._supervisor_router(name), [name, END]
            )
        elif tools:
            graph_builder.add_conditional_edges(name, tools_condition)
            graph_builder.add_edge("tools", name)
        else:
            graph_builder.add_edge(name, END)

        graph_builder.set_entry_point(name)
        graph = graph_builder.compile(checkpointer=checkpointer)
        return graph

    @staticmethod
    def _has_tool_calls(state: State) -> bool:
        messages = state.get("messages") or []
        return bool(messages) and bool(getattr(messages[-1], "tool_calls", None))

    def _agent_router(self, *, supervised: bool):
        def route(state: State) -> str:
            if self._has_tool_calls(state):
                return "tools"
            return "supervisor" if supervised else END

        return route

    @staticmethod
    def _supervisor_router(agent_node_name: str):
        def route(state: State) -> str:
            # 只有明确“未达成”才继续；判定不可用时必须停下，
            # 否则一次解析失败就会把整份预算烧光。
            return agent_node_name if state.get("verdict") == "not_met" else END

        return route

    def _supervisor_node_factory(self, llm, mode: str, config: dict):
        async def supervisor_node(state: State) -> dict:
            iteration = int(state.get("iteration") or 0) + 1
            max_iterations = max(1, int(state.get("max_iterations") or 1))
            if iteration > max_iterations:
                reason = f"已达到最大迭代轮次（{max_iterations}），停止。"
                self._record_iteration(config, iteration, "budget_exhausted", reason)
                return {"iteration": iteration, "verdict": "budget_exhausted"}
            verdict, reason = await self._judge(llm, mode, state)
            self._record_iteration(config, iteration, verdict, reason)
            if verdict != "not_met":
                return {"iteration": iteration, "verdict": verdict}
            # 把监督者的下一步指令作为人类消息回注，驱动下一轮。
            return {
                "iteration": iteration,
                "verdict": verdict,
                "messages": [HumanMessage(content=reason)],
            }

        return supervisor_node

    async def _judge(self, llm, mode: str, state: State) -> tuple[str, str]:
        """让模型判定是否达成；任何异常都终止而不是继续烧预算。"""
        latest = ""
        for message in reversed(state.get("messages") or []):
            if getattr(message, "type", "") == "ai":
                latest = self._content_to_text(message.content)
                if latest.strip():
                    break
        focus = (
            f"目标：{state.get('goal') or '（未提供）'}\n"
            f"达成标准：{state.get('success_criteria') or '（未提供）'}"
            if mode == "goal"
            else f"停止条件：{state.get('success_criteria') or '（未提供）'}"
        )
        prompt = f"{focus}\n最新产出：\n{latest[:JUDGE_CONTEXT_LIMIT]}"
        try:
            response = await llm.ainvoke(
                [SystemMessage(content=JUDGE_CONTRACT), HumanMessage(content=prompt)]
            )
        except Exception:  # noqa: BLE001 - 判定失败不得抛到流里
            return "judge_unavailable", "监督判定调用失败，已停止迭代。"
        parsed = self._parse_judgement(self._content_to_text(response.content))
        if parsed is None:
            return "judge_unavailable", "监督判定结果无法解析，已停止迭代。"
        met, reason = parsed
        return ("met" if met else "not_met"), reason

    @staticmethod
    def _parse_judgement(text: str) -> tuple[bool, str] | None:
        """从模型文本里取第一段 JSON；不合约定时返回 None。"""
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except ValueError:
            return None
        if not isinstance(payload, dict) or "met" not in payload:
            return None
        reason = str(payload.get("reason") or "").strip() or "（监督者未说明原因）"
        return bool(payload["met"]), reason[:JUDGE_REASON_LIMIT]

    @staticmethod
    def _mode_prompt(base_prompt: str, mode: str, config: dict) -> str:
        """在技能提示词上叠加模式约束，不取代技能本身的角色设定。"""
        goal = str(config.get("goal") or "").strip()
        criteria = str(config.get("success_criteria") or "").strip()
        if mode == "plan":
            return f"{base_prompt}\n\n{PLAN_OUTPUT_CONTRACT}"
        if mode == "goal":
            return (
                f"{base_prompt}\n\n{GOAL_MODE_CONTRACT}\n"
                f"目标：{goal or '（未提供）'}\n达成标准：{criteria or '（未提供）'}"
            )
        if mode == "loop":
            return f"{base_prompt}\n\n{LOOP_MODE_CONTRACT}\n停止条件：{criteria or '（未提供）'}"
        return base_prompt

    @classmethod
    def _record_iteration(cls, config: dict, iteration: int, verdict: str, reason: str) -> None:
        """把轮次判定写入侧信道，供路由层发 SSE 与落库。"""
        trace = config.get("iterations")
        if not isinstance(trace, list) or len(trace) >= ITERATION_TRACE_MAX_EVENTS:
            return
        trace.append(
            {
                "iteration": iteration,
                "verdict": verdict,
                "reason": reason[:JUDGE_REASON_LIMIT],
            }
        )

    def _subagent_tool(
        self,
        *,
        user_role: str,
        tools: list[StructuredTool],
        model_id: str,
        config: dict,
        workspace_id: str | None,
        permission_mode: str,
        depth: int,
    ) -> StructuredTool:
        """构造 dispatch_subagent：父代理把子任务交给子代理独立完成。

        子代理不重新连接 MCP，而是复用父代理已加载并已过滤的工具集，
        因此它的权限永远是父代理的子集，无法提权。它也不获得新的
        时间预算，而是共享父执行的剩余预算。
        """
        semaphore = asyncio.Semaphore(max(1, settings.subagent_max_parallel))
        deadline = float(
            config.get("deadline")
            or (time.monotonic() + max(1, settings.agent_run_timeout_seconds))
        )
        config["deadline"] = deadline
        # 先把本工具从子代理的工具集里去掉；只有深度未达上限时才重新加回。
        child_tools = [tool for tool in tools if tool.name != SUBAGENT_TOOL_NAME]
        child_depth = depth + 1
        can_nest = child_depth < max(0, settings.subagent_max_depth)

        async def dispatch(skill_name: str, task: str) -> str:
            """把一个自包含的子任务交给指定技能的子代理独立完成，返回其最终文本。

            参数:
                skill_name: 子代理使用的技能名，决定它的角色与工具白名单。
                task: 交给子代理的完整任务描述，必须自包含。
            """
            if not str(task or "").strip():
                return "子代理未启动：task 不能为空。"
            child_skill = self.skill_manager.get_skill(skill_name)
            if child_skill is None:
                return f"子代理未启动：技能“{skill_name}”不存在。"
            # 技能可以用 model_override 改用哪个模型，但不能绕过模型级 RBAC。
            child_model = (child_skill.model_override or model_id).strip() or model_id
            if not self.auth_manager.is_allowed(user_role, f"model:{child_model}", "use"):
                return "子代理未启动：当前角色无权使用技能指定的模型。"
            nested = list(child_tools)
            # 嵌套同样要三重授权：深度未达上限 + 子技能显式开启 + RBAC 允许。
            if (
                can_nest
                and SUBAGENT_TOOL_NAME in (child_skill.allowed_tool_names or [])
                and self.auth_manager.is_allowed(
                    user_role, f"tool:{SUBAGENT_TOOL_NAME}", "use"
                )
            ):
                nested.append(
                    self._subagent_tool(
                        user_role=user_role,
                        tools=nested,
                        model_id=child_model,
                        config=config,
                        workspace_id=workspace_id,
                        permission_mode=permission_mode,
                        depth=child_depth,
                    )
                )
            child_config: dict = {
                "model_id": child_model,
                "skill_name": skill_name,
                "workspace_id": workspace_id,
                "permission_mode": permission_mode,
                "deadline": deadline,
                "subagent_depth": child_depth,
                "tool_trace": [],
                "usage_by_message": {},
                "iterations": [],
            }
            async with semaphore:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._record_subagent_usage(config, child_config, child_model, skill_name, "skipped")
                    return "子代理未启动：本次执行的时间预算已用尽。"
                child_config["started_monotonic"] = time.monotonic()
                try:
                    async with asyncio.timeout(remaining):
                        return await self._run_child(
                            config, child_config, nested, child_model, skill_name, str(task)
                        )
                except TimeoutError:
                    self._record_subagent_usage(config, child_config, child_model, skill_name, "timeout")
                    return "子代理已中止：共享时间预算已用尽，请缩小任务范围。"
                except Exception:  # noqa: BLE001 - 子代理失败不得连带失败父代理
                    self._record_subagent_usage(config, child_config, child_model, skill_name, "failed")
                    return "子代理执行失败，请缩小任务范围后重试。"

        return StructuredTool.from_function(
            coroutine=dispatch,
            name=SUBAGENT_TOOL_NAME,
            description=(
                "把一个自包含的子任务交给指定技能的子代理独立完成，返回它的最终文本。"
                "适用于可并行或需要不同专长的子任务；不要用它替代你自己能直接完成的一步。"
            ),
        )

    async def _run_child(
        self,
        parent_config: dict,
        child_config: dict,
        tools: list[StructuredTool],
        model_id: str,
        skill_name: str,
        task: str,
    ) -> str:
        """用已过滤的工具集跑一个独立的子代理图，不重连 MCP。"""
        skill_data = self.skill_manager.assemble_skill(skill_name, tools)
        llm = self.model_hub.get_chat_model(model_id=model_id)
        agent = self._agent_factory(llm, skill_data["tools"], skill_data["system_prompt"])
        node = functools.partial(self._agent_node_factory, agent=agent)
        graph = self._graph_factory(node, skill_data["tools"])
        graph_config = {
            # 子代理用独立线程：写入父线程会污染父代理的会话记忆。
            "configurable": {"thread_id": str(uuid.uuid4())},
            "recursion_limit": max(1, settings.agent_recursion_limit),
        }
        parts: list[str] = []
        async for message, _metadata in graph.astream(
            {"messages": [HumanMessage(content=task)]},
            graph_config,
            stream_mode="messages",
        ):
            if isinstance(message, AIMessageChunk):
                self._record_usage(child_config, message)
                parts.append(self._content_to_text(message.content))
            elif isinstance(message, ToolMessage):
                self._record_tool_trace(child_config, message)
        self._record_subagent_usage(
            parent_config, child_config, model_id, skill_name, "succeeded"
        )
        result = "".join(parts).strip()
        return result[:SUBAGENT_RESULT_LIMIT] or "子代理没有返回内容。"

    @classmethod
    def _record_subagent_usage(
        cls,
        parent_config: dict,
        child_config: dict,
        model_id: str,
        skill_name: str,
        status: str,
    ) -> None:
        """把子代理的用量挂到父执行的侧信道上。

        子代理有自己独立的 ``usage_by_message``，因此不会与父代理重复
        计数；路由层据此为每个子代理写一条带 ``parent_run_id`` 的用量记录。
        即使子代理失败或超时，已消耗的 token 也是真实成本，必须上报。
        """
        records = parent_config.setdefault("subagent_usage", [])
        if not isinstance(records, list) or len(records) >= SUBAGENT_USAGE_LIMIT:
            return
        trace = child_config.get("tool_trace")
        started = child_config.get("started_monotonic")
        elapsed_ms = (
            max(0, int((time.monotonic() - float(started)) * 1000))
            if isinstance(started, (int, float))
            else 0
        )
        records.append(
            {
                "model_id": model_id,
                "skill_name": skill_name,
                "status": status,
                "depth": int(child_config.get("subagent_depth") or 0),
                "tool_calls": len(trace) if isinstance(trace, list) else 0,
                "duration_ms": elapsed_ms,
                "usage": cls.summarize_usage(child_config),
            }
        )

    async def run(
        self,
        user_role: str,
        query: str,
        config: dict,
        checkpointer: AsyncPostgresSaver | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        执行 Agent 请求

        Args:
            user_role: 用户角色 (如 "developer", "user")
            query: 用户查询
            config: 配置字典
                - model_id: 模型ID (如 "gpt-4o", "claude-3-5-sonnet")
                - skill_name: Skill名称
                - mcp_servers: MCP服务器列表
                - mode: chat/plan/agent/goal/loop，缺省为 agent
                - goal / success_criteria / max_iterations: 监督模式参数
            checkpointer: LangGraph 检查点保存器

        Yields:
            流式响应内容
        """
        model_id = config.get("model_id", settings.default_model)
        skill_name = config.get("skill_name", "default")
        mcp_servers = config.get("mcp_servers", [])
        # 缺省 agent 而不是 chat：引入模式前，对话与工作执行本来就会
        # 绑定已选 MCP 工具；默认成 chat 会静默关掉用户选的工具。
        mode = str(config.get("mode") or "agent")
        if mode not in AGENT_MODES:
            raise ValueError(f"不支持的运行模式：{mode}")
        supervised = mode in SUPERVISED_MODES
        max_iterations = max(
            1,
            min(
                int(config.get("max_iterations") or settings.agent_max_iterations),
                settings.agent_max_iterations,
            ),
        )

        # 1. 权限校验（API 层也会提前执行一次，以便返回正确 HTTP 状态）
        self.validate_permissions(user_role, config)

        # 2. 获取所有可用工具 (MCP工具)
        all_tools: list[StructuredTool] = []
        workspace_id = config.get("workspace_id")
        async with self.mcp_manager.connect_many(
            mcp_servers,
            workspace_id=workspace_id,
            # 供工具服务将文件改动归因到本次受治理的执行。
            agent_run_id=config.get("agent_run_id") or None,
        ) as sessions:
            for session in sessions:
                tools = await self.mcp_manager.get_mcp_tools(session)
                all_tools.extend(tools)

            # 未授权工具不会进入模型上下文，即使 MCP 服务本身可访问。
            all_tools = self.filter_available_tools(
                user_role,
                all_tools,
                workspace_id=workspace_id,
                permission_mode=str(config.get("permission_mode") or "default"),
            )

            # 子代理是显式能力：技能必须在白名单里列出 dispatch_subagent
            # 才会注入。白名单为空表示“放开全部 MCP 工具”，并不等于“可以
            # 派生子代理”——后者会成倍放大模型调用量与耗时，必须单独授权。
            # 工具由引擎本地注入不经 MCP，因此还要手动走同一道 RBAC。
            skill = self.skill_manager.get_skill(skill_name)
            depth = int(config.get("subagent_depth") or 0)
            subagent_opted_in = bool(
                skill and SUBAGENT_TOOL_NAME in (skill.allowed_tool_names or [])
            )
            if (
                subagent_opted_in
                and depth < max(0, settings.subagent_max_depth)
                and self.auth_manager.is_allowed(
                    user_role, f"tool:{SUBAGENT_TOOL_NAME}", "use"
                )
            ):
                all_tools = list(all_tools) + [
                    self._subagent_tool(
                        user_role=user_role,
                        tools=all_tools,
                        model_id=model_id,
                        config=config,
                        workspace_id=workspace_id,
                        permission_mode=str(config.get("permission_mode") or "default"),
                        depth=depth,
                    )
                ]

            # 3. 按模式收敛工具面，再装配 Skill（过滤工具 + 获取提示词）
            if mode == "chat":
                mode_tools: list[StructuredTool] = []
            elif mode == "plan":
                mode_tools = [
                    tool for tool in all_tools if tool.name in PLAN_MODE_TOOL_NAMES
                ]
            else:
                mode_tools = all_tools
            skill_data = self.skill_manager.assemble_skill(skill_name, mode_tools)

            # 4. 通过 ModelHub 获取 ChatModel (LiteLLM 或后备方案)
            llm = self.model_hub.get_chat_model(model_id=model_id)

            # 5. 构建 LangGraph Agent
            system_prompt = self._mode_prompt(skill_data["system_prompt"], mode, config)
            agent = self._agent_factory(llm, skill_data["tools"], system_prompt)
            worker_node = functools.partial(self._agent_node_factory, agent=agent)
            graph = self._graph_factory(
                worker_node,
                skill_data["tools"],
                checkpointer,
                name="agent_node",
                supervisor_node=(
                    self._supervisor_node_factory(llm, mode, config)
                    if supervised
                    else None
                ),
            )

            # 6. 构建初始状态；只有监督模式需要轮次与判定字段
            initial_state: dict = {"messages": [HumanMessage(content=query)]}
            if supervised:
                initial_state.update(
                    {
                        "mode": mode,
                        "goal": str(config.get("goal") or ""),
                        "success_criteria": str(config.get("success_criteria") or ""),
                        "iteration": 0,
                        "max_iterations": max_iterations,
                        "verdict": "",
                    }
                )

            # 7. 执行并流式返回
            recursion_limit = max(1, settings.agent_recursion_limit)
            if supervised:
                # 每轮可能伴随多次工具往返，随轮次放宽但保留硬顶。
                recursion_limit = min(
                    MAX_SUPERVISED_RECURSION,
                    recursion_limit * (max_iterations + 1),
                )
            graph_config = {
                "configurable": {
                    "thread_id": config.get("thread_id") or str(uuid.uuid4())
                },
                "recursion_limit": recursion_limit,
            }

            async for message, metadata in graph.astream(
                initial_state,
                graph_config,
                stream_mode="messages",
            ):
                if isinstance(message, AIMessageChunk):
                    # 监督判定同样消耗 token，无论是否展示都必须计量。
                    self._record_usage(config, message)
                    # 但监督节点是内部控制流：它输出的判定 JSON 不是给
                    # 用户看的回复，stream_mode=messages 会把它一并流出来，
                    # 必须按节点名过滤掉，否则原始 JSON 会泄到对话里。
                    if (metadata or {}).get("langgraph_node") == SUPERVISOR_NODE_NAME:
                        continue
                    text = self._content_to_text(message.content)
                    if text:
                        yield text
                elif isinstance(message, ToolMessage):
                    self._record_tool_trace(config, message)

    def filter_available_tools(
        self,
        user_role: str,
        tools: list[StructuredTool],
        *,
        workspace_id: str | None = None,
        permission_mode: str = "default",
    ) -> list[StructuredTool]:
        """Apply deployment safety and RBAC before tools reach the model.

        The built-in MCP service also provides read-only internet tools.  A
        deployment that disables workspace/Python tools should still be able
        to use those network tools, so the restriction belongs at tool level
        rather than rejecting the whole MCP server.
        """
        filtered = tools
        # ``full_access`` widens the deployment flag but never the tenant
        # boundary: a valid server-derived workspace stays mandatory even when
        # the flag is enabled.  This keeps direct/internal callers from
        # silently falling back to a shared filesystem root.
        workspace_tools_allowed = bool(workspace_id) and (
            settings.enable_local_mcp_tools or permission_mode == "full_access"
        )
        if not workspace_tools_allowed:
            filtered = [tool for tool in filtered if tool.name not in WORKSPACE_TOOL_NAMES]
        else:
            # Arbitrary Python can traverse the whole container filesystem and
            # therefore cannot be made tenant-safe by changing only its cwd.
            # It remains available only to explicitly isolated, direct MCP
            # deployments and is never injected into the multi-tenant API agent.
            filtered = [tool for tool in filtered if tool.name != "run_python"]
        return [
            tool
            for tool in filtered
            if self.auth_manager.is_allowed(user_role, f"tool:{tool.name}", "use")
        ]

    def validate_permissions(self, user_role: str, config: dict) -> None:
        """在打开 SSE 响应前验证所请求资源。"""
        model_id = config.get("model_id", settings.default_model)
        skill_name = config.get("skill_name", "default")
        self.auth_manager.check_permission(user_role, f"model:{model_id}", "use")
        self.auth_manager.check_permission(user_role, f"skill:{skill_name}", "use")
        for mcp_server in config.get("mcp_servers", []):
            self.auth_manager.check_permission(user_role, f"mcp:{mcp_server}", "use")

    @staticmethod
    def _content_to_text(content) -> str:
        """兼容 LangChain 字符串和 content block 两种流式格式。"""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)

    @classmethod
    def _record_usage(cls, config: dict, message: AIMessageChunk) -> None:
        """Accumulate the provider's real token counts, never an estimate.

        ``stream_mode=messages`` yields every chunk of every LLM call in the
        tool loop.  Chunks belonging to one call share an id and only the last
        one normally carries ``usage_metadata``, so keeping the latest value
        per id both avoids double counting and tolerates a provider that
        reports usage on more than one chunk.  A call that never reports usage
        contributes nothing at all: an unmeasured provider must not show up as
        zero consumption.
        """
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict):
            return
        per_message: dict[str, dict[str, int]] = config.setdefault(
            "usage_by_message", {}
        )
        if len(per_message) >= USAGE_MESSAGE_LIMIT:
            return
        # A missing id cannot distinguish separate calls, so such chunks share
        # one stable key instead of growing the mapping without bound.
        key = str(getattr(message, "id", "") or "unidentified")
        per_message[key] = {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }

    @staticmethod
    def summarize_usage(config: dict) -> dict[str, int]:
        """Total the per-call usage captured during one streamed run."""
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "llm_calls": 0,
        }
        per_message = config.get("usage_by_message")
        if not isinstance(per_message, dict):
            return totals
        for entry in per_message.values():
            totals["input_tokens"] += int(entry.get("input_tokens") or 0)
            totals["output_tokens"] += int(entry.get("output_tokens") or 0)
            totals["total_tokens"] += int(entry.get("total_tokens") or 0)
            totals["llm_calls"] += 1
        return totals

    @classmethod
    def _record_tool_trace(cls, config: dict, message: ToolMessage) -> None:
        """Record a bounded completed-tool event without changing text output.

        ``stream_mode=messages`` emits a ``ToolMessage`` after each ToolNode
        invocation. Routes pass a request-local list in ``config`` and persist
        it with the assistant message or governed AgentRun. Keeping the trace
        side-channel separate preserves the existing string streaming API.
        """
        trace = config.get("tool_trace")
        if not isinstance(trace, list) or len(trace) >= TOOL_TRACE_MAX_EVENTS:
            return
        result = cls._content_to_text(message.content)[:TOOL_TRACE_RESULT_LIMIT]
        trace.append(
            {
                "name": message.name or "tool",
                "tool_call_id": message.tool_call_id,
                "status": getattr(message, "status", "success") or "success",
                "result_preview": result,
            }
        )
