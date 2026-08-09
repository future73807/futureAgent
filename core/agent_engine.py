"""
AgentEngine - 统一编排引擎
整合 LiteLLM + LangGraph + MCP + Casbin
"""
import functools
import uuid
from typing import AsyncGenerator, Optional

from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage
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
    }
)
TOOL_TRACE_MAX_EVENTS = 64
TOOL_TRACE_RESULT_LIMIT = 2_000


class State(MessagesState):
    pass


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
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
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
    ) -> CompiledStateGraph:
        graph_builder = StateGraph(State)
        graph_builder.add_node(name, agent_node)
        if tools:
            graph_builder.add_node("tools", ToolNode(tools))
            graph_builder.add_conditional_edges(name, tools_condition)
            graph_builder.add_edge("tools", name)
        else:
            graph_builder.add_edge(name, END)

        graph_builder.set_entry_point(name)
        graph = graph_builder.compile(checkpointer=checkpointer)
        return graph

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
            checkpointer: LangGraph 检查点保存器

        Yields:
            流式响应内容
        """
        model_id = config.get("model_id", settings.default_model)
        skill_name = config.get("skill_name", "default")
        mcp_servers = config.get("mcp_servers", [])

        # 1. 权限校验（API 层也会提前执行一次，以便返回正确 HTTP 状态）
        self.validate_permissions(user_role, config)

        # 2. 获取所有可用工具 (MCP工具)
        all_tools: list[StructuredTool] = []
        workspace_id = config.get("workspace_id")
        async with self.mcp_manager.connect_many(
            mcp_servers, workspace_id=workspace_id
        ) as sessions:
            for session in sessions:
                tools = await self.mcp_manager.get_mcp_tools(session)
                all_tools.extend(tools)

            # 未授权工具不会进入模型上下文，即使 MCP 服务本身可访问。
            all_tools = self.filter_available_tools(
                user_role, all_tools, workspace_id=workspace_id
            )

            # 3. 装配 Skill (过滤工具 + 获取提示词)
            skill_data = self.skill_manager.assemble_skill(skill_name, all_tools)

            # 4. 通过 ModelHub 获取 ChatModel (LiteLLM 或后备方案)
            llm = self.model_hub.get_chat_model(model_id=model_id)

            # 5. 构建 LangGraph Agent
            agent = self._agent_factory(llm, skill_data["tools"], skill_data["system_prompt"])
            worker_node = functools.partial(self._agent_node_factory, agent=agent)
            graph = self._graph_factory(
                worker_node,
                skill_data["tools"],
                checkpointer,
                name="agent_node",
            )

            # 6. 构建消息
            messages = [HumanMessage(content=query)]

            # 7. 执行并流式返回
            graph_config = {
                "configurable": {
                    "thread_id": config.get("thread_id") or str(uuid.uuid4())
                }
            }

            async for message, _metadata in graph.astream(
                {"messages": messages},
                graph_config,
                stream_mode="messages",
            ):
                if isinstance(message, AIMessageChunk):
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
    ) -> list[StructuredTool]:
        """Apply deployment safety and RBAC before tools reach the model.

        The built-in MCP service also provides read-only internet tools.  A
        deployment that disables workspace/Python tools should still be able
        to use those network tools, so the restriction belongs at tool level
        rather than rejecting the whole MCP server.
        """
        filtered = tools
        # A valid server-derived workspace is mandatory even when the feature
        # flag is enabled.  This keeps direct/internal callers from silently
        # falling back to a shared filesystem root.
        if not settings.enable_local_mcp_tools or not workspace_id:
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
