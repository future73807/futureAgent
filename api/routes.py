"""Authenticated, workspace-scoped REST API for futureAgent.

The earlier prototype accepted a ``user_role`` sent by the browser.  This
module intentionally never does that: identity comes from a signed bearer
token and the effective permissions are derived from the user's workspace
membership on the server.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any, AsyncGenerator, Literal

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sse_starlette.sse import EventSourceResponse
from sqlmodel import Session, select

from api.dependencies import (
    WorkspaceContext,
    get_current_user,
    get_workspace_context,
    require_platform_admin,
    require_workspace_role,
    write_audit,
)
from auth.auth_manager import AuthManager
from config import settings
from core.agent_engine import AgentEngine
from core.mcp_manager import MCPManager
from core.model_hub import ModelHub
from core.skill_manager import Skill, SkillManager
from db.database import get_session
from db.models import (
    Attachment,
    AuditEvent,
    ChatMessage,
    Conversation,
    Membership,
    Project,
    RefreshSession,
    Task,
    User,
    Workspace,
    WorkPlan,
    WorkPlanStep,
    new_id,
    now_utc,
)
from db.security import create_token, decode_token, hash_password, verify_password

router = APIRouter()

TASK_STATUSES = {"backlog", "todo", "in_progress", "review", "done"}
TASK_PRIORITIES = {"low", "medium", "high", "urgent"}
PLAN_STATUSES = {"draft", "approved", "in_progress", "completed"}
STEP_STATUSES = {"pending", "running", "blocked", "done"}
MEMBERSHIP_ROLES = {"owner", "admin", "member", "viewer"}
ALLOWED_UPLOAD_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".pdf",
    ".docx",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}


class RequestModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class RegisterRequest(RequestModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=72)
    display_name: str = Field(min_length=2, max_length=120)
    workspace_name: str | None = Field(default=None, max_length=120)


class LoginRequest(RequestModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class WorkspaceCreateRequest(RequestModel):
    name: str = Field(min_length=2, max_length=120)


class WorkspaceUpdateRequest(RequestModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    plan: str | None = Field(default=None, min_length=2, max_length=32)


class MembershipCreateRequest(RequestModel):
    email: EmailStr
    role: str = Field(default="member", max_length=32)


class MembershipUpdateRequest(RequestModel):
    role: str = Field(min_length=1, max_length=32)


class OwnershipTransferRequest(RequestModel):
    member_id: str = Field(min_length=1, max_length=64)


class ProjectCreateRequest(RequestModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=4000)
    color: str = Field(default="#5B5BD6", pattern=r"^#[0-9A-Fa-f]{6}$")


class ProjectUpdateRequest(RequestModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    status: Literal["active", "archived"] | None = None


class TaskCreateRequest(RequestModel):
    project_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=2, max_length=240)
    description: str = Field(default="", max_length=8000)
    status: str = Field(default="todo", max_length=24)
    priority: str = Field(default="medium", max_length=16)
    assignee_id: str | None = Field(default=None, max_length=64)
    due_date: date | None = None
    labels: list[str] = Field(default_factory=list, max_length=20)


class TaskUpdateRequest(RequestModel):
    title: str | None = Field(default=None, min_length=2, max_length=240)
    description: str | None = Field(default=None, max_length=8000)
    status: str | None = Field(default=None, max_length=24)
    priority: str | None = Field(default=None, max_length=16)
    assignee_id: str | None = Field(default=None, max_length=64)
    due_date: date | None = None
    labels: list[str] | None = Field(default=None, max_length=20)
    sort_order: int | None = Field(default=None, ge=0, le=100_000)


class WorkPlanStepInput(RequestModel):
    id: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=2, max_length=240)
    instructions: str = Field(default="", max_length=8000)
    assignee_id: str | None = Field(default=None, max_length=64)


class WorkPlanWriteRequest(RequestModel):
    objective: str = Field(default="", max_length=8000)
    steps: list[WorkPlanStepInput] = Field(default_factory=list, max_length=50)


class WorkPlanStepUpdateRequest(RequestModel):
    status: str | None = Field(default=None, max_length=24)
    output_summary: str | None = Field(default=None, max_length=8000)
    assignee_id: str | None = Field(default=None, max_length=64)


class ConversationCreateRequest(RequestModel):
    title: str = Field(default="New conversation", min_length=1, max_length=240)
    project_id: str | None = Field(default=None, max_length=64)
    model_id: str = Field(default="", max_length=120)
    skill_name: str = Field(default="default", max_length=120)


class ConversationUpdateRequest(RequestModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    archived: bool | None = None


class ChatCompletionRequest(RequestModel):
    query: str = Field(min_length=1, max_length=100_000)
    model_id: str = Field(default="", max_length=120)
    conversation_id: str | None = Field(default=None, max_length=64)


class AgentRequest(ChatCompletionRequest):
    skill_name: str = Field(default="default", max_length=120)
    mcp_servers: list[str] = Field(default_factory=list, max_length=20)


class PolicyRequest(RequestModel):
    role: str = Field(min_length=1, max_length=64)
    resource: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1, max_length=64)


class AdminUserUpdateRequest(RequestModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    is_active: bool | None = None
    is_platform_admin: bool | None = None


def get_agent_engine() -> AgentEngine:
    return AgentEngine(
        model_hub=ModelHub(),
        mcp_manager=MCPManager(),
        skill_manager=SkillManager(),
        auth_manager=AuthManager(),
    )


def _sse_error(exc: Exception) -> dict[str, str]:
    if isinstance(exc, HTTPException):
        detail = str(exc.detail)
    else:
        # Provider exceptions can contain implementation details.  The request
        # itself is recorded in the conversation and the user gets a stable,
        # actionable error instead of an accidental secret disclosure.
        detail = "The AI service could not complete this request. Please retry later."
    return {"event": "error", "data": json.dumps({"detail": detail}, ensure_ascii=False)}


def _provider_name(model_id: str) -> str:
    if model_id.startswith(("gpt-", "openai/")):
        return "OpenAI"
    if model_id.startswith("claude"):
        return "Anthropic"
    if model_id.startswith("ollama/"):
        return "Ollama"
    if model_id.startswith("gemini/"):
        return "Google"
    return model_id.split("/", 1)[0]


def _safe_json_list(value: str) -> list[Any]:
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _effective_role(context: WorkspaceContext) -> str:
    """Map persisted product roles to Casbin roles on the server only."""
    if context.user.is_platform_admin:
        return "admin"
    # A collaboration member needs the same model/tool execution capability as
    # an owner.  Viewers are intentionally limited by the `user` Casbin role.
    return "user" if context.membership.role == "viewer" else "developer"


def _user_data(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "is_platform_admin": user.is_platform_admin,
        "is_active": user.is_active,
        "created_at": user.created_at,
    }


def _workspace_data(workspace: Workspace, role: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug,
        "owner_id": workspace.owner_id,
        "plan": workspace.plan,
        "created_at": workspace.created_at,
    }
    if role is not None:
        data["role"] = role
    return data


def _project_data(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "workspace_id": project.workspace_id,
        "name": project.name,
        "description": project.description,
        "color": project.color,
        "status": project.status,
        "created_by": project.created_by,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _task_data(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "assignee_id": task.assignee_id,
        "reporter_id": task.reporter_id,
        "due_date": task.due_date,
        "labels": _safe_json_list(task.labels_json),
        "sort_order": task.sort_order,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _conversation_data(conversation: Conversation) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "workspace_id": conversation.workspace_id,
        "owner_id": conversation.owner_id,
        "project_id": conversation.project_id,
        "title": conversation.title,
        "model_id": conversation.model_id,
        "skill_name": conversation.skill_name,
        "archived": conversation.archived,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def _message_data(message: ChatMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": message.content,
        "tool_trace": _safe_json_list(message.tool_trace_json),
        "created_at": message.created_at,
    }


def _plan_data(session: Session, plan: WorkPlan | None) -> dict[str, Any] | None:
    if not plan:
        return None
    steps = session.exec(
        select(WorkPlanStep)
        .where(WorkPlanStep.plan_id == plan.id)
        .order_by(WorkPlanStep.position)
    ).all()
    return {
        "id": plan.id,
        "task_id": plan.task_id,
        "objective": plan.objective,
        "status": plan.status,
        "created_by": plan.created_by,
        "approved_by": plan.approved_by,
        "approved_at": plan.approved_at,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "steps": [
            {
                "id": step.id,
                "position": step.position,
                "title": step.title,
                "instructions": step.instructions,
                "status": step.status,
                "assignee_id": step.assignee_id,
                "output_summary": step.output_summary,
                "updated_at": step.updated_at,
            }
            for step in steps
        ],
    }


def _audit_data(event: AuditEvent) -> dict[str, Any]:
    try:
        metadata = json.loads(event.metadata_json)
    except json.JSONDecodeError:
        metadata = {}
    return {
        "id": event.id,
        "workspace_id": event.workspace_id,
        "actor_id": event.actor_id,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "metadata": metadata,
        "created_at": event.created_at,
    }


def _unique_workspace_slug(session: Session, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    if not base:
        base = "workspace"
    candidate = base
    suffix = 2
    while session.exec(select(Workspace.id).where(Workspace.slug == candidate)).first():
        candidate = f"{base[:54]}-{suffix}"
        suffix += 1
    return candidate


def _membership_for_workspace(session: Session, user: User, workspace_id: str) -> Membership:
    membership = session.exec(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user.id,
        )
    ).first()
    if not membership and not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="You do not have access to this workspace")
    if membership:
        return membership
    # Platform administrators may operate a workspace without a membership.
    return Membership(workspace_id=workspace_id, user_id=user.id, role="admin")


def _workspace_or_404(session: Session, workspace_id: str) -> Workspace:
    workspace = session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _require_workspace_manager(session: Session, user: User, workspace_id: str) -> Membership:
    membership = _membership_for_workspace(session, user, workspace_id)
    if not user.is_platform_admin and membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Workspace administrator permission required")
    return membership


def _member_or_422(session: Session, workspace_id: str, user_id: str | None) -> None:
    if not user_id:
        return
    member = session.exec(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user_id,
        )
    ).first()
    if not member:
        raise HTTPException(status_code=422, detail="Assignee must belong to the workspace")


def _project_or_404(session: Session, workspace_id: str, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project or project.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _task_or_404(session: Session, workspace_id: str, task_id: str) -> Task:
    task = session.get(Task, task_id)
    if not task or task.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _conversation_or_404(
    session: Session,
    context: WorkspaceContext,
    conversation_id: str,
) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if not conversation or conversation.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if (
        conversation.owner_id != context.user.id
        and not context.user.is_platform_admin
        and context.membership.role not in {"owner", "admin"}
    ):
        raise HTTPException(status_code=403, detail="You cannot access this conversation")
    return conversation


def _ensure_model_ready(model_id: str) -> None:
    reason = ModelHub.readiness_error(model_id)
    if reason:
        raise HTTPException(status_code=503, detail=reason)


def _authorize_agent_config(context: WorkspaceContext, model_id: str, skill_name: str, mcp_servers: list[str]) -> str:
    role = _effective_role(context)
    engine = get_agent_engine()
    engine.validate_permissions(
        role,
        {"model_id": model_id, "skill_name": skill_name, "mcp_servers": mcp_servers},
    )
    return role


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="futureagent_refresh",
        value=token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.environment.lower() == "production",
        samesite="lax",
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key="futureagent_refresh",
        path="/api/v1/auth",
        httponly=True,
        secure=settings.environment.lower() == "production",
        samesite="lax",
    )


def _issue_auth_payload(session: Session, user: User, response: Response) -> dict[str, Any]:
    refresh_session = RefreshSession(
        user_id=user.id,
        expires_at=now_utc() + timedelta(days=settings.refresh_token_expire_days),
    )
    session.add(refresh_session)
    session.flush()
    access_token = create_token(
        user_id=user.id,
        token_type="access",
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    refresh_token = create_token(
        user_id=user.id,
        token_type="refresh",
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
        session_id=refresh_session.id,
    )
    _set_refresh_cookie(response, refresh_token)
    memberships = session.exec(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at)
    ).all()
    workspaces = [
        _workspace_data(workspace, membership.role)
        for membership in memberships
        if (workspace := session.get(Workspace, membership.workspace_id))
    ]
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user": _user_data(user),
        "workspaces": workspaces,
    }


def _create_conversation_for_chat(
    session: Session,
    context: WorkspaceContext,
    conversation_id: str | None,
    model_id: str,
    skill_name: str = "default",
    title_hint: str = "",
) -> Conversation:
    if conversation_id:
        conversation = _conversation_or_404(session, context, conversation_id)
        if conversation.archived:
            raise HTTPException(status_code=409, detail="Conversation is archived")
        return conversation
    conversation = Conversation(
        workspace_id=context.workspace.id,
        owner_id=context.user.id,
        title=(title_hint[:60] or "New conversation"),
        model_id=model_id,
        skill_name=skill_name,
    )
    session.add(conversation)
    session.flush()
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="conversation.created",
        target_type="conversation",
        target_id=conversation.id,
    )
    return conversation


@router.get("/v1/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "futureAgent",
        "environment": settings.environment,
        "authentication": "jwt",
    }


# ---------------------------------------------------------------------------
# Authentication and account lifecycle
# ---------------------------------------------------------------------------


@router.post("/v1/auth/register", status_code=status.HTTP_201_CREATED)
def register(
    request: RegisterRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    email = str(request.email).lower()
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(
        email=email,
        display_name=request.display_name,
        password_hash=hash_password(request.password),
    )
    session.add(user)
    session.flush()
    workspace_name = request.workspace_name or f"{request.display_name}'s workspace"
    workspace = Workspace(
        name=workspace_name,
        slug=_unique_workspace_slug(session, workspace_name),
        owner_id=user.id,
    )
    session.add(workspace)
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
    write_audit(
        session,
        actor_id=user.id,
        workspace_id=workspace.id,
        action="workspace.created",
        target_type="workspace",
        target_id=workspace.id,
        metadata={"source": "self_service_registration"},
    )
    payload = _issue_auth_payload(session, user, response)
    session.commit()
    payload["workspaces"] = [_workspace_data(workspace, "owner")]
    return payload


@router.post("/v1/auth/login")
def login(
    request: LoginRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user = session.exec(
        select(User).where(User.email == str(request.email).lower())
    ).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been disabled")
    write_audit(session, actor_id=user.id, action="auth.login", target_type="user", target_id=user.id)
    payload = _issue_auth_payload(session, user, response)
    session.commit()
    return payload


@router.post("/v1/auth/refresh")
def refresh_access_token(
    response: Response,
    refresh_token: Annotated[str | None, Cookie(alias="futureagent_refresh")] = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh session")
    payload = decode_token(refresh_token, expected_type="refresh")
    refresh_session = session.get(RefreshSession, payload["jti"])
    if (
        not refresh_session
        or refresh_session.user_id != payload["sub"]
        or refresh_session.revoked
        or refresh_session.expires_at <= now_utc()
    ):
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Refresh session has expired")
    user = session.get(User, refresh_session.user_id)
    if not user or not user.is_active:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Account is unavailable")
    refresh_session.revoked = True
    write_audit(session, actor_id=user.id, action="auth.token_refreshed", target_type="user", target_id=user.id)
    result = _issue_auth_payload(session, user, response)
    session.commit()
    return result


@router.post("/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    refresh_token: Annotated[str | None, Cookie(alias="futureagent_refresh")] = None,
    session: Session = Depends(get_session),
) -> None:
    if refresh_token:
        try:
            payload = decode_token(refresh_token, expected_type="refresh")
            refresh_session = session.get(RefreshSession, payload["jti"])
            if refresh_session:
                refresh_session.revoked = True
                write_audit(
                    session,
                    actor_id=refresh_session.user_id,
                    action="auth.logout",
                    target_type="user",
                    target_id=refresh_session.user_id,
                )
                session.commit()
        except HTTPException:
            pass
    _clear_refresh_cookie(response)
    return None


@router.get("/v1/auth/me")
def me(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    memberships = session.exec(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at)
    ).all()
    workspaces: list[dict[str, Any]] = []
    for membership in memberships:
        workspace = session.get(Workspace, membership.workspace_id)
        if workspace:
            workspaces.append(_workspace_data(workspace, membership.role))
    return {"user": _user_data(user), "workspaces": workspaces}


# ---------------------------------------------------------------------------
# Workspace and collaboration administration
# ---------------------------------------------------------------------------


@router.get("/v1/workspaces")
def list_workspaces(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    memberships = session.exec(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at)
    ).all()
    items = [
        _workspace_data(workspace, membership.role)
        for membership in memberships
        if (workspace := session.get(Workspace, membership.workspace_id))
    ]
    return {"workspaces": items}


@router.post("/v1/workspaces", status_code=status.HTTP_201_CREATED)
def create_workspace(
    request: WorkspaceCreateRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    workspace = Workspace(
        name=request.name,
        slug=_unique_workspace_slug(session, request.name),
        owner_id=user.id,
    )
    session.add(workspace)
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
    write_audit(
        session,
        actor_id=user.id,
        workspace_id=workspace.id,
        action="workspace.created",
        target_type="workspace",
        target_id=workspace.id,
    )
    session.commit()
    return {"workspace": _workspace_data(workspace, "owner")}


@router.patch("/v1/workspaces/{workspace_id}")
def update_workspace(
    workspace_id: str,
    request: WorkspaceUpdateRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_workspace_manager(session, user, workspace_id)
    workspace = _workspace_or_404(session, workspace_id)
    if request.name is not None:
        workspace.name = request.name
    if request.plan is not None:
        workspace.plan = request.plan
    workspace.updated_at = now_utc()
    write_audit(
        session,
        actor_id=user.id,
        workspace_id=workspace_id,
        action="workspace.updated",
        target_type="workspace",
        target_id=workspace_id,
    )
    session.add(workspace)
    session.commit()
    return {"workspace": _workspace_data(workspace)}


@router.get("/v1/workspaces/{workspace_id}/members")
def list_members(
    workspace_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _membership_for_workspace(session, user, workspace_id)
    _workspace_or_404(session, workspace_id)
    memberships = session.exec(
        select(Membership)
        .where(Membership.workspace_id == workspace_id)
        .order_by(Membership.created_at)
    ).all()
    members = []
    for membership in memberships:
        member_user = session.get(User, membership.user_id)
        if member_user:
            members.append({"id": membership.id, "role": membership.role, "user": _user_data(member_user)})
    return {"members": members}


@router.post("/v1/workspaces/{workspace_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(
    workspace_id: str,
    request: MembershipCreateRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_workspace_manager(session, user, workspace_id)
    if request.role not in MEMBERSHIP_ROLES - {"owner"}:
        raise HTTPException(status_code=422, detail="Role must be admin, member, or viewer")
    member_user = session.exec(
        select(User).where(User.email == str(request.email).lower())
    ).first()
    if not member_user:
        raise HTTPException(status_code=404, detail="The invited user must register first")
    if session.exec(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == member_user.id,
        )
    ).first():
        raise HTTPException(status_code=409, detail="This user is already a member")
    membership = Membership(workspace_id=workspace_id, user_id=member_user.id, role=request.role)
    session.add(membership)
    write_audit(
        session,
        actor_id=user.id,
        workspace_id=workspace_id,
        action="member.added",
        target_type="membership",
        target_id=membership.id,
        metadata={"user_id": member_user.id, "role": request.role},
    )
    session.commit()
    return {"member": {"id": membership.id, "role": membership.role, "user": _user_data(member_user)}}


@router.patch("/v1/workspaces/{workspace_id}/members/{member_id}")
def update_member(
    workspace_id: str,
    member_id: str,
    request: MembershipUpdateRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_workspace_manager(session, user, workspace_id)
    if request.role not in MEMBERSHIP_ROLES - {"owner"}:
        raise HTTPException(status_code=422, detail="Role must be admin, member, or viewer")
    membership = session.get(Membership, member_id)
    if not membership or membership.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Member not found")
    if membership.role == "owner":
        raise HTTPException(status_code=409, detail="Transfer ownership before changing the owner role")
    membership.role = request.role
    write_audit(
        session,
        actor_id=user.id,
        workspace_id=workspace_id,
        action="member.role_updated",
        target_type="membership",
        target_id=member_id,
        metadata={"role": request.role},
    )
    session.add(membership)
    session.commit()
    member_user = session.get(User, membership.user_id)
    return {"member": {"id": membership.id, "role": membership.role, "user": _user_data(member_user)}}


@router.delete("/v1/workspaces/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    workspace_id: str,
    member_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> None:
    _require_workspace_manager(session, user, workspace_id)
    membership = session.get(Membership, member_id)
    if not membership or membership.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Member not found")
    if membership.role == "owner":
        raise HTTPException(status_code=409, detail="Transfer ownership before removing the owner")
    session.delete(membership)
    write_audit(
        session,
        actor_id=user.id,
        workspace_id=workspace_id,
        action="member.removed",
        target_type="membership",
        target_id=member_id,
        metadata={"user_id": membership.user_id},
    )
    session.commit()
    return None


@router.post("/v1/workspaces/{workspace_id}/transfer-owner")
def transfer_workspace_ownership(
    workspace_id: str,
    request: OwnershipTransferRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    workspace = _workspace_or_404(session, workspace_id)
    current_membership = _membership_for_workspace(session, user, workspace_id)
    if not user.is_platform_admin and current_membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only the workspace owner can transfer ownership")
    target_membership = session.get(Membership, request.member_id)
    if not target_membership or target_membership.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Target member not found")
    old_owner = session.exec(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == workspace.owner_id,
        )
    ).first()
    if old_owner:
        old_owner.role = "admin"
        session.add(old_owner)
    target_membership.role = "owner"
    workspace.owner_id = target_membership.user_id
    workspace.updated_at = now_utc()
    session.add(target_membership)
    session.add(workspace)
    write_audit(
        session,
        actor_id=user.id,
        workspace_id=workspace_id,
        action="workspace.owner_transferred",
        target_type="workspace",
        target_id=workspace_id,
        metadata={"new_owner_id": target_membership.user_id},
    )
    session.commit()
    return {"workspace": _workspace_data(workspace, "owner")}


# ---------------------------------------------------------------------------
# Project board and Work mode plans
# ---------------------------------------------------------------------------


@router.get("/v1/projects")
def list_projects(
    include_archived: bool = Query(False),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    statement = select(Project).where(Project.workspace_id == context.workspace.id)
    if not include_archived:
        statement = statement.where(Project.status == "active")
    projects = session.exec(statement.order_by(Project.updated_at.desc())).all()
    return {"projects": [_project_data(project) for project in projects]}


@router.post("/v1/projects", status_code=status.HTTP_201_CREATED)
def create_project(
    request: ProjectCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_workspace_role(context, "owner", "admin", "member")
    project = Project(
        workspace_id=context.workspace.id,
        name=request.name,
        description=request.description,
        color=request.color,
        created_by=context.user.id,
    )
    session.add(project)
    session.flush()
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="project.created",
        target_type="project",
        target_id=project.id,
    )
    session.commit()
    return {"project": _project_data(project)}


@router.patch("/v1/projects/{project_id}")
def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_workspace_role(context, "owner", "admin", "member")
    project = _project_or_404(session, context.workspace.id, project_id)
    for field in ("name", "description", "color", "status"):
        value = getattr(request, field)
        if value is not None:
            setattr(project, field, value)
    project.updated_at = now_utc()
    session.add(project)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="project.updated",
        target_type="project",
        target_id=project.id,
    )
    session.commit()
    return {"project": _project_data(project)}


@router.get("/v1/tasks")
def list_tasks(
    project_id: str | None = Query(None),
    task_status: str | None = Query(None, alias="status"),
    assignee_id: str | None = Query(None),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    statement = select(Task).where(Task.workspace_id == context.workspace.id)
    if project_id:
        _project_or_404(session, context.workspace.id, project_id)
        statement = statement.where(Task.project_id == project_id)
    if task_status:
        if task_status not in TASK_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown task status")
        statement = statement.where(Task.status == task_status)
    if assignee_id:
        statement = statement.where(Task.assignee_id == assignee_id)
    tasks = session.exec(statement.order_by(Task.sort_order, Task.updated_at.desc())).all()
    return {"tasks": [_task_data(task) for task in tasks]}


@router.post("/v1/tasks", status_code=status.HTTP_201_CREATED)
def create_task(
    request: TaskCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_workspace_role(context, "owner", "admin", "member")
    if request.status not in TASK_STATUSES or request.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail="Invalid task status or priority")
    _project_or_404(session, context.workspace.id, request.project_id)
    _member_or_422(session, context.workspace.id, request.assignee_id)
    task = Task(
        workspace_id=context.workspace.id,
        project_id=request.project_id,
        title=request.title,
        description=request.description,
        status=request.status,
        priority=request.priority,
        assignee_id=request.assignee_id,
        reporter_id=context.user.id,
        due_date=request.due_date,
        labels_json=json.dumps(request.labels, ensure_ascii=False),
    )
    session.add(task)
    session.flush()
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="task.created",
        target_type="task",
        target_id=task.id,
        metadata={"project_id": task.project_id, "status": task.status},
    )
    session.commit()
    return {"task": _task_data(task)}


@router.patch("/v1/tasks/{task_id}")
def update_task(
    task_id: str,
    request: TaskUpdateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_workspace_role(context, "owner", "admin", "member")
    task = _task_or_404(session, context.workspace.id, task_id)
    if request.status is not None and request.status not in TASK_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid task status")
    if request.priority is not None and request.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail="Invalid task priority")
    if "assignee_id" in request.model_fields_set:
        _member_or_422(session, context.workspace.id, request.assignee_id)
        task.assignee_id = request.assignee_id
    for field in ("title", "description", "status", "priority", "due_date", "sort_order"):
        if field in request.model_fields_set:
            setattr(task, field, getattr(request, field))
    if request.labels is not None:
        task.labels_json = json.dumps(request.labels, ensure_ascii=False)
    task.updated_at = now_utc()
    session.add(task)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="task.updated",
        target_type="task",
        target_id=task.id,
        metadata={"status": task.status, "assignee_id": task.assignee_id},
    )
    session.commit()
    return {"task": _task_data(task)}


@router.get("/v1/tasks/{task_id}/plan")
def get_work_plan(
    task_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _task_or_404(session, context.workspace.id, task_id)
    plan = session.exec(select(WorkPlan).where(WorkPlan.task_id == task_id)).first()
    return {"plan": _plan_data(session, plan)}


@router.get("/v1/tasks/{task_id}/activity")
def list_task_activity(
    task_id: str,
    limit: int = Query(100, ge=1, le=300),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Return the auditable timeline for one task and its work artifacts.

    The workspace-level audit log remains manager-only.  This narrower view is
    safe for every workspace member who can already view the task: it exposes
    only events that target the task, its plan steps, or its attached files.
    """
    _task_or_404(session, context.workspace.id, task_id)
    target_ids = {task_id}
    plan = session.exec(select(WorkPlan).where(WorkPlan.task_id == task_id)).first()
    if plan:
        target_ids.add(plan.id)
        target_ids.update(
            step.id
            for step in session.exec(select(WorkPlanStep).where(WorkPlanStep.plan_id == plan.id)).all()
        )
    target_ids.update(
        attachment.id
        for attachment in session.exec(
            select(Attachment).where(
                Attachment.workspace_id == context.workspace.id,
                Attachment.task_id == task_id,
            )
        ).all()
    )
    events = session.exec(
        select(AuditEvent)
        .where(
            AuditEvent.workspace_id == context.workspace.id,
            AuditEvent.target_id.in_(target_ids),
        )
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).all()
    return {"events": [_audit_data(event) for event in events]}


