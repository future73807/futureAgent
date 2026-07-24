"""认证、工作区范围与审计依赖。"""
import json
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from db.database import get_session
from db.models import AuditEvent, Membership, User, Workspace
from db.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class WorkspaceContext:
    user: User
    workspace: Workspace
    membership: Membership


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    user = session.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不可用")
    return user


def get_workspace_context(
    workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> WorkspaceContext:
    statement = select(Membership).where(Membership.user_id == user.id)
    if workspace_id:
        statement = statement.where(Membership.workspace_id == workspace_id)
    membership = session.exec(statement.order_by(Membership.created_at)).first()
    if not membership:
        raise HTTPException(status_code=403, detail="没有该工作区的访问权限")
    workspace = session.get(Workspace, membership.workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return WorkspaceContext(user=user, workspace=workspace, membership=membership)


def require_workspace_role(context: WorkspaceContext, *roles: str) -> None:
    if context.user.is_platform_admin or context.membership.role in roles:
        return
    raise HTTPException(status_code=403, detail="当前工作区角色没有此操作权限")


def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="需要平台管理员权限")
    return user


def write_audit(
    session: Session,
    *,
    actor_id: str | None,
    action: str,
    workspace_id: str | None = None,
    target_type: str = "",
    target_id: str = "",
    metadata: dict | None = None,
) -> None:
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        )
    )
