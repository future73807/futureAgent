"""
MCPManager - MCP 客户端管理
基于官方 MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
"""
from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncGenerator

from mcp import ClientSession
from mcp.client.sse import sse_client
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.tools import StructuredTool

from config import settings


class MCPManager:
    """管理多个 MCP Server 的连接和工具加载"""

    def __init__(self):
        self.sessions: dict[str, ClientSession] = {}
        self._exit_stack: AsyncExitStack | None = None

    @asynccontextmanager
    async def connect(self, mcp_host: str = "mcp"):
        """连接到指定 MCP Server"""
        async with sse_client(
            f"http://{mcp_host}:{settings.mcp_server_port}/sse"
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                self.sessions[mcp_host] = session
                yield session

    @asynccontextmanager
    async def connect_all(self):
        """连接所有配置的 MCP Server"""
        async with AsyncExitStack() as stack:
            sessions = []
            for hostname in settings.mcp_hostnames:
                session = await stack.enter_async_context(
                    self._single_connection(hostname)
                )
                self.sessions[hostname] = session
                sessions.append(session)
            try:
                yield sessions
            finally:
                self.sessions.clear()

    @asynccontextmanager
    async def _single_connection(
        self, mcp_host: str
    ) -> AsyncGenerator[ClientSession, None]:
        async with sse_client(
            f"http://{mcp_host}:{settings.mcp_server_port}/sse"
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session

    async def get_mcp_tools(
        self, session: ClientSession
    ) -> list[StructuredTool]:
        """获取 MCP Server 提供的工具，转换为 LangChain Tool 格式"""
        return await load_mcp_tools(session)

    async def get_all_tools(self) -> list[StructuredTool]:
        """获取所有 MCP Server 的工具"""
        all_tools = []
        for hostname, session in self.sessions.items():
            tools = await self.get_mcp_tools(session)
            all_tools.extend(tools)
        return all_tools

    async def list_tools(
        self, session: ClientSession
    ) -> list[str]:
        """列出 MCP Server 提供的所有工具名称"""
        response = await session.list_tools()
        return [tool.name for tool in response.tools]

    async def call_tool(
        self, session: ClientSession, tool_name: str, arguments: dict
    ):
        """调用 MCP Server 上的工具"""
        response = await session.call_tool(tool_name, arguments=arguments)
        return response.content[0].text