@router.put("/v1/tasks/{task_id}/plan")
def upsert_work_plan(
    task_id: str,
    request: WorkPlanWriteRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_workspace_role(context, "owner", "admin", "member")
    task = _task_or_404(session, context.workspace.id, task_id)
    plan = session.exec(select(WorkPlan).where(WorkPlan.task_id == task.id)).first()
    if plan and plan.status != "draft" and context.membership.role not in {"owner", "admin"} and not context.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="An approved plan can only be revised by a workspace manager")
    if not plan:
        plan = WorkPlan(
            workspace_id=context.workspace.id,
            task_id=task.id,
            objective=request.objective,
            created_by=context.user.id,
        )
        session.add(plan)
        session.flush()
    else:
        plan.objective = request.objective
        plan.status = "draft"
        plan.approved_by = None
        plan.approved_at = None
        plan.updated_at = now_utc()
        session.add(plan)

    existing = {
        step.id: step
        for step in session.exec(select(WorkPlanStep).where(WorkPlanStep.plan_id == plan.id)).all()
    }
    supplied_ids: set[str] = set()
    for position, item in enumerate(request.steps):
        _member_or_422(session, context.workspace.id, item.assignee_id)
        if item.id:
            step = existing.get(item.id)
            if not step:
                raise HTTPException(status_code=422, detail="A plan step does not belong to this plan")
            supplied_ids.add(step.id)
            step.title = item.title
            step.instructions = item.instructions
            step.assignee_id = item.assignee_id
            step.position = position
            step.updated_at = now_utc()
        else:
            step = WorkPlanStep(
                plan_id=plan.id,
                position=position,
                title=item.title,
                instructions=item.instructions,
                assignee_id=item.assignee_id,
            )
        session.add(step)
    for step in existing.values():
        if step.id not in supplied_ids:
            session.delete(step)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="work_plan.saved",
        target_type="work_plan",
        target_id=plan.id,
        metadata={"task_id": task.id, "step_count": len(request.steps)},
    )
    session.commit()
    return {"plan": _plan_data(session, plan)}


