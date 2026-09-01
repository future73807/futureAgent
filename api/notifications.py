"""站内通知中心与 Webhook/IM 出口。

通知始终定向到单个用户；出口推送以最小文本负载进行，任何失败只记录
日志，不影响主业务请求。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from api.dependencies import WorkspaceContext, get_workspace_context, require_workspace_role, write_audit
from db.database import get_session
from db.models import Notification, NotificationTarget, new_id, now_utc

router = APIRouter()
logger = logging.getLogger(__name__)

TARGET_KINDS = {"webhook", "wecom", "feishu", "dingtalk"}


class NotificationTargetRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="webhook", max_length=24)
    url: str = Field(min_length=10, max_length=1000)
    enabled: bool = True


class NotificationTargetPatchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=10, max_length=1000)
    enabled: bool | None = None


def push_notification(
    session: Session,
    workspace_id: str,
    user_id: str | None,
    notification_type: str,
    title: str,
    body: str = "",
    link: str = "",
    ref_id: str = "",
) -> Notification | None:
    """写入一条定向通知；user_id 为空或等于接收人以外时由调用方判断。"""
    if not user_id:
        return None
    notification = Notification(
        workspace_id=workspace_id,
        user_id=user_id,
        type=notification_type,
        title=title[:240],
        body=body[:4000],
        link=link[:40],
        ref_id=ref_id[:80],
    )
    session.add(notification)
    return notification


def _target_payload(kind: str, title: str, body: str) -> dict[str, Any]:
    text = "\n".join(part for part in (title, body) if part)
    if kind == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    if kind in {"wecom", "dingtalk"}:
        return {"msgtype": "text", "text": {"content": text}}
    return {"title": title, "body": body, "source": "futureAgent"}


def dispatch_to_targets(session: Session, workspace_id: str, title: str, body: str = "") -> int:
    """把通知推送到启用的出口；返回成功投递数，失败不抛出。"""
    targets = session.exec(
        select(NotificationTarget)
        .where(NotificationTarget.workspace_id == workspace_id, NotificationTarget.enabled.is_(True))
    ).all()
    delivered = 0
    for target in targets:
        try:
            with httpx.Client(timeout=3.0, trust_env=False) as client:
                response = client.post(target.url, json=_target_payload(target.kind, title, body))
            if response.status_code < 400:
                delivered += 1
            else:
                logger.warning("notification target %s returned %s", target.name, response.status_code)
        except Exception:  # noqa: BLE001 - 出口故障不能拖垮业务请求
            logger.warning("notification target %s unreachable", target.name, exc_info=True)
    return delivered


def _target_data(target: NotificationTarget) -> dict[str, Any]:
    return {
        "id": target.id,
        "workspace_id": target.workspace_id,
        "name": target.name,
        "kind": target.kind,
        "url": target.url,
        "enabled": target.enabled,
        "created_at": target.created_at,
    }


def _notification_data(item: Notification) -> dict[str, Any]:
    return {
        "id": item.id,
        "type": item.type,
        "title": item.title,
        "body": item.body,
        "link": item.link,
        "ref_id": item.ref_id,
        "read": item.read_at is not None,
        "created_at": item.created_at,
    }


def _notification_or_404(session: Session, context: WorkspaceContext, notification_id: str) -> Notification:
    notification = session.get(Notification, notification_id)
    if notification is None or notification.workspace_id != context.workspace.id or notification.user_id != context.user.id:
        raise HTTPException(status_code=404, detail="通知不存在")
    return notification


@router.get("/v1/notifications")
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(30, ge=1, le=100),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    statement = select(Notification).where(
        Notification.workspace_id == context.workspace.id,
        Notification.user_id == context.user.id,
    )
    if unread_only:
        statement = statement.where(Notification.read_at.is_(None))
    items = session.exec(statement.order_by(Notification.created_at.desc()).limit(limit)).all()
    unread = session.exec(
        select(Notification.id).where(
            Notification.workspace_id == context.workspace.id,
            Notification.user_id == context.user.id,
            Notification.read_at.is_(None),
        )
    ).all()
    return {"notifications": [_notification_data(item) for item in items], "unread_count": len(unread)}


@router.post("/v1/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    notification = _notification_or_404(session, context, notification_id)
    if notification.read_at is None:
        notification.read_at = now_utc()
        session.add(notification)
        session.commit()
    return {"notification": _notification_data(notification)}


@router.post("/v1/notifications/read-all")
def mark_all_notifications_read(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    unread = session.exec(
        select(Notification)
        .where(
            Notification.workspace_id == context.workspace.id,
            Notification.user_id == context.user.id,
            Notification.read_at.is_(None),
        )
    ).all()
    for notification in unread:
        notification.read_at = now_utc()
        session.add(notification)
    session.commit()
    return {"marked": len(unread)}


def _require_target_manager(context: WorkspaceContext) -> None:
    require_workspace_role(context, "owner", "admin")


@router.get("/v1/notifications/targets")
def list_notification_targets(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_target_manager(context)
    targets = session.exec(
        select(NotificationTarget)
        .where(NotificationTarget.workspace_id == context.workspace.id)
        .order_by(NotificationTarget.created_at.desc())
    ).all()
    return {"targets": [_target_data(item) for item in targets]}


@router.post("/v1/notifications/targets", status_code=status.HTTP_201_CREATED)
def create_notification_target(
    request: NotificationTargetRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_target_manager(context)
    if request.kind not in TARGET_KINDS:
        raise HTTPException(status_code=422, detail="不支持的通知出口类型")
    target = NotificationTarget(
        workspace_id=context.workspace.id,
        name=request.name,
        kind=request.kind,
        url=request.url,
        enabled=request.enabled,
        created_by=context.user.id,
    )
    session.add(target)
    session.flush()
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="notification_target.created",
        target_type="notification_target",
        target_id=target.id,
        metadata={"kind": target.kind},
    )
    session.commit()
    return {"target": _target_data(target)}


@router.patch("/v1/notifications/targets/{target_id}")
def update_notification_target(
    target_id: str,
    request: NotificationTargetPatchRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_target_manager(context)
    target = session.get(NotificationTarget, target_id)
    if target is None or target.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="通知出口不存在")
    if request.name is not None:
        target.name = request.name
    if request.url is not None:
        target.url = request.url
    if request.enabled is not None:
        target.enabled = request.enabled
    target.updated_at = now_utc()
    session.add(target)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="notification_target.updated",
        target_type="notification_target",
        target_id=target.id,
        metadata={"enabled": target.enabled},
    )
    session.commit()
    return {"target": _target_data(target)}


@router.delete("/v1/notifications/targets/{target_id}", status_code=200)
def delete_notification_target(
    target_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_target_manager(context)
    target = session.get(NotificationTarget, target_id)
    if target is None or target.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="通知出口不存在")
    session.delete(target)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="notification_target.deleted",
        target_type="notification_target",
        target_id=target_id,
    )
    session.commit()
    return {"deleted": target_id}


@router.post("/v1/notifications/targets/{target_id}/test")
def test_notification_target(
    target_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_target_manager(context)
    target = session.get(NotificationTarget, target_id)
    if target is None or target.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="通知出口不存在")
    try:
        with httpx.Client(timeout=4.0, trust_env=False) as client:
            response = client.post(
                target.url,
                json=_target_payload(target.kind, "futureAgent 测试通知", "这是一条来自工作区的测试推送。"),
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"出口不可达：{exc.__class__.__name__}")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"出口返回 {response.status_code}")
    return {"delivered": True, "status_code": response.status_code}
