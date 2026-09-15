"""futureAgent 联调用的第二个 MCP 服务：Python 项目工具。

与 ``server.py`` 的区别：这里只面向「某个 Python 项目」的只读探查与受控命令，
用来验证产品能同时挂多个 MCP 服务、并把它们的工具一起交给模型。

工作区隔离沿用同一套服务端签名声明（``x-futureagent-workspace`` +
``x-futureagent-workspace-signature``），模型看不到也伪造不了。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

DEFAULT_WORKSPACE = Path(__file__).resolve().parent / "workspace"
WORKSPACE_ROOT = Path(os.getenv("MCP_WORKSPACE_ROOT", str(DEFAULT_WORKSPACE))).resolve()
WORKSPACE_SIGNING_KEY = os.getenv(
    "MCP_WORKSPACE_SIGNING_KEY",
    "change-this-development-mcp-secret-before-production",
)
SERVER_PORT = int(os.getenv("PYTHON_TOOLS_MCP_PORT", "8051"))
COMMAND_TIMEOUT_SECONDS = max(5, min(int(os.getenv("PYTHON_TOOLS_TIMEOUT", "120")), 600))
MAX_OUTPUT = 12_000
IGNORED_DIRS = {".futureagent", "__pycache__", ".git", ".venv", "node_modules"}
ALLOWED_HOSTS = [
    value.strip()
    for value in os.getenv(
        "MCP_ALLOWED_HOSTS_CSV",
        f"localhost:{SERVER_PORT},127.0.0.1:{SERVER_PORT},[::1]:{SERVER_PORT}",
    ).split(",")
    if value.strip()
]

mcp = FastMCP(
    "futureAgent python project tools",
    instructions=(
        "面向工作区内 Python 项目的只读工具：列目录、读文件、跑单元测试、"
        "做语法检查。所有路径都被限制在调用方所属工作区的私有目录内。"
    ),
    host="0.0.0.0",
    port=SERVER_PORT,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=ALLOWED_HOSTS,
    ),
)


def _workspace_root_for_context(ctx: Context) -> Path:
    """把签名声明解析成该工作区的私有目录。"""
    request = ctx.request_context.request
    headers = getattr(request, "headers", {}) if request is not None else {}
    workspace_id = headers.get("x-futureagent-workspace", "")
    signature = headers.get("x-futureagent-workspace-signature", "")

    meta = ctx.request_context.meta
    if not workspace_id and meta is not None:
        workspace_id = getattr(meta, "futureagent_workspace", "")
        signature = getattr(meta, "futureagent_workspace_signature", "")

    if not WORKSPACE_SIGNING_KEY or not workspace_id or len(workspace_id) > 200:
        raise PermissionError("项目工具缺少有效的工作区授权")
    expected = hmac.new(
        WORKSPACE_SIGNING_KEY.encode("utf-8"),
        workspace_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise PermissionError("项目工具缺少有效的工作区授权")

    scopes_root = (WORKSPACE_ROOT / ".futureagent" / "workspaces").resolve()
    scopes_root.mkdir(parents=True, exist_ok=True)
    scope_path = scopes_root / hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()
    if scope_path.is_symlink():
        raise PermissionError("工作区目录无效")
    scope_path.mkdir(parents=True, exist_ok=True)
    resolved = scope_path.resolve()
    try:
        resolved.relative_to(scopes_root)
    except ValueError as exc:
        raise PermissionError("工作区目录无效") from exc
    return resolved


def _resolve(root: Path, path: str) -> Path:
    candidate = Path(path or ".")
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError("路径必须位于当前工作区内") from exc
    return resolved


def _run(command: list[str], cwd: Path) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return f"命令超时（>{COMMAND_TIMEOUT_SECONDS}s）：{' '.join(command)}"
    except OSError as exc:  # 解释器缺失等
        return f"命令无法执行：{exc}"
    output = (completed.stdout or "") + (completed.stderr or "")
    return output.strip()[:MAX_OUTPUT] or f"（无输出，退出码 {completed.returncode}）"


@mcp.tool(name="project_tree")
def project_tree(ctx: Context, project: str = ".", max_files: int = 200) -> list[dict]:
    """列出某个 Python 项目下的文件（相对路径、字节数）。"""
    root = _resolve(_workspace_root_for_context(ctx), project)
    if not root.exists():
        return [{"error": f"项目目录不存在：{project}"}]
    entries: list[dict] = []
    for path in sorted(root.rglob("*")):
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_dir():
            continue
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
            }
        )
        if len(entries) >= max(1, min(int(max_files), 1000)):
            break
    return entries


@mcp.tool(name="read_project_file")
def read_project_file(ctx: Context, path: str) -> str:
    """读取项目内的文本文件（最大 200KB）。"""
    root = _workspace_root_for_context(ctx)
    target = _resolve(root, path)
    if not target.is_file():
        return f"文件不存在：{path}"
    if target.stat().st_size > 200_000:
        return f"文件过大，拒绝读取：{path}"
    return target.read_text(encoding="utf-8", errors="replace")


@mcp.tool(name="run_project_tests")
def run_project_tests(ctx: Context, project: str = ".", pattern: str = "tests") -> str:
    """在项目目录下执行 `py -m unittest discover -s <pattern>` 并返回输出。"""
    root = _resolve(_workspace_root_for_context(ctx), project)
    if not root.is_dir():
        return f"项目目录不存在：{project}"
    safe_pattern = "".join(ch for ch in pattern if ch.isalnum() or ch in "._-") or "tests"
    # 指错目录时 unittest 的报错很难懂（会把别处的同名包导进来）。先自己看一眼，
    # 把可用的候选目录列给模型，省掉一轮试错。
    if not (root / safe_pattern).is_dir():
        candidates = sorted(
            item.name
            for item in root.iterdir()
            if item.is_dir() and item.name not in IGNORED_DIRS
        )
        return (
            f"目录 {project} 下没有 {safe_pattern}/，无法发现测试。"
            f"现有子目录：{'、'.join(candidates) or '（无）'}"
        )
    return _run(
        [sys.executable or "py", "-m", "unittest", "discover", "-s", safe_pattern],
        cwd=root,
    )


@mcp.tool(name="check_python_syntax")
def check_python_syntax(ctx: Context, path: str) -> str:
    """对单个 .py 文件做语法检查，返回编译错误。"""
    root = _workspace_root_for_context(ctx)
    target = _resolve(root, path)
    if not target.is_file():
        return f"文件不存在：{path}"
    if target.suffix != ".py":
        return f"只支持 .py 文件：{path}"
    return _run([sys.executable or "py", "-m", "py_compile", str(target)], cwd=target.parent)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