@router.post("/v1/tasks/{task_id}/plan/approve")
def approve_work_plan(
    task_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_workspace_role(context, "owner", "admin")
    _task_or_404(session, context.workspace.id, task_id)
    plan = session.exec(select(WorkPlan).where(WorkPlan.task_id == task_id)).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Work plan not found")
    if not session.exec(select(WorkPlanStep.id).where(WorkPlanStep.plan_id == plan.id)).first():
        raise HTTPException(status_code=422, detail="A work plan needs at least one step before approval")
    plan.status = "approved"
    plan.approved_by = context.user.id
    plan.approved_at = now_utc()
    plan.updated_at = now_utc()
    session.add(plan)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="work_plan.approved",
        target_type="work_plan",
        target_id=plan.id,
    )
    session.commit()
    return {"plan": _plan_data(session, plan)}


@router.patch("/v1/tasks/{task_id}/plan/steps/{step_id}")
def update_work_plan_step(
    task_id: str,
    step_id: str,
    request: WorkPlanStepUpdateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    task = _task_or_404(session, context.workspace.id, task_id)
    plan = session.exec(select(WorkPlan).where(WorkPlan.task_id == task.id)).first()
    step = session.get(WorkPlanStep, step_id)
    if not plan or not step or step.plan_id != plan.id:
        raise HTTPException(status_code=404, detail="Work plan step not found")
    can_update = (
        context.user.is_platform_admin
        or context.membership.role in {"owner", "admin"}
        or step.assignee_id == context.user.id
        or task.assignee_id == context.user.id
        or task.reporter_id == context.user.id
    )
    if not can_update:
        raise HTTPException(status_code=403, detail="You cannot update this plan step")
    if request.status is not None:
        if request.status not in STEP_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid work plan step status")
        step.status = request.status
    if request.output_summary is not None:
        step.output_summary = request.output_summary
    if "assignee_id" in request.model_fields_set:
        _member_or_422(session, context.workspace.id, request.assignee_id)
        step.assignee_id = request.assignee_id
    step.updated_at = now_utc()
    all_steps = session.exec(select(WorkPlanStep).where(WorkPlanStep.plan_id == plan.id)).all()
    if all_steps and all(item.status == "done" for item in all_steps):
        plan.status = "completed"
    elif any(item.status == "running" for item in all_steps):
        plan.status = "in_progress"
    plan.updated_at = now_utc()
    session.add(step)
    session.add(plan)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="work_plan.step_updated",
        target_type="work_plan_step",
        target_id=step.id,
        metadata={"status": step.status},
    )
    session.commit()
    return {"plan": _plan_data(session, plan)}


