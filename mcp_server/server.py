"""futureAgent 自带的本地 MCP 工具服务。

所有文件操作都被限制在 ``MCP_WORKSPACE_ROOT``，默认是容器内的
``/workspace``。生产环境应只挂载确实需要 Agent 访问的目录。
"""
import csv
import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

DEFAULT_WORKSPACE = Path(__file__).resolve().parent / "workspace"
WORKSPACE_ROOT = Path(os.getenv("MCP_WORKSPACE_ROOT", str(DEFAULT_WORKSPACE))).resolve()
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE = 1_000_000
MAX_OUTPUT_SIZE = 20_000

mcp = FastMCP(
    "futureAgent local tools",
    instructions="提供受工作区边界保护的文件和 Python 工具。",
    host="0.0.0.0",
    port=int(os.getenv("MCP_SERVER_PORT", "8050")),
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _resolve_path(path: str) -> Path:
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (WORKSPACE_ROOT / candidate).resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise ValueError("路径必须位于 MCP_WORKSPACE_ROOT 内") from exc
    return resolved


def _ensure_readable_file(path: str) -> Path:
    resolved = _resolve_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")
    if resolved.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"文件超过 {MAX_FILE_SIZE} 字节限制")
    return resolved


@mcp.tool()
def list_files(path: str = ".") -> list[dict]:
    """列出工作区目录中的文件和子目录。"""
    directory = _resolve_path(path)
    if not directory.is_dir():
        raise NotADirectoryError(path)
    return [
        {
            "name": child.name,
            "path": child.relative_to(WORKSPACE_ROOT).as_posix(),
            "type": "directory" if child.is_dir() else "file",
            "size": child.stat().st_size if child.is_file() else None,
        }
        for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    ]


@mcp.tool()
def read_file(path: str) -> str:
    """读取工作区内 UTF-8 文本文件。"""
    return _ensure_readable_file(path).read_text(encoding="utf-8")


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """将 UTF-8 文本写入工作区；内容最大 1 MB。"""
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_SIZE:
        raise ValueError(f"内容超过 {MAX_FILE_SIZE} 字节限制")
    resolved = _resolve_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_bytes(encoded)
    return f"已写入 {resolved.relative_to(WORKSPACE_ROOT).as_posix()} ({len(encoded)} 字节)"


@mcp.tool()
def read_csv(path: str, limit: int = 50) -> dict:
    """读取 CSV 的表头和前若干行，limit 最大为 200。"""
    resolved = _ensure_readable_file(path)
    limit = max(1, min(limit, 200))
    with resolved.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for index, row in enumerate(reader):
            if index >= limit:
                break
            rows.append(dict(row))
        return {"columns": reader.fieldnames or [], "rows": rows, "returned_rows": len(rows)}


@mcp.tool()
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


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
