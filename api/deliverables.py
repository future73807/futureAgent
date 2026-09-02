"""交付物中心：把 MCP 工作区里 AI 产出的文件登记为可下载交付物。

路径来源是 MCP ``local_tools`` 服务（工作区签名隔离），API 通过
``read_file_base64`` 取回字节后写入统一对象存储；登记、列表与下载都
以工作区为硬边界。
"""
from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select
from starlette.background import BackgroundTask

from api.dependencies import WorkspaceContext, get_workspace_context, require_workspace_role, write_audit
from config import settings
from core.mcp_manager import MCPManager
from core.storage import ObjectNotFound, StorageError, get_storage
from db.database import get_session
from db.models import Conversation, Deliverable, Task, new_id

router = APIRouter()

DEFAULT_TOOL_SERVER = "local_tools"
MAX_DELIVERABLE_BYTES = 20 * 1024 * 1024

KIND_BY_EXTENSION = {
    ".xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".webp": ("image", "image/webp"),
    ".pdf": ("pdf", "application/pdf"),
    ".csv": ("file", "text/csv"),
    ".md": ("file", "text/markdown"),
    ".txt": ("file", "text/plain"),
    ".json": ("file", "application/json"),
}


class DeliverableCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    path: str = Field(min_length=1, max_length=400)
    name: str | None = Field(default=None, max_length=255)
    task_id: str | None = Field(default=None, max_length=80)
    conversation_id: str | None = Field(default=None, max_length=80)
    agent_run_id: str | None = Field(default=None, max_length=80)
    server: str = Field(default=DEFAULT_TOOL_SERVER, max_length=60)


async def fetch_workspace_files(workspace_id: str, server: str = DEFAULT_TOOL_SERVER) -> list[dict[str, Any]]:
    """列出 MCP 工作区文件清单；连接失败向上抛出由路由转译。"""
    manager = MCPManager()
    async with manager.connect_many([server], workspace_id=workspace_id) as sessions:
        listing = await manager.call_tool(sessions[0], "list_files", {"path": "."})
    entries = _tool_text_to_json(listing)
    return [item for item in entries if isinstance(item, dict) if item.get("type") == "file"]


async def fetch_workspace_file_bytes(workspace_id: str, path: str, server: str = DEFAULT_TOOL_SERVER) -> bytes:
    """按 base64 取回工作区文件字节；由路由做大小与错误转译。"""
    manager = MCPManager()
    async with manager.connect_many([server], workspace_id=workspace_id) as sessions:
        payload = await manager.call_tool(sessions[0], "read_file_base64", {"path": path})
    text = str(payload).strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=502, detail="工具服务返回的文件内容无法解析") from exc


def _tool_text_to_json(text: Any) -> list[Any]:
    """list_files 返回 JSON 文本（或已是列表），这里统一成列表。"""
    import json

    if isinstance(text, list):
        return text
    try:
        parsed = json.loads(str(text))
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _kind_for(name: str) -> tuple[str, str]:
    return KIND_BY_EXTENSION.get(Path(name).suffix.lower(), ("file", "application/octet-stream"))


def _deliverable_data(item: Deliverable) -> dict[str, Any]:
    return {
        "id": item.id,
        "workspace_id": item.workspace_id,
        "task_id": item.task_id,
        "conversation_id": item.conversation_id,
        "agent_run_id": item.agent_run_id,
        "name": item.name,
        "kind": item.kind,
        "size_bytes": item.size_bytes,
        "registered_by": item.registered_by,
        "created_at": item.created_at,
        "download_url": f"/api/v1/deliverables/{item.id}/download",
    }


def _deliverable_or_404(session: Session, context: WorkspaceContext, deliverable_id: str) -> Deliverable:
    deliverable = session.get(Deliverable, deliverable_id)
    if deliverable is None or deliverable.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="交付物不存在")
    return deliverable


@router.get("/v1/workspace/files")
async def list_workspace_files(
    server: str = Query(DEFAULT_TOOL_SERVER, max_length=60),
    context: WorkspaceContext = Depends(get_workspace_context),
) -> dict[str, Any]:
    """列出 MCP 工作区中已生成的文件，供交付物登记选择。"""
    require_workspace_role(context, "owner", "admin", "member")
    try:
        files = await fetch_workspace_files(context.workspace.id, server)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - 连接细节不外露
        raise HTTPException(status_code=502, detail="工具服务暂不可用，无法列出工作区文件")
    return {
        "files": [
            {
                "path": item.get("path") or item.get("name"),
                "name": item.get("name"),
                "size_bytes": item.get("size"),
            }
            for item in files
        ]
    }


