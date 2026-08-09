"""futureAgent 自带的本地 MCP 工具服务。

内置文件工具被限制在 ``MCP_WORKSPACE_ROOT``，默认是容器内的
``/workspace``。Python 执行工具只应在隔离容器内显式启用。
"""
import asyncio
import csv
import hashlib
import hmac
import ipaddress
import os
import socket
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlsplit, urlunsplit

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

DEFAULT_WORKSPACE = Path(__file__).resolve().parent / "workspace"
WORKSPACE_ROOT = Path(os.getenv("MCP_WORKSPACE_ROOT", str(DEFAULT_WORKSPACE))).resolve()
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE = 1_000_000
MAX_OUTPUT_SIZE = 20_000
SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8050"))
MAX_WEB_BYTES = max(10_000, min(int(os.getenv("MCP_WEB_MAX_BYTES", "500000")), 2_000_000))
WEB_TIMEOUT_SECONDS = max(2.0, min(float(os.getenv("MCP_WEB_TIMEOUT_SECONDS", "15")), 60.0))
ENABLE_PYTHON_TOOL = os.getenv("MCP_ENABLE_PYTHON_TOOL", "false").lower() in {"1", "true", "yes", "on"}
ALLOW_DNS_FAKE_IPS = os.getenv("MCP_WEB_ALLOW_DNS_FAKE_IPS", "false").lower() in {"1", "true", "yes", "on"}
WORKSPACE_SIGNING_KEY = os.getenv("MCP_WORKSPACE_SIGNING_KEY", "")
DNS_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
ALLOWED_HOSTS = [
    value.strip()
    for value in os.getenv(
        "MCP_ALLOWED_HOSTS_CSV",
        f"localhost:{SERVER_PORT},127.0.0.1:{SERVER_PORT},[::1]:{SERVER_PORT}",
    ).split(",")
    if value.strip()
]

mcp = FastMCP(
    "futureAgent local tools",
    instructions=(
        "提供受工作区边界保护的文件/CSV工具和受 SSRF 防护的公开网页工具；"
        "Python 执行仅在部署方显式启用时提供。"
    ),
    host="0.0.0.0",
    port=SERVER_PORT,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=ALLOWED_HOSTS,
    ),
)


def _workspace_root_for_context(ctx: Context) -> Path:
    """Resolve an authenticated product workspace to its private file root."""
    request = ctx.request_context.request
    headers = getattr(request, "headers", {}) if request is not None else {}
    workspace_id = headers.get("x-futureagent-workspace", "")
    signature = headers.get("x-futureagent-workspace-signature", "")

    # In-memory MCP transports have no HTTP request.  Supporting the same claim
    # in request metadata keeps protocol-level tests and non-HTTP transports
    # covered without ever exposing it as a tool argument to the model.
    meta = ctx.request_context.meta
    if not workspace_id and meta is not None:
        workspace_id = getattr(meta, "futureagent_workspace", "")
        signature = getattr(meta, "futureagent_workspace_signature", "")

    if not WORKSPACE_SIGNING_KEY or not workspace_id or len(workspace_id) > 200:
        raise PermissionError("文件工具缺少有效的工作区授权")
    expected = hmac.new(
        WORKSPACE_SIGNING_KEY.encode("utf-8"),
        workspace_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise PermissionError("文件工具缺少有效的工作区授权")

    scopes_root = (WORKSPACE_ROOT / ".futureagent" / "workspaces").resolve()
    scopes_root.mkdir(parents=True, exist_ok=True)
    scope_name = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()
    scope_path = scopes_root / scope_name
    if scope_path.is_symlink():
        raise PermissionError("工作区文件目录无效")
    scope_path.mkdir(parents=False, exist_ok=True)
    resolved_scope = scope_path.resolve()
    try:
        resolved_scope.relative_to(scopes_root)
    except ValueError as exc:
        raise PermissionError("工作区文件目录无效") from exc
    return resolved_scope


def _resolve_path(path: str, workspace_root: Path = WORKSPACE_ROOT) -> Path:
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (workspace_root / candidate).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("路径必须位于当前工作区内") from exc
    return resolved


def _ensure_readable_file(path: str, workspace_root: Path = WORKSPACE_ROOT) -> Path:
    resolved = _resolve_path(path, workspace_root)
    if not resolved.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")
    if resolved.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"文件超过 {MAX_FILE_SIZE} 字节限制")
    return resolved