# ---------------------------------------------------------------------------
# Persistent conversations, streaming AI, and attachments
# ---------------------------------------------------------------------------


@router.get("/v1/conversations")
def list_conversations(
    include_archived: bool = Query(False),
    team: bool = Query(False),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    statement = select(Conversation).where(Conversation.workspace_id == context.workspace.id)
    if not team or (not context.user.is_platform_admin and context.membership.role not in {"owner", "admin"}):
        statement = statement.where(Conversation.owner_id == context.user.id)
    if not include_archived:
        statement = statement.where(Conversation.archived.is_(False))
    conversations = session.exec(statement.order_by(Conversation.updated_at.desc())).all()
    return {"conversations": [_conversation_data(item) for item in conversations]}


@router.post("/v1/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: ConversationCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_workspace_role(context, "owner", "admin", "member")
    if request.project_id:
        _project_or_404(session, context.workspace.id, request.project_id)
    conversation = Conversation(
        workspace_id=context.workspace.id,
        owner_id=context.user.id,
        title=request.title,
        project_id=request.project_id,
        model_id=request.model_id or settings.default_model,
        skill_name=request.skill_name,
    )
    session.add(conversation)
    session.flush()
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="conversation.created",
        target_type="conversation",
        target_id=conversation.id,
    )
    session.commit()
    return {"conversation": _conversation_data(conversation)}


@router.patch("/v1/conversations/{conversation_id}")
def update_conversation(
    conversation_id: str,
    request: ConversationUpdateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    conversation = _conversation_or_404(session, context, conversation_id)
    if request.title is not None:
        conversation.title = request.title
    if request.archived is not None:
        conversation.archived = request.archived
    conversation.updated_at = now_utc()
    session.add(conversation)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="conversation.updated",
        target_type="conversation",
        target_id=conversation.id,
        metadata={"archived": conversation.archived},
    )
    session.commit()
    return {"conversation": _conversation_data(conversation)}


@router.get("/v1/conversations/{conversation_id}/messages")
def list_conversation_messages(
    conversation_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _conversation_or_404(session, context, conversation_id)
    messages = session.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at)
    ).all()
    return {"messages": [_message_data(message) for message in messages]}


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
):
    require_workspace_role(context, "owner", "admin", "member")
    model_id = request.model_id or settings.default_model
    _authorize_agent_config(context, model_id, "default", [])
    _ensure_model_ready(model_id)
    conversation = _create_conversation_for_chat(
        session, context, request.conversation_id, model_id, title_hint=request.query
    )
    user_message = ChatMessage(conversation_id=conversation.id, role="user", content=request.query)
    assistant_message = ChatMessage(conversation_id=conversation.id, role="assistant", content="")
    session.add(user_message)
    session.add(assistant_message)
    conversation.model_id = model_id
    conversation.updated_at = now_utc()
    session.add(conversation)
    session.commit()

    async def stream() -> AsyncGenerator[dict[str, str], None]:
        collected: list[str] = []
        try:
            history = session.exec(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(16)
            ).all()
            messages = [
                {"role": item.role, "content": item.content}
                for item in reversed(history)
                if item.content
            ]
            response = await ModelHub().generate(model_id=model_id, messages=messages, stream=True)
            yield {
                "event": "meta",
                "data": json.dumps({"conversation_id": conversation.id, "message_id": assistant_message.id}),
            }
            async for chunk in response:
                content = chunk.choices[0].delta.content if chunk.choices else ""
                text = AgentEngine._content_to_text(content)
                if text:
                    collected.append(text)
                    yield {"event": "token", "data": text}
            assistant_message.content = "".join(collected)
            conversation.updated_at = now_utc()
            session.add(assistant_message)
            session.add(conversation)
            write_audit(
                session,
                actor_id=context.user.id,
                workspace_id=context.workspace.id,
                action="chat.completed",
                target_type="conversation",
                target_id=conversation.id,
                metadata={"model_id": model_id},
            )
            session.commit()
            yield {"event": "done", "data": "{}"}
        except Exception as exc:
            assistant_message.content = "".join(collected) or "[AI request did not complete]"
            session.add(assistant_message)
            session.commit()
            yield _sse_error(exc)

    return EventSourceResponse(stream(), ping=15, headers={"X-Accel-Buffering": "no"})


