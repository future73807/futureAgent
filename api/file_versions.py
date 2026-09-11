"""文件版本与差异分析：读取 MCP 工作区里 AI 改动的历史快照。

版本快照由 MCP 工具服务在覆盖文件前写入，存放在租户目录之外，因此模型的
文件工具既看不到也改不到它们。API 通过与交付物登记完全相同的方式取回数据：
带签名的工作区声明调用 ``local_tools``，再在服务端生成差异。

二进制格式（xlsx/docx/图片/PDF）不做文本差异，而是如实返回
``diff_available=false`` 与各版本的大小和摘要——伪造一份不可读的"差异"
比明确说"比不了"更糟。
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import (
    WorkspaceContext,
    get_workspace_context,
    require_workspace_role,
)
from api.deliverables import DEFAULT_TOOL_SERVER, KIND_BY_EXTENSION, _tool_text_to_json
from core.mcp_manager import MCPManager

router = APIRouter()

# 差异行数上限：超大文件的完整差异会撑爆响应，截断时明确标注。
DIFF_MAX_LINES = 4_000
# 版本号 0 表示"当前工作区文件"，用于把最新快照与线上内容对比。
CURRENT_VERSION = 0
BINARY_KINDS = {"xlsx", "docx", "image", "pdf"}


def _is_binary_path(path: str) -> bool:
    kind, _content_type = KIND_BY_EXTENSION.get(
        Path(path).suffix.lower(), ("file", "application/octet-stream")
    )
    return kind in BINARY_KINDS


async def _call_tool(
    workspace_id: str, tool_name: str, arguments: dict[str, Any], server: str
) -> Any:
    """调用本地工具服务；连接失败向上抛出由路由统一转译。"""
    manager = MCPManager()
    async with manager.connect_many([server], workspace_id=workspace_id) as sessions:
        return await manager.call_tool(sessions[0], tool_name, arguments)


def _tool_text(payload: Any) -> str:
    """取出工具返回的文本。

    FastMCP 会把字符串结果序列化为 JSON，因此带引号时先试反序列化；
    解不开就只剔除外层引号，不得丢内容。
    """
    if isinstance(payload, str):
        text = payload
    else:
        text = str(payload)
    if text.startswith('"') and text.endswith('"'):
        try:
            decoded = json.loads(text)
        except ValueError:
            return text[1:-1]
        if isinstance(decoded, str):
            return decoded
    return text


async def fetch_file_versions(
    workspace_id: str, path: str, server: str = DEFAULT_TOOL_SERVER
) -> list[dict[str, Any]]:
    payload = await _call_tool(
        workspace_id, "list_file_versions", {"path": path}, server
    )
    return [item for item in _tool_text_to_json(payload) if isinstance(item, dict)]


async def fetch_version_text(
    workspace_id: str, path: str, version: int, server: str = DEFAULT_TOOL_SERVER
) -> str:
    payload = await _call_tool(
        workspace_id, "read_file_version", {"path": path, "version": version}, server
    )
    return _tool_text(payload)


async def fetch_current_text(
    workspace_id: str, path: str, server: str = DEFAULT_TOOL_SERVER
) -> str:
    payload = await _call_tool(workspace_id, "read_file", {"path": path}, server)
    return _tool_text(payload)


def _unified_lines(
    old: str, new: str, path: str, from_version: int, to_version: int
) -> list[str]:
    return list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=f"{path}@v{from_version}",
            tofile=f"{path}@current" if to_version == CURRENT_VERSION else f"{path}@v{to_version}",
            lineterm="",
        )
    )


def _side_by_side_rows(old: str, new: str) -> list[dict[str, str]]:
    """按 SequenceMatcher 的操作码生成左右对照行。"""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    rows: list[dict[str, str]] = []
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                rows.append(
                    {
                        "kind": "equal",
                        "left": old_lines[i1 + offset],
                        "right": new_lines[j1 + offset],
                    }
                )
        elif tag == "delete":
            rows.extend({"kind": "delete", "left": line, "right": ""} for line in old_lines[i1:i2])
        elif tag == "insert":
            rows.extend({"kind": "insert", "left": "", "right": line} for line in new_lines[j1:j2])
        else:
            left = old_lines[i1:i2]
            right = new_lines[j1:j2]
            for offset in range(max(len(left), len(right))):
                rows.append(
                    {
                        "kind": "replace",
                        "left": left[offset] if offset < len(left) else "",
                        "right": right[offset] if offset < len(right) else "",
                    }
                )
        if len(rows) >= DIFF_MAX_LINES:
            break
    return rows[:DIFF_MAX_LINES]


def _translate(exc: Exception, unavailable_message: str) -> HTTPException:
    """把工具服务的失败转译成不泄露内部细节的 HTTP 错误。"""
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=502, detail=unavailable_message)


@router.get("/v1/workspace/files/versions")
async def list_workspace_file_versions(
    path: str = Query(min_length=1, max_length=400),
    server: str = Query(DEFAULT_TOOL_SERVER, max_length=60),
    context: WorkspaceContext = Depends(get_workspace_context),
) -> dict[str, Any]:
    """列出一个工作区文件的历史版本清单（不含内容）。"""
    require_workspace_role(context, "owner", "admin", "member", "viewer")
    try:
        versions = await fetch_file_versions(context.workspace.id, path, server)
    except Exception as exc:  # noqa: BLE001 - 连接细节不外露
        raise _translate(exc, "工具服务暂不可用，无法读取文件版本") from exc
    return {
        "path": path,
        "versions": versions,
        "retention_note": "清单只保留最近若干个版本；更早的改动已被保留策略清理。",
    }


@router.get("/v1/workspace/files/diff")
async def diff_workspace_file_versions(
    path: str = Query(min_length=1, max_length=400),
    from_version: int = Query(1, ge=0, alias="from"),
    to_version: int = Query(0, ge=0, alias="to"),
    diff_format: str = Query("unified", alias="format", pattern="^(unified|side-by-side)$"),
    server: str = Query(DEFAULT_TOOL_SERVER, max_length=60),
    context: WorkspaceContext = Depends(get_workspace_context),
) -> dict[str, Any]:
    """比对工作区文件的两个版本；``to=0`` 表示当前文件内容。"""
    require_workspace_role(context, "owner", "admin", "member", "viewer")
    if from_version == to_version:
        raise HTTPException(status_code=422, detail="请选择两个不同的版本进行比对")
    if _is_binary_path(path):
        # 二进制格式没有可信的文本差异，明确告知而不是硬凑。
        try:
            versions = await fetch_file_versions(context.workspace.id, path, server)
        except Exception as exc:  # noqa: BLE001
            raise _translate(exc, "工具服务暂不可用，无法读取文件版本") from exc
        return {
            "path": path,
            "from": from_version,
            "to": to_version,
            "format": diff_format,
            "diff_available": False,
            "reason": "该文件格式为二进制，不提供文本差异；可分别下载各版本后自行比对。",
            "versions": versions,
        }
    try:
        old = (
            await fetch_current_text(context.workspace.id, path, server)
            if from_version == CURRENT_VERSION
            else await fetch_version_text(context.workspace.id, path, from_version, server)
        )
        new = (
            await fetch_current_text(context.workspace.id, path, server)
            if to_version == CURRENT_VERSION
            else await fetch_version_text(context.workspace.id, path, to_version, server)
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc, "工具服务暂不可用，无法读取文件版本内容") from exc

    if diff_format == "side-by-side":
        rows = _side_by_side_rows(old, new)
        return {
            "path": path,
            "from": from_version,
            "to": to_version,
            "format": diff_format,
            "diff_available": True,
            "rows": rows,
            "truncated": len(rows) >= DIFF_MAX_LINES,
            "changed": any(row["kind"] != "equal" for row in rows),
        }
    lines = _unified_lines(old, new, path, from_version, to_version)
    return {
        "path": path,
        "from": from_version,
        "to": to_version,
        "format": diff_format,
        "diff_available": True,
        "lines": lines[:DIFF_MAX_LINES],
        "truncated": len(lines) > DIFF_MAX_LINES,
        "changed": bool(lines),
    }