def _write_bytes_atomically(resolved: Path, content: bytes) -> None:
    """Replace one workspace file without exposing a partially written value."""
    resolved.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = None
    if resolved.exists():
        if not resolved.is_file():
            raise IsADirectoryError(str(resolved))
        existing_mode = stat.S_IMODE(resolved.stat().st_mode)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=resolved.parent,
        prefix=f".{resolved.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if existing_mode is not None:
            os.chmod(temporary_path, existing_mode)
        os.replace(temporary_path, resolved)
    finally:
        temporary_path.unlink(missing_ok=True)


def list_files(
    path: str = ".", *, _workspace_root: Path | None = None
) -> list[dict]:
    """列出工作区目录中的文件和子目录。"""
    workspace_root = _workspace_root or WORKSPACE_ROOT
    directory = _resolve_path(path, workspace_root)
    if not directory.is_dir():
        raise NotADirectoryError(path)
    entries = []
    for child in sorted(
        directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
    ):
        # Do not follow links just to render a directory listing.  Reads and
        # writes resolve the target separately and enforce the workspace root.
        is_link = child.is_symlink()
        is_file = not is_link and child.is_file()
        entries.append(
            {
                "name": child.name,
                "path": child.relative_to(workspace_root).as_posix(),
                "type": (
                    "symlink"
                    if is_link
                    else "directory"
                    if child.is_dir()
                    else "file"
                ),
                "size": child.stat().st_size if is_file else None,
            }
        )
    return entries


def read_file(path: str, *, _workspace_root: Path | None = None) -> str:
    """读取工作区内 UTF-8 文本文件。"""
    return _ensure_readable_file(path, _workspace_root or WORKSPACE_ROOT).read_text(
        encoding="utf-8"
    )


def write_file(
    path: str, content: str, *, _workspace_root: Path | None = None
) -> str:
    """将 UTF-8 文本写入工作区；内容最大 1 MB。"""
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_SIZE:
        raise ValueError(f"内容超过 {MAX_FILE_SIZE} 字节限制")
    workspace_root = _workspace_root or WORKSPACE_ROOT
    resolved = _resolve_path(path, workspace_root)
    _write_bytes_atomically(resolved, encoded)
    return f"已写入 {resolved.relative_to(workspace_root).as_posix()} ({len(encoded)} 字节)"


def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
    *,
    _workspace_root: Path | None = None,
) -> dict:
    """精确替换 UTF-8 文件内容；默认要求 old_text 在文件中唯一出现。"""
    if not old_text:
        raise ValueError("old_text 不能为空")
    workspace_root = _workspace_root or WORKSPACE_ROOT
    resolved = _ensure_readable_file(path, workspace_root)
    original = resolved.read_text(encoding="utf-8")
    matches = original.count(old_text)
    if matches == 0:
        raise ValueError("未找到要替换的精确文本；文件未修改")
    if matches > 1 and not replace_all:
        raise ValueError(
            f"要替换的文本出现 {matches} 次；请提供更具体的 old_text，或设置 replace_all=true"
        )

    replacements = matches if replace_all else 1
    updated = original.replace(old_text, new_text, -1 if replace_all else 1)
    encoded = updated.encode("utf-8")
    if len(encoded) > MAX_FILE_SIZE:
        raise ValueError(f"编辑后的文件超过 {MAX_FILE_SIZE} 字节限制；文件未修改")
    _write_bytes_atomically(resolved, encoded)
    return {
        "path": resolved.relative_to(workspace_root).as_posix(),
        "replacements": replacements,
        "size": len(encoded),
    }


def read_csv(
    path: str, limit: int = 50, *, _workspace_root: Path | None = None
) -> dict:
    """读取 CSV 的表头和前若干行，limit 最大为 200。"""
    resolved = _ensure_readable_file(path, _workspace_root or WORKSPACE_ROOT)
    limit = max(1, min(limit, 200))
    with resolved.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for index, row in enumerate(reader):
            if index >= limit:
                break
            rows.append(dict(row))
        return {"columns": reader.fieldnames or [], "rows": rows, "returned_rows": len(rows)}


@mcp.tool(name="list_files")
def scoped_list_files(ctx: Context, path: str = ".") -> list[dict]:
    """列出当前产品工作区目录中的文件和子目录。"""
    return list_files(path, _workspace_root=_workspace_root_for_context(ctx))


@mcp.tool(name="read_file")
def scoped_read_file(ctx: Context, path: str) -> str:
    """读取当前产品工作区内的 UTF-8 文本文件。"""
    return read_file(path, _workspace_root=_workspace_root_for_context(ctx))


