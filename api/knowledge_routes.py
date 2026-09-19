"""知识库 API 路由（RAG 语料管理）。

工作区成员可以创建、上传、修改与删除知识库文档；写入会触发向量切块重建，
供智能体在回答时检索引用。所有操作以工作区为边界，read-only 成员只能读。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from api.dependencies import WorkspaceContext, get_workspace_context, write_audit
from core.knowledge_retrieval import reindex_knowledge_base
from db.database import get_session
from db.knowledge_models import KnowledgeBase, KnowledgeChunk, now_utc

router = APIRouter(tags=["知识库"])

KNOWLEDGE_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".log",
    ".html",
    ".htm",
    ".xml",
}
KNOWLEDGE_TEXT_CONTENT_TYPES = {
    "application/json",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
}
MAX_KNOWLEDGE_TEXT_BYTES = 400_000
MAX_KNOWLEDGE_CONTENT_CHARS = 100_000


class KnowledgeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class KnowledgeBaseCreateRequest(KnowledgeRequest):
    title: str = Field(min_length=2, max_length=240)
    description: str = Field(default="", max_length=2000)
    content: str = Field(default="", max_length=MAX_KNOWLEDGE_CONTENT_CHARS)


class KnowledgeBaseUpdateRequest(KnowledgeRequest):
    title: str | None = Field(default=None, min_length=2, max_length=240)
    description: str | None = Field(default=None, max_length=2000)
    content: str | None = Field(default=None, max_length=MAX_KNOWLEDGE_CONTENT_CHARS)


def _require_member_write(context: WorkspaceContext) -> None:
    """需要实际的工作区成员身份；平台管理员不是绕过方式。"""
    if context.membership.role == "viewer":
        raise HTTPException(status_code=403, detail="只读成员不能执行此操作")


def _require_workspace_manager(context: WorkspaceContext) -> None:
    """管理员必须是当前工作区的 owner/admin。"""
    if context.membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="需要当前工作区的管理权限")


def _knowledge_base_or_404(session: Session, workspace_id: str, kb_id: str) -> KnowledgeBase:
    kb = session.get(KnowledgeBase, kb_id)
    if not kb or kb.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="知识库文档不存在")
    return kb


def _knowledge_base_data(kb: KnowledgeBase) -> dict[str, Any]:
    return {
        "id": kb.id,
        "title": kb.title,
        "description": kb.description,
        "content": kb.content,
        "file_name": kb.file_name,
        "file_type": kb.file_type,
        "file_size": kb.file_size,
        "created_by": kb.created_by,
        "created_at": kb.created_at,
        "updated_at": kb.updated_at,
    }


def _write_knowledge_audit(
    session: Session,
    *,
    actor_id: str | None,
    workspace_id: str,
    action: str,
    target_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    write_audit(
        session,
        actor_id=actor_id,
        workspace_id=workspace_id,
        action=action,
        target_type="knowledge_base",
        target_id=target_id,
        metadata=metadata,
        visibility="workspace",
        owner_user_id=None,
    )


def _reindex_quietly(session: Session, workspace_id: str, kb: KnowledgeBase) -> None:
    """同步路由用的重建入口：端点在线程池里执行，此处没有运行中的事件循环。

    embedding 未启用或调用失败都不阻塞文档写入——写入成功比索引新鲜更重要，
    下一次写文档时会重建。
    """
    try:
        asyncio.run(reindex_knowledge_base(session, workspace_id, kb))
    except Exception:  # noqa: BLE001 - 索引失败只记录，不影响文档本身
        logging.getLogger(__name__).debug("knowledge index failed", exc_info=True)


async def _reindex_quietly_async(session: Session, workspace_id: str, kb: KnowledgeBase) -> None:
    """异步路由用的重建入口：上传端点本身就在事件循环里，不能再用 asyncio.run。"""
    try:
        await reindex_knowledge_base(session, workspace_id, kb)
    except Exception:  # noqa: BLE001 - 同上
        logging.getLogger(__name__).debug("knowledge index failed", exc_info=True)


@router.get("")
def list_knowledge_bases(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    knowledge_bases = session.exec(
        select(KnowledgeBase)
        .where(KnowledgeBase.workspace_id == context.workspace.id)
        .order_by(KnowledgeBase.created_at.desc())
    ).all()
    items = [_knowledge_base_data(kb) for kb in knowledge_bases]
    return {"knowledge_bases": items, "items": items}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_knowledge_base(
    payload: KnowledgeBaseCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_member_write(context)
    kb = KnowledgeBase(
        workspace_id=context.workspace.id,
        title=payload.title,
        description=payload.description,
        content=payload.content,
        created_by=context.user.id,
    )
    session.add(kb)
    session.flush()
    _write_knowledge_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="knowledge_base.created",
        target_id=kb.id,
    )
    session.commit()
    _reindex_quietly(session, context.workspace.id, kb)
    return {"knowledge_base": _knowledge_base_data(kb)}


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_knowledge_base_file(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    description: str = Form(default=""),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_member_write(context)
    file_name = Path(file.filename or "knowledge.txt").name
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    extension = Path(file_name).suffix.lower()
    if not (
        content_type.startswith("text/")
        or content_type in KNOWLEDGE_TEXT_CONTENT_TYPES
        or extension in KNOWLEDGE_TEXT_EXTENSIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="知识库上传仅支持 UTF-8 文本、Markdown、CSV、JSON、YAML、HTML 和 XML 文件",
        )
    if len(file_name) > 255:
        raise HTTPException(status_code=422, detail="知识库文件名不能超过 255 个字符")
    resolved_title = (title or Path(file_name).stem or file_name).strip()
    if len(resolved_title) < 2 or len(resolved_title) > 240:
        raise HTTPException(status_code=422, detail="知识库标题长度必须为 2 到 240 个字符")
    if len(description) > 2000:
        raise HTTPException(status_code=422, detail="知识库说明不能超过 2000 个字符")

    content = await file.read(MAX_KNOWLEDGE_TEXT_BYTES + 1)
    if len(content) > MAX_KNOWLEDGE_TEXT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"知识库文本文件不能超过 {MAX_KNOWLEDGE_TEXT_BYTES} 字节",
        )
    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="知识库文件必须使用 UTF-8 编码") from exc
    if len(text_content) > MAX_KNOWLEDGE_CONTENT_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"知识库文本内容不能超过 {MAX_KNOWLEDGE_CONTENT_CHARS} 个字符",
        )
    kb = KnowledgeBase(
        workspace_id=context.workspace.id,
        title=resolved_title,
        description=description,
        content=text_content,
        file_name=file_name,
        file_type=content_type or "text/plain",
        file_size=len(content),
        created_by=context.user.id,
    )
    session.add(kb)
    session.flush()
    _write_knowledge_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="knowledge_base.uploaded",
        target_id=kb.id,
        metadata={
            "file_name": file_name,
            "file_type": content_type or "text/plain",
            "file_size": len(content),
        },
    )
    session.commit()
    await _reindex_quietly_async(session, context.workspace.id, kb)
    return {"knowledge_base": _knowledge_base_data(kb)}


@router.patch("/{kb_id}")
def update_knowledge_base(
    kb_id: str,
    payload: KnowledgeBaseUpdateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    kb = _knowledge_base_or_404(session, context.workspace.id, kb_id)
    _require_member_write(context)
    if payload.title is not None:
        kb.title = payload.title
    if payload.description is not None:
        kb.description = payload.description
    if payload.content is not None:
        kb.content = payload.content
    kb.updated_at = now_utc()
    session.add(kb)
    _write_knowledge_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="knowledge_base.updated",
        target_id=kb.id,
    )
    session.commit()
    _reindex_quietly(session, context.workspace.id, kb)
    return {"knowledge_base": _knowledge_base_data(kb)}


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge_base(
    kb_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> None:
    kb = _knowledge_base_or_404(session, context.workspace.id, kb_id)
    _require_workspace_manager(context)
    # 级联删除向量切块，避免残留块继续被检索召回
    for chunk in session.exec(
        select(KnowledgeChunk).where(KnowledgeChunk.kb_id == kb.id)
    ).all():
        session.delete(chunk)
    session.delete(kb)
    _write_knowledge_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="knowledge_base.deleted",
        target_id=kb.id,
    )
    session.commit()
