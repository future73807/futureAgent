"""
AgentEngine - 统一编排引擎
整合 LiteLLM + LangGraph + MCP + Casbin
"""
import functools
from typing import AsyncGenerator, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.base import RunnableSequence
from langchain_core.tools import StructuredTool
from langgraph.graph import MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from core.model_hub import ModelHub
from core.skill_manager import SkillManager
from core.mcp_manager import MCPManager
from auth.auth_manager import AuthManager
from config import settings


class State(MessagesState):
    next: str


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

    def _agent_node_factory(
        self,
        state: State,
        agent: RunnableSequence,
    ) -> State:
        result = agent.invoke(state)
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
        graph_builder.add_node("tools", ToolNode(tools))

        graph_builder.add_conditional_edges(name, tools_condition)
        graph_builder.add_edge("tools", name)

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

        # 1. 权限校验
        self.auth_manager.check_permission(user_role, f"model:{model_id}", "use")
        self.auth_manager.check_permission(user_role, f"skill:{skill_name}", "use")
        for mcp_server in mcp_servers:
            self.auth_manager.check_permission(user_role, f"mcp:{mcp_server}", "use")

        # 2. 获取所有可用工具 (MCP工具)
        all_tools: list[StructuredTool] = []
        async with self.mcp_manager.connect_all() as sessions:
            for session in sessions:
                tools = await self.mcp_manager.get_mcp_tools(session)
                all_tools.extend(tools)

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
            graph_config = dict(configurable=dict(thread_id="1"))

            async for event in graph.astream_events(
                {"messages": messages},
                graph_config,
                version="v2",
                stream_mode="updates",
            ):
                yield str(event)
