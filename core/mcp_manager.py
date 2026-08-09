"""MCP 客户端连接、发现与工具加载。"""
import asyncio
import hashlib
import hmac
import ipaddress
from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import urlparse, urlsplit, urlunsplit

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.tools import StructuredTool

from config import settings


class MCPManager:
    """管理多个 MCP Server 的连接和工具加载"""

    def __init__(self, servers: dict[str, str] | None = None):
        # An explicit empty mapping is useful for offline/test operation and
        # must not silently fall back to environment-configured servers.
        self.servers = dict(settings.mcp_servers if servers is None else servers)
        self.sessions: dict[str, ClientSession] = {}

    @asynccontextmanager
    async def connect(self, server_name: str):
        """连接到指定 MCP Server"""
        if server_name not in self.servers:
            raise ValueError(f"MCP 服务“{server_name}”尚未配置")
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
    async def connect_many(
        self, server_names: list[str], *, workspace_id: str | None = None
    ):
        """只连接本次请求选择的 MCP 服务。

        The bundled ``local_tools`` service receives a server-authenticated
        workspace claim.  File paths are then rooted by the MCP server itself,
        so a model cannot escape a tenant boundary with ``..``, absolute paths,
        or a symlink already present in the shared volume.
        """
        unique_names = list(dict.fromkeys(server_names))
        unknown = [name for name in unique_names if name not in self.servers]
        if unknown:
            raise ValueError(f"未知 MCP 服务：{', '.join(unknown)}")

        async with AsyncExitStack() as stack:
            sessions = []
            for server_name in unique_names:
                session = await stack.enter_async_context(
                    self._single_connection(server_name, workspace_id=workspace_id)
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
        self, server_name: str, *, workspace_id: str | None = None
    ) -> AsyncGenerator[ClientSession, None]:
        headers = self.workspace_scope_headers(workspace_id) if server_name == "local_tools" else None
        async with self._open_transport(self.servers[server_name], headers=headers) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session

    @asynccontextmanager
    async def _open_transport(self, url: str, *, headers: dict[str, str] | None = None):
        """优先使用当前 MCP Streamable HTTP，并兼容已有 SSE 地址。"""
        client_factory = self._httpx_client_factory(url)
        if url.rstrip("/").endswith("/sse"):
            async with sse_client(
                url,
                headers=headers,
                timeout=settings.mcp_connect_timeout,
                sse_read_timeout=60,
                httpx_client_factory=client_factory,
            ) as streams:
                yield streams
            return
        timeout = httpx.Timeout(settings.mcp_connect_timeout, read=60)
        async with client_factory(headers=headers, timeout=timeout) as client:
            # Some FastMCP versions do not complete the optional DELETE-based
            # session termination on Windows.  Waiting for that response kept
            # an otherwise completed chat request alive until the SSE read
            # timeout.  Closing the transport/client is sufficient and makes
            # cleanup deterministic; the server releases the disconnected
            # stream independently.
            async with streamable_http_client(
                url,
                http_client=client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _session_id):
                yield read_stream, write_stream

    @staticmethod
    def workspace_scope_headers(workspace_id: str | None) -> dict[str, str] | None:
        """Create an authenticated local-MCP workspace claim.

        Missing scope deliberately produces no headers.  The bundled server
        will still allow discovery, but refuses every file operation.
        """
        if not workspace_id:
            return None
        signature = hmac.new(
            settings.mcp_workspace_signing_key.encode("utf-8"),
            workspace_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-FutureAgent-Workspace": workspace_id,
            "X-FutureAgent-Workspace-Signature": signature,
        }

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
                {
                    "name": name,
                    "url": self._display_url(url),
                    "status": "configured",
                    "tools": [],
                }
                for name, url in self.servers.items()
            ]
        return await asyncio.gather(
            *(self._probe_server(name, url) for name, url in self.servers.items())
        )

    async def _probe_server(self, name: str, url: str) -> dict:
        display_url = self._display_url(url)
        try:
            async with asyncio.timeout(settings.mcp_connect_timeout):
                async with self.connect(name) as session:
                    tools = await self.list_tools(session)
            return {
                "name": name,
                "url": display_url,
                "status": "online",
                "tools": tools,
            }
        except Exception:
            # 连接库异常可能包含内部主机名、鉴权头或上游实现细节；这些信息
            # 不应通过管理员界面直接暴露。保留统一提示，详情由部署日志处理。
            return {
                "name": name,
                "url": display_url,
                "status": "offline",
                "tools": [],
                "error": "服务探测失败，请检查地址、网络或鉴权配置。",
            }

    @staticmethod
    def _display_url(url: str) -> str:
        """Return an endpoint suitable for admin UI without embedded secrets."""
        parsed = urlsplit(url)
        hostname = parsed.hostname or ""
        host = f"[{hostname}]" if ":" in hostname else hostname
        try:
            port = parsed.port
        except ValueError:
            port = None
        netloc = f"{host}:{port}" if port else host
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