@router.post("/v1/chat/agent")
async def agent_chat(
    request: AgentRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
):
    require_workspace_role(context, "owner", "admin", "member")
    model_id = request.model_id or settings.default_model
    engine = get_agent_engine()
    if not engine.skill_manager.get_skill(request.skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{request.skill_name}' not found")
    unknown_servers = [name for name in request.mcp_servers if name not in engine.mcp_manager.servers]
    if unknown_servers:
        raise HTTPException(status_code=404, detail=f"Unknown MCP server(s): {', '.join(unknown_servers)}")
    effective_role = _authorize_agent_config(context, model_id, request.skill_name, request.mcp_servers)
    _ensure_model_ready(model_id)
    conversation = _create_conversation_for_chat(
        session,
        context,
        request.conversation_id,
        model_id,
        request.skill_name,
        request.query,
    )
    user_message = ChatMessage(conversation_id=conversation.id, role="user", content=request.query)
    assistant_message = ChatMessage(conversation_id=conversation.id, role="assistant", content="")
    session.add(user_message)
    session.add(assistant_message)
    conversation.model_id = model_id
    conversation.skill_name = request.skill_name
    conversation.updated_at = now_utc()
    session.add(conversation)
    session.commit()
    config = {
        "model_id": model_id,
        "skill_name": request.skill_name,
        "mcp_servers": request.mcp_servers,
        "thread_id": conversation.id,
    }

    async def stream() -> AsyncGenerator[dict[str, str], None]:
        collected: list[str] = []
        try:
            yield {
                "event": "meta",
                "data": json.dumps({"conversation_id": conversation.id, "message_id": assistant_message.id}),
            }
            async for chunk in engine.run(user_role=effective_role, query=request.query, config=config):
                collected.append(chunk)
                yield {"event": "token", "data": chunk}
            assistant_message.content = "".join(collected)
            conversation.updated_at = now_utc()
            session.add(assistant_message)
            session.add(conversation)
            write_audit(
                session,
                actor_id=context.user.id,
                workspace_id=context.workspace.id,
                action="agent.completed",
                target_type="conversation",
                target_id=conversation.id,
                metadata={"model_id": model_id, "skill_name": request.skill_name},
            )
            session.commit()
            yield {"event": "done", "data": "{}"}
        except Exception as exc:
            assistant_message.content = "".join(collected) or "[Agent request did not complete]"
            session.add(assistant_message)
            session.commit()
            yield _sse_error(exc)

    return EventSourceResponse(stream(), ping=15, headers={"X-Accel-Buffering": "no"})


@router.post("/v1/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    file: UploadFile = File(...),
    task_id: str | None = Form(default=None),
    conversation_id: str | None = Form(default=None),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_workspace_role(context, "owner", "admin", "member")
    if not file.filename:
        raise HTTPException(status_code=422, detail="A file name is required")
    original_name = Path(file.filename).name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=415, detail="This file type is not allowed")
    if task_id:
        _task_or_404(session, context.workspace.id, task_id)
    if conversation_id:
        _conversation_or_404(session, context, conversation_id)
    if not task_id and not conversation_id:
        raise HTTPException(status_code=422, detail="Attach the file to a task or a conversation")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{new_id()}{extension}"
    destination = upload_dir / stored_name
    byte_count = 0
    preview = bytearray()
    limit = settings.max_upload_mb * 1024 * 1024
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                byte_count += len(chunk)
                if byte_count > limit:
                    raise HTTPException(status_code=413, detail=f"File exceeds the {settings.max_upload_mb} MB limit")
                output.write(chunk)
                if len(preview) < 100_000:
                    preview.extend(chunk[: 100_000 - len(preview)])
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    extracted_text = ""
    if extension in {".txt", ".md", ".csv", ".json"}:
        extracted_text = bytes(preview).decode("utf-8", errors="replace")[:100_000]
    attachment = Attachment(
        workspace_id=context.workspace.id,
        uploaded_by=context.user.id,
        task_id=task_id,
        conversation_id=conversation_id,
        original_name=original_name,
        stored_name=stored_name,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=byte_count,
        extracted_text=extracted_text,
    )
    session.add(attachment)
    session.flush()
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="attachment.uploaded",
        target_type="attachment",
        target_id=attachment.id,
        metadata={"name": original_name, "size_bytes": byte_count},
    )
    session.commit()
    return {"attachment": _attachment_data(attachment)}


