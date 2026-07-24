"""MCP 客户端连接、发现与工具加载。"""
import asyncio
import ipaddress
from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.tools import StructuredTool

from config import settings


class MCPManager:
    """管理多个 MCP Server 的连接和工具加载"""

    def __init__(self, servers: dict[str, str] | None = None):
        self.servers = dict(servers or settings.mcp_servers)
        self.sessions: dict[str, ClientSession] = {}

    @asynccontextmanager
    async def connect(self, server_name: str):
        """连接到指定 MCP Server"""
        if server_name not in self.servers:
            raise ValueError(f"MCP server '{server_name}' is not configured")
        async with self._open_transport(self.servers[server_name]) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                self.sessions[server_name] = session
                try:
                    yield session
                finally:
                    self.sessions.pop(server_name, None)

    @asynccontextmanager
    async def connect_all(self):
        """连接所有配置的 MCP Server"""
        async with self.connect_many(list(self.servers)) as sessions:
            yield sessions

    @asynccontextmanager
    async def connect_many(self, server_names: list[str]):
        """只连接本次请求选择的 MCP 服务。"""
        unique_names = list(dict.fromkeys(server_names))
        unknown = [name for name in unique_names if name not in self.servers]
        if unknown:
            raise ValueError(f"Unknown MCP server(s): {', '.join(unknown)}")

        async with AsyncExitStack() as stack:
            sessions = []
            for server_name in unique_names:
                session = await stack.enter_async_context(
                    self._single_connection(server_name)
                )
                self.sessions[server_name] = session
                sessions.append(session)
            try:
                yield sessions
            finally:
                for server_name in unique_names:
                    self.sessions.pop(server_name, None)

    @asynccontextmanager
    async def _single_connection(
        self, server_name: str
    ) -> AsyncGenerator[ClientSession, None]:
        async with self._open_transport(self.servers[server_name]) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session

    @asynccontextmanager
    async def _open_transport(self, url: str):
        """优先使用当前 MCP Streamable HTTP，并兼容已有 SSE 地址。"""
        client_factory = self._httpx_client_factory(url)
        if url.rstrip("/").endswith("/sse"):
            async with sse_client(
                url,
                timeout=settings.mcp_connect_timeout,
                sse_read_timeout=60,
                httpx_client_factory=client_factory,
            ) as streams:
                yield streams
            return
        async with streamablehttp_client(
            url,
            timeout=settings.mcp_connect_timeout,
            sse_read_timeout=60,
            httpx_client_factory=client_factory,
        ) as (read_stream, write_stream, _session_id):
            yield read_stream, write_stream

    @staticmethod
    def _httpx_client_factory(url: str):
        """本地/Docker MCP 地址不应被系统 HTTP 代理劫持。"""
        hostname = urlparse(url).hostname or ""
        bypass_proxy = hostname == "localhost" or "." not in hostname
        try:
            bypass_proxy = bypass_proxy or ipaddress.ip_address(hostname).is_private
        except ValueError:
            pass

        def factory(headers=None, timeout=None, auth=None):
            return httpx.AsyncClient(
                headers=headers,
                timeout=timeout,
                auth=auth,
                follow_redirects=True,
                trust_env=not bypass_proxy,
            )

        return factory

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
        if not response.content:
            return ""
        first = response.content[0]
        return getattr(first, "text", str(first))

    async def list_servers(self, probe: bool = False) -> list[dict]:
        """列出已配置服务；可选地连接探测状态和工具。"""
        if not probe:
            return [
                {"name": name, "url": url, "status": "configured", "tools": []}
                for name, url in self.servers.items()
            ]
        return await asyncio.gather(
            *(self._probe_server(name, url) for name, url in self.servers.items())
        )

    async def _probe_server(self, name: str, url: str) -> dict:
        try:
            async with asyncio.timeout(settings.mcp_connect_timeout):
                async with self.connect(name) as session:
                    tools = await self.list_tools(session)
            return {"name": name, "url": url, "status": "online", "tools": tools}
        except Exception as exc:
            return {
                "name": name,
                "url": url,
                "status": "offline",
                "tools": [],
                "error": str(exc),
            }