@router.get("/v1/deliverables")
def list_deliverables(
    task_id: str | None = Query(None),
    conversation_id: str | None = Query(None),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    statement = select(Deliverable).where(Deliverable.workspace_id == context.workspace.id)
    if task_id:
        statement = statement.where(Deliverable.task_id == task_id)
    if conversation_id:
        statement = statement.where(Deliverable.conversation_id == conversation_id)
    items = session.exec(statement.order_by(Deliverable.created_at.desc()).limit(100)).all()
    return {"deliverables": [_deliverable_data(item) for item in items]}


@router.post("/v1/deliverables", status_code=status.HTTP_201_CREATED)
async def register_deliverable(
    request: DeliverableCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_workspace_role(context, "owner", "admin", "member")
    if request.task_id:
        task = session.get(Task, request.task_id)
        if task is None or task.workspace_id != context.workspace.id:
            raise HTTPException(status_code=404, detail="关联任务不存在")
    if request.conversation_id:
        conversation = session.get(Conversation, request.conversation_id)
        if conversation is None or conversation.workspace_id != context.workspace.id or conversation.owner_id != context.user.id:
            raise HTTPException(status_code=404, detail="关联对话不存在")
    if not request.task_id and not request.conversation_id:
        raise HTTPException(status_code=422, detail="请将交付物关联到任务或对话")

    raw_name = request.name or Path(request.path).name or "deliverable"
    name = Path(raw_name).name
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=422, detail="交付物名称无效")
    try:
        content = await fetch_workspace_file_bytes(context.workspace.id, request.path, request.server)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="工具服务暂不可用，无法读取该文件")
    if not content:
        raise HTTPException(status_code=422, detail="文件内容为空，无法登记为交付物")
    if len(content) > MAX_DELIVERABLE_BYTES:
        raise HTTPException(status_code=413, detail="文件超过交付物大小限制")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件超过 {settings.max_upload_mb} MB 大小限制")

    kind, content_type = _kind_for(name)
    stored_name = f"deliverables/{context.workspace.id}/{new_id()}{Path(name).suffix.lower()}"
    stored = False
    try:
        import io

        storage = get_storage()
        storage.put_stream(stored_name, io.BytesIO(content), content_type=content_type)
        stored = True
        deliverable = Deliverable(
            workspace_id=context.workspace.id,
            task_id=request.task_id,
            conversation_id=request.conversation_id,
            agent_run_id=request.agent_run_id,
            name=name,
            kind=kind,
            source_path=request.path[:500],
            stored_name=stored_name,
            content_type=content_type,
            size_bytes=len(content),
            registered_by=context.user.id,
        )
        session.add(deliverable)
        session.flush()
        write_audit(
            session,
            actor_id=context.user.id,
            workspace_id=context.workspace.id,
            action="deliverable.registered",
            target_type="deliverable",
            target_id=deliverable.id,
            metadata={"name": name, "source_path": request.path[:200], "size_bytes": len(content)},
        )
        session.commit()
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="交付物存储当前不可用") from exc
    except Exception:
        session.rollback()
        if stored:
            try:
                get_storage().delete(stored_name)
            except StorageError:
                pass
        raise
    return {"deliverable": _deliverable_data(deliverable)}


@router.get("/v1/deliverables/{deliverable_id}/download")
def download_deliverable(
    deliverable_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    deliverable = _deliverable_or_404(session, context, deliverable_id)
    try:
        stream = get_storage().open_stream(deliverable.stored_name)
    except ObjectNotFound as exc:
        raise HTTPException(status_code=404, detail="交付物文件当前不可用") from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="交付物存储当前不可用") from exc
    # HTTP 头只能 latin-1 编码：filename 回退保留 ASCII，UTF-8 名称走 filename*
    safe_filename = re.sub(r"[^ \"'*+,\-./:;<=>?@^\_~0-9A-Za-z]", "_", deliverable.name) or "deliverable"
    disposition = f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{quote(deliverable.name)}"
    return StreamingResponse(
        stream,
        media_type=deliverable.content_type,
        headers={"Content-Disposition": disposition},
        background=BackgroundTask(stream.close),
    )


@router.delete("/v1/deliverables/{deliverable_id}")
def delete_deliverable(
    deliverable_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_workspace_role(context, "owner", "admin", "member")
    deliverable = _deliverable_or_404(session, context, deliverable_id)
    if deliverable.registered_by != context.user.id and context.membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="只能删除自己登记的交付物")
    session.delete(deliverable)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="deliverable.deleted",
        target_type="deliverable",
        target_id=deliverable_id,
        metadata={"name": deliverable.name},
    )
    session.commit()
    try:
        get_storage().delete(deliverable.stored_name)
    except (StorageError, ObjectNotFound):
        pass
    return {"deleted": deliverable_id}