def _attachment_data(attachment: Attachment) -> dict[str, Any]:
    return {
        "id": attachment.id,
        "workspace_id": attachment.workspace_id,
        "task_id": attachment.task_id,
        "conversation_id": attachment.conversation_id,
        "original_name": attachment.original_name,
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
        "uploaded_by": attachment.uploaded_by,
        "created_at": attachment.created_at,
        "download_url": f"/api/v1/attachments/{attachment.id}/download",
        "preview_url": f"/api/v1/attachments/{attachment.id}/preview",
        "preview_available": bool(attachment.extracted_text),
    }


@router.get("/v1/attachments")
def list_attachments(
    task_id: str | None = Query(None),
    conversation_id: str | None = Query(None),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if task_id:
        _task_or_404(session, context.workspace.id, task_id)
    if conversation_id:
        _conversation_or_404(session, context, conversation_id)
    statement = select(Attachment).where(Attachment.workspace_id == context.workspace.id)
    if task_id:
        statement = statement.where(Attachment.task_id == task_id)
    if conversation_id:
        statement = statement.where(Attachment.conversation_id == conversation_id)
    attachments = session.exec(statement.order_by(Attachment.created_at.desc())).all()
    return {"attachments": [_attachment_data(item) for item in attachments]}


@router.get("/v1/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> FileResponse:
    attachment = session.get(Attachment, attachment_id)
    if not attachment or attachment.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    file_path = Path(settings.upload_dir) / attachment.stored_name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="The attachment file is unavailable")
    return FileResponse(file_path, media_type=attachment.content_type, filename=attachment.original_name)


@router.get("/v1/attachments/{attachment_id}/preview")
def preview_attachment(
    attachment_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Return a bounded text preview for workspace-owned text attachments.

    Binary artifacts remain downloadable but are intentionally not parsed in
    the API process.  This keeps the MVP's preview feature useful without
    pretending to render untrusted office files or PDFs server-side.
    """
    attachment = session.get(Attachment, attachment_id)
    if not attachment or attachment.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return {
        "attachment": _attachment_data(attachment),
        "text": attachment.extracted_text,
        "preview_available": bool(attachment.extracted_text),
        "message": None if attachment.extracted_text else "Preview is available for text, Markdown, CSV, and JSON uploads.",
    }


# ---------------------------------------------------------------------------
# Model, skill, MCP and policy management
# ---------------------------------------------------------------------------


@router.get("/v1/models")
def list_models(
    context: WorkspaceContext = Depends(get_workspace_context),
) -> dict[str, Any]:
    role = _effective_role(context)
    auth = AuthManager()
    models = [
        model_id
        for model_id in ModelHub.list_supported_models()
        if auth.is_allowed(role, f"model:{model_id}", "use")
    ]
    return {
        "models": models,
        "details": [
            {
                "id": model_id,
                "provider": _provider_name(model_id),
                "configured": ModelHub.is_model_configured(model_id),
                "configuration_source": ModelHub.configuration_source(model_id),
                "ready": ModelHub.readiness_error(model_id) is None,
            }
            for model_id in models
        ],
    }


@router.get("/v1/skills")
def list_skills(context: WorkspaceContext = Depends(get_workspace_context)) -> dict[str, Any]:
    role = _effective_role(context)
    auth = AuthManager()
    skills = [
        skill
        for skill in SkillManager().list_skills()
        if auth.is_allowed(role, f"skill:{skill.name}", "use")
    ]
    return {"skills": [skill.model_dump() for skill in skills]}


@router.post("/v1/skills", status_code=status.HTTP_201_CREATED)
def create_skill(
    skill: Skill,
    user: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        saved = SkillManager().save_skill(skill)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    write_audit(session, actor_id=user.id, action="skill.created", target_type="skill", target_id=saved.name)
    session.commit()
    return {"skill": saved.model_dump()}


@router.put("/v1/skills/{skill_name}")
def update_skill(
    skill_name: str,
    skill: Skill,
    user: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if skill_name != skill.name:
        raise HTTPException(status_code=400, detail="Skill path and body names must match")
    manager = SkillManager()
    if skill_name == "default" or not manager.get_skill(skill_name):
        raise HTTPException(status_code=404, detail=f"Editable Skill '{skill_name}' not found")
    saved = manager.save_skill(skill, overwrite=True)
    write_audit(session, actor_id=user.id, action="skill.updated", target_type="skill", target_id=saved.name)
    session.commit()
    return {"skill": saved.model_dump()}


@router.delete("/v1/skills/{skill_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_skill(
    skill_name: str,
    user: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> None:
    try:
        deleted = SkillManager().delete_skill(skill_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    write_audit(session, actor_id=user.id, action="skill.deleted", target_type="skill", target_id=skill_name)
    session.commit()
    return None


@router.get("/v1/mcp/servers")
async def list_mcp_servers(
    probe: bool = Query(False),
    context: WorkspaceContext = Depends(get_workspace_context),
) -> dict[str, Any]:
    if probe:
        require_workspace_role(context, "owner", "admin")
    role = _effective_role(context)
    auth = AuthManager()
    servers = await MCPManager().list_servers(probe=probe)
    return {
        "servers": [
            server for server in servers if auth.is_allowed(role, f"mcp:{server['name']}", "use")
        ]
    }


@router.get("/v1/auth/policies")
def list_policies(user: User = Depends(require_platform_admin)) -> dict[str, Any]:
    auth = AuthManager()
    return {"policies": auth.get_policies(), "roles": auth.get_roles()}


@router.post("/v1/auth/policies", status_code=status.HTTP_201_CREATED)
def add_policy(
    policy: PolicyRequest,
    user: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    auth = AuthManager()
    if not auth.add_policy(policy.role, policy.resource, policy.action):
        raise HTTPException(status_code=409, detail="Policy already exists")
    write_audit(
        session,
        actor_id=user.id,
        action="policy.created",
        target_type="policy",
        target_id=f"{policy.role}:{policy.resource}:{policy.action}",
    )
    session.commit()
    return {"policy": [policy.role, policy.resource, policy.action]}


@router.delete("/v1/auth/policies", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy(
    policy: PolicyRequest,
    user: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> None:
    auth = AuthManager()
    if not auth.remove_policy(policy.role, policy.resource, policy.action):
        raise HTTPException(status_code=404, detail="Policy not found")
    write_audit(
        session,
        actor_id=user.id,
        action="policy.deleted",
        target_type="policy",
        target_id=f"{policy.role}:{policy.resource}:{policy.action}",
    )
    session.commit()
    return None


@router.get("/v1/settings")
def public_settings(user: User = Depends(require_platform_admin)) -> dict[str, Any]:
    return {
        "environment": settings.environment,
        "default_model": settings.default_model,
        "mcp_servers": list(settings.mcp_servers),
        "providers": {
            "openai": bool(settings.openai_api_key),
            "anthropic": bool(settings.anthropic_api_key),
            "google": bool(settings.google_api_key),
            "ollama": True,
        },
        "litellm": {"enabled": bool(settings.litellm_proxy_url), "url": settings.litellm_proxy_url},
        "observability": {"langfuse": bool(settings.langfuse_public_key and settings.langfuse_secret_key)},
        "uploads": {"max_upload_mb": settings.max_upload_mb},
    }


# ---------------------------------------------------------------------------
# Operational dashboards and audit trail (platform administrator only)
# ---------------------------------------------------------------------------


@router.get("/v1/admin/overview")
def admin_overview(
    user: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return {
        "counts": {
            "users": len(session.exec(select(User.id)).all()),
            "workspaces": len(session.exec(select(Workspace.id)).all()),
            "projects": len(session.exec(select(Project.id)).all()),
            "tasks": len(session.exec(select(Task.id)).all()),
            "conversations": len(session.exec(select(Conversation.id)).all()),
            "attachments": len(session.exec(select(Attachment.id)).all()),
            "models": len(ModelHub.list_supported_models()),
            "skills": len(SkillManager().list_skills()),
            "roles": len(AuthManager().get_roles()),
            "mcp_servers": len(MCPManager().servers),
        },
        "default_model": settings.default_model,
        "environment": settings.environment,
    }


@router.get("/v1/dashboard")
def dashboard(
    user: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return admin_overview(user=user, session=session)


@router.get("/v1/admin/users")
def admin_list_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    users = session.exec(select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)).all()
    return {"users": [_user_data(item) for item in users], "offset": offset, "limit": limit}


@router.patch("/v1/admin/users/{user_id}")
def admin_update_user(
    user_id: str,
    request: AdminUserUpdateRequest,
    admin: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    target = session.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == admin.id and request.is_active is False:
        raise HTTPException(status_code=409, detail="You cannot disable your own account")
    for field in ("display_name", "is_active", "is_platform_admin"):
        if field in request.model_fields_set:
            setattr(target, field, getattr(request, field))
    target.updated_at = now_utc()
    session.add(target)
    write_audit(
        session,
        actor_id=admin.id,
        action="admin.user_updated",
        target_type="user",
        target_id=target.id,
        metadata={"is_active": target.is_active, "is_platform_admin": target.is_platform_admin},
    )
    session.commit()
    return {"user": _user_data(target)}


@router.get("/v1/admin/workspaces")
def admin_list_workspaces(
    user: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    workspaces = session.exec(select(Workspace).order_by(Workspace.created_at.desc())).all()
    membership_counts: dict[str, int] = {}
    for membership in session.exec(select(Membership)).all():
        membership_counts[membership.workspace_id] = membership_counts.get(membership.workspace_id, 0) + 1
    return {
        "workspaces": [
            {**_workspace_data(workspace), "member_count": membership_counts.get(workspace.id, 0)}
            for workspace in workspaces
        ]
    }


@router.get("/v1/audit-events")
def list_workspace_audit_events(
    limit: int = Query(100, ge=1, le=500),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_workspace_role(context, "owner", "admin")
    events = session.exec(
        select(AuditEvent)
        .where(AuditEvent.workspace_id == context.workspace.id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).all()
    return {"events": [_audit_data(event) for event in events]}


@router.get("/v1/admin/audit-events")
def admin_list_audit_events(
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    events = session.exec(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)).all()
    return {"events": [_audit_data(event) for event in events]}