@mcp.tool(name="write_file")
def scoped_write_file(ctx: Context, path: str, content: str) -> str:
    """将 UTF-8 文本写入当前产品工作区；内容最大 1 MB。"""
    return write_file(
        path,
        content,
        _workspace_root=_workspace_root_for_context(ctx),
    )


@mcp.tool(name="edit_file")
def scoped_edit_file(
    ctx: Context,
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> dict:
    """精确替换当前产品工作区文件；默认要求目标文本唯一。"""
    return edit_file(
        path,
        old_text,
        new_text,
        replace_all,
        _workspace_root=_workspace_root_for_context(ctx),
    )


@mcp.tool(name="read_csv")
def scoped_read_csv(ctx: Context, path: str, limit: int = 50) -> dict:
    """读取当前产品工作区 CSV 的表头和前若干行，最多 200 行。"""
    return read_csv(
        path,
        limit,
        _workspace_root=_workspace_root_for_context(ctx),
    )


def run_python(code: str, timeout_seconds: int = 10) -> dict:
    """在 MCP 容器的工作区执行 Python 代码，最长运行 30 秒。"""
    if len(code) > 20_000:
        raise ValueError("代码超过 20,000 字符限制")
    timeout_seconds = max(1, min(timeout_seconds, 30))
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", code],
            cwd=WORKSPACE_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Python 执行超过 {timeout_seconds} 秒") from exc
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout[-MAX_OUTPUT_SIZE:],
        "stderr": result.stderr[-MAX_OUTPUT_SIZE:],
        "truncated": len(result.stdout) > MAX_OUTPUT_SIZE or len(result.stderr) > MAX_OUTPUT_SIZE,
    }


if ENABLE_PYTHON_TOOL:
    mcp.tool()(run_python)


def _public_ip(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


def _safe_resolved_ip(address: str) -> bool:
    """Allow public IPs plus Clash-style synthetic DNS targets when enabled."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return parsed.is_global or (ALLOW_DNS_FAKE_IPS and parsed in DNS_FAKE_IP_NETWORK)


@dataclass(frozen=True)
class _ResolvedWebTarget:
    original_url: str
    connect_url: str
    host_header: str
    sni_hostname: str


async def _resolve_public_url(url: str) -> _ResolvedWebTarget:
    """Resolve once and return an IP-pinned request target.

    The request URL uses the exact address checked here.  ``Host`` and TLS SNI
    retain the original hostname, so certificate verification remains intact
    without asking the resolver a second time.
    """
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只允许访问有效的 HTTP 或 HTTPS 地址")
    if parsed.username or parsed.password:
        raise ValueError("联网工具不允许 URL 内嵌凭据")
    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise ValueError("URL 端口无效") from exc
    hostname = parsed.hostname.encode("idna").decode("ascii")
    selected_address: str
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        port = explicit_port or (443 if parsed.scheme == "https" else 80)
        try:
            records = await asyncio.to_thread(
                socket.getaddrinfo, hostname, port, 0, socket.SOCK_STREAM
            )
        except OSError as exc:
            raise ValueError("无法解析目标站点") from exc
        addresses = list(dict.fromkeys(record[4][0] for record in records))
        if not addresses or any(not _safe_resolved_ip(address) for address in addresses):
            raise ValueError("联网工具不允许访问本地或私有网络地址")
        selected_address = addresses[0]
    else:
        if not _public_ip(hostname):
            raise ValueError("联网工具不允许访问本地或私有网络地址")
        selected_address = hostname

    ip_value = ipaddress.ip_address(selected_address)
    pinned_host = f"[{selected_address}]" if ip_value.version == 6 else selected_address
    pinned_netloc = f"{pinned_host}:{explicit_port}" if explicit_port else pinned_host
    default_port = 443 if parsed.scheme == "https" else 80
    original_host = f"[{hostname}]" if ":" in hostname else hostname
    host_header = (
        f"{original_host}:{explicit_port}"
        if explicit_port and explicit_port != default_port
        else original_host
    )
    connect_url = urlunsplit(
        (parsed.scheme, pinned_netloc, parsed.path or "/", parsed.query, "")
    )
    return _ResolvedWebTarget(
        original_url=url,
        connect_url=connect_url,
        host_header=host_header,
        sni_hostname=hostname,
    )


class _ReadableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth and data.strip():
            self.parts.append(data.strip())


def _readable_html(value: str) -> str:
    parser = _ReadableHTMLParser()
    parser.feed(value)
    return "\n".join(parser.parts)


async def _fetch_web_resource(url: str, *, preserve_html: bool = False) -> dict:
    current_url = url
    timeout = httpx.Timeout(WEB_TIMEOUT_SECONDS)
    for _redirect in range(4):
        target = await _resolve_public_url(current_url)
        # A fresh client per redirect prevents connection pooling across two
        # hostnames that happen to resolve to the same address but require
        # different TLS identities.
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "futureAgent-MCP/1.0"},
        ) as client:
            async with client.stream(
                "GET",
                target.connect_url,
                headers={"Host": target.host_header},
                extensions={"sni_hostname": target.sni_hostname},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise RuntimeError("远程站点返回了无目标的重定向")
                    current_url = urljoin(current_url, location)
                    continue
                if response.status_code >= 400:
                    raise RuntimeError(f"远程站点返回 HTTP {response.status_code}")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                allowed = (
                    not content_type
                    or content_type.startswith("text/")
                    or content_type in {
                        "application/json",
                        "application/xml",
                        "application/xhtml+xml",
                    }
                )
                if not allowed:
                    raise ValueError("联网工具仅支持文本、HTML、JSON 和 XML 内容")
                chunks: list[bytes] = []
                size = 0
                truncated = False
                async for chunk in response.aiter_bytes():
                    remaining = MAX_WEB_BYTES - size
                    if len(chunk) > remaining:
                        chunks.append(chunk[:remaining])
                        truncated = True
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_WEB_BYTES:
                        truncated = True
                        break
                raw = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                text = raw
                if not preserve_html and content_type in {"text/html", "application/xhtml+xml"}:
                    text = _readable_html(raw)
                return {
                    "url": current_url,
                    "status": response.status_code,
                    "content_type": content_type or "text/plain",
                    "text": text[:MAX_WEB_BYTES],
                    "truncated": truncated,
                }
    raise RuntimeError("远程站点重定向次数过多")


@mcp.tool()
async def fetch_url(url: str) -> dict:
    """读取公开 HTTP/HTTPS 网页；拒绝本机、内网和云元数据地址。"""
    return await _fetch_web_resource(url)


class _SearchResultParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._href = ""
        self._title_parts: list[str] = []
        self._in_title = False
        self._in_snippet = False
        self._snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        if tag == "a" and "result__a" in classes:
            self._in_title = True
            self._href = attributes.get("href", "")
            self._title_parts = []
        if "result__snippet" in classes:
            self._in_snippet = True
            self._snippet_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
            title = " ".join(self._title_parts).strip()
            if title and self._href:
                self.results.append({"title": title, "url": _search_result_url(self._href), "snippet": ""})
        if self._in_snippet and tag in {"a", "div", "span"}:
            self._in_snippet = False
            if self.results:
                self.results[-1]["snippet"] = " ".join(self._snippet_parts).strip()

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self._title_parts.append(data.strip())
        if self._in_snippet and data.strip():
            self._snippet_parts.append(data.strip())


def _search_result_url(value: str) -> str:
    candidate = "https:" + value if value.startswith("//") else value
    parsed = urlsplit(candidate)
    redirected = parse_qs(parsed.query).get("uddg", [])
    return unquote(redirected[0]) if redirected else candidate


@mcp.tool()
async def web_search(query: str, limit: int = 5) -> dict:
    """通过无需密钥的 DuckDuckGo HTML 搜索公开网页，最多返回 10 条。"""
    query = query.strip()
    if not query or len(query) > 500:
        raise ValueError("搜索词长度必须为 1 到 500 个字符")
    limit = max(1, min(limit, 10))
    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        page = await _fetch_web_resource(search_url, preserve_html=True)
    except Exception as exc:
        raise RuntimeError(
            "网页搜索服务暂时不可用；该后端无需 API 密钥，请检查公网、DNS 或上游限流"
        ) from exc
    parser = _SearchResultParser()
    parser.feed(page["text"])
    results = [result for result in parser.results if result["url"].startswith(("http://", "https://"))]
    selected = results[:limit]
    response = {
        "query": query,
        "provider": "duckduckgo_html",
        "results": selected,
        "result_count": len(selected),
    }
    if not selected:
        response["warning"] = "搜索服务未返回可解析结果，可能是无结果、网络限制或上游页面变更"
    return response


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
