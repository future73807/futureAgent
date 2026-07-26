"""Authenticated, workspace-scoped REST API for futureAgent.

The earlier prototype accepted a ``user_role`` sent by the browser.  This
module intentionally never does that: identity comes from a signed bearer
token and the effective permissions are derived from the user's workspace
membership on the server.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any, AsyncGenerator, Literal
from urllib.parse import quote
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sse_starlette.sse import EventSourceResponse
from starlette.background import BackgroundTask
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
from core.observability import metrics_payload, record_agent_run, record_attachment_upload
from core.skill_manager import Skill, SkillManager
from core.storage import ObjectNotFound, StorageError, attachment_object_key, get_storage
from db.database import get_session
from db.models import (
    AgentRun,
    Attachment,
    AuditEvent,
    BusinessAlert,
    BusinessAlertRule,
    BusinessAssistantMessage,
    BusinessBossTask,
    BusinessDataSource,
    BusinessRecord,
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
PREVIEW_TEXT_LIMIT = 100_000
PREVIEW_ARCHIVE_MEMBER_LIMIT = 2_000_000


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
    title: str = Field(default="新对话", min_length=1, max_length=240)
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


class TaskExecutionRequest(RequestModel):
    """Request a governed AI attempt against an approved Work-mode plan."""

    model_id: str = Field(default="", max_length=120)
    skill_name: str = Field(default="default", max_length=120)
    step_id: str | None = Field(default=None, max_length=64)
    mcp_servers: list[str] = Field(default_factory=list, max_length=20)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=96)
    retry_of_id: str | None = Field(default=None, max_length=64)


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
        detail = "AI 服务未能完成本次请求，请稍后重试。"
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


def _agent_run_data(run: AgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "task_id": run.task_id,
        "plan_id": run.plan_id,
        "step_id": run.step_id,
        "requested_by": run.requested_by,
        "model_id": run.model_id,
        "skill_name": run.skill_name,
        "retry_of_id": run.retry_of_id,
        "attempt": run.attempt,
        "status": run.status,
        "output": run.output,
        "error_message": run.error_message,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
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


def _audit_visible_to_user(event: AuditEvent, user: User) -> bool:
    """Private operating-agent audit metadata never grants admin bypass."""
    return event.visibility != "private" or event.owner_user_id == user.id


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
        raise HTTPException(status_code=403, detail="没有该工作区的访问权限")
    if membership:
        return membership
    # Platform administrators may operate a workspace without a membership.
    return Membership(workspace_id=workspace_id, user_id=user.id, role="admin")


def _workspace_or_404(session: Session, workspace_id: str) -> Workspace:
    workspace = session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return workspace


def _require_workspace_manager(session: Session, user: User, workspace_id: str) -> Membership:
    membership = _membership_for_workspace(session, user, workspace_id)
    if not user.is_platform_admin and membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="需要工作区管理员权限")
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
        raise HTTPException(status_code=422, detail="负责人必须属于当前工作区")


def _project_or_404(session: Session, workspace_id: str, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project or project.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _task_or_404(session: Session, workspace_id: str, task_id: str) -> Task:
    task = session.get(Task, task_id)
    if not task or task.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _conversation_or_404(
    session: Session,
    context: WorkspaceContext,
    conversation_id: str,
) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if not conversation or conversation.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="对话不存在")
    if (
        conversation.owner_id != context.user.id
        and not context.user.is_platform_admin
        and context.membership.role not in {"owner", "admin"}
    ):
        raise HTTPException(status_code=403, detail="没有该对话的访问权限")
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


def _validate_mcp_server_selection(engine: AgentEngine, mcp_servers: list[str]) -> None:
    unknown_servers = [name for name in mcp_servers if name not in engine.mcp_manager.servers]
    if unknown_servers:
        raise HTTPException(status_code=404, detail=f"未知 MCP 服务：{', '.join(unknown_servers)}")
    if "local_tools" in mcp_servers and not settings.enable_local_mcp_tools:
        raise HTTPException(
            status_code=403,
            detail="当前部署未启用本地 MCP 文件工具。启用前请配置按工作区隔离的连接器。",
        )


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


def _refresh_session_expired(expires_at: Any) -> bool:
    """Compare refresh expirations safely across SQLite and PostgreSQL.

    The application stores UTC timestamps. PostgreSQL can return a naive
    ``timestamp without time zone`` value for existing rows, while ``now_utc``
    is timezone-aware. Treat those legacy/database values as UTC so a valid
    refresh token cannot trigger a server error during comparison.
    """
    current_time = now_utc()
    if getattr(expires_at, "tzinfo", None) is None:
        expires_at = expires_at.replace(tzinfo=current_time.tzinfo)
    return expires_at <= current_time


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
            raise HTTPException(status_code=409, detail="对话已归档")
        return conversation
    conversation = Conversation(
        workspace_id=context.workspace.id,
        owner_id=context.user.id,
        title=(title_hint[:60] or "新对话"),
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


@router.get("/v1/health/live")
async def liveness() -> dict[str, str]:
    """Process-only probe: it stays green while dependencies recover."""
    return {"status": "ok"}


@router.get("/v1/health/ready")
def readiness(session: Session = Depends(get_session)) -> JSONResponse:
    """Readiness probe for the database and configured attachment backend."""
    failures: list[str] = []
    try:
        session.exec(select(User.id).limit(1)).first()
    except Exception:
        failures.append("database")
    try:
        get_storage().check_ready()
    except StorageError:
        failures.append("storage")
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE if failures else status.HTTP_200_OK
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "not_ready" if failures else "ready",
            "service": "futureAgent",
            "checks": {"database": "failed" if "database" in failures else "ok", "storage": "failed" if "storage" in failures else "ok"},
        },
    )


@router.get("/metrics", include_in_schema=False)
def metrics(authorization: Annotated[str | None, Header()] = None) -> Response:
    """Return Prometheus metrics only with a configured bearer token in production."""
    expected_token = settings.metrics_bearer_token
    supplied_token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if expected_token:
        if not secrets.compare_digest(supplied_token, expected_token):
            raise HTTPException(status_code=401, detail="指标接口认证失败")
    elif settings.environment.lower() == "production":
        raise HTTPException(status_code=404, detail="资源不存在")
    payload, content_type = metrics_payload()
    return Response(content=payload, media_type=content_type)


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
        raise HTTPException(status_code=409, detail="该邮箱已注册账号")
    user = User(
        email=email,
        display_name=request.display_name,
        password_hash=hash_password(request.password),
    )
    session.add(user)
    session.flush()
    workspace_name = request.workspace_name or f"{request.display_name}的工作区"
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
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="该账号已被停用")
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
        raise HTTPException(status_code=401, detail="续期会话不存在")
    payload = decode_token(refresh_token, expected_type="refresh")
    refresh_session = session.get(RefreshSession, payload["jti"])
    if (
        not refresh_session
        or refresh_session.user_id != payload["sub"]
        or refresh_session.revoked
        or _refresh_session_expired(refresh_session.expires_at)
    ):
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="续期会话已过期")
    user = session.get(User, refresh_session.user_id)
    if not user or not user.is_active:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="账号当前不可用")
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
        raise HTTPException(status_code=422, detail="角色只能是管理员、成员或只读成员")
    member_user = session.exec(
        select(User).where(User.email == str(request.email).lower())
    ).first()
    if not member_user:
        raise HTTPException(status_code=404, detail="受邀用户需要先完成注册")
    if session.exec(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == member_user.id,
        )
    ).first():
        raise HTTPException(status_code=409, detail="该用户已经是工作区成员")
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
        raise HTTPException(status_code=422, detail="角色只能是管理员、成员或只读成员")
    membership = session.get(Membership, member_id)
    if not membership or membership.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    if membership.role == "owner":
        raise HTTPException(status_code=409, detail="请先转移所有权，再修改所有者角色")
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
        raise HTTPException(status_code=404, detail="成员不存在")
    if membership.role == "owner":
        raise HTTPException(status_code=409, detail="请先转移所有权，再移除所有者")
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
        raise HTTPException(status_code=403, detail="只有工作区所有者可以转移所有权")
    target_membership = session.get(Membership, request.member_id)
    if not target_membership or target_membership.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="目标成员不存在")
    # Boss/private operating-agent data must never silently cross an ownership
    # boundary.  A deliberate archival/handover workflow can be added later;
    # this MVP blocks the transfer instead of exposing the old owner's private
    # assistant history, sources, alerts or tasks to the new owner.
    has_private_business_data = any(
        (
            session.exec(
                select(BusinessDataSource.id).where(
                    BusinessDataSource.workspace_id == workspace_id,
                    BusinessDataSource.data_scope != "company",
                ).limit(1)
            ).first(),
            session.exec(
                select(BusinessRecord.id).where(
                    BusinessRecord.workspace_id == workspace_id,
                    BusinessRecord.data_scope != "company",
                ).limit(1)
            ).first(),
            session.exec(
                select(BusinessAlertRule.id).where(
                    BusinessAlertRule.workspace_id == workspace_id,
                    BusinessAlertRule.data_scope != "company",
                ).limit(1)
            ).first(),
            session.exec(
                select(BusinessAlert.id).where(
                    BusinessAlert.workspace_id == workspace_id,
                    BusinessAlert.data_scope != "company",
                ).limit(1)
            ).first(),
            session.exec(
                select(BusinessAssistantMessage.id).where(
                    BusinessAssistantMessage.workspace_id == workspace_id,
                    BusinessAssistantMessage.owner_user_id == workspace.owner_id,
                ).limit(1)
            ).first(),
            session.exec(
                select(BusinessBossTask.id).where(
                    BusinessBossTask.workspace_id == workspace_id,
                    BusinessBossTask.boss_user_id == workspace.owner_id,
                ).limit(1)
            ).first(),
        )
    )
    if has_private_business_data:
        write_audit(
            session,
            actor_id=user.id,
            workspace_id=workspace_id,
            action="workspace.owner_transfer_blocked_private_business_data",
            target_type="workspace",
            target_id=workspace_id,
            metadata={"reason": "private_business_data_requires_archival_or_handover"},
            visibility="private",
            owner_user_id=workspace.owner_id,
        )
        session.commit()
        raise HTTPException(
            status_code=409,
            detail="工作区存在老板或私事经营数据；请先完成归档或受控交接后再转移所有权",
        )
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
            raise HTTPException(status_code=422, detail="未知的任务状态")
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
        raise HTTPException(status_code=422, detail="任务状态或优先级无效")
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
        raise HTTPException(status_code=422, detail="任务状态无效")
    if request.priority is not None and request.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail="任务优先级无效")
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
        run.id
        for run in session.exec(
            select(AgentRun).where(
                AgentRun.workspace_id == context.workspace.id,
                AgentRun.task_id == task_id,
            )
        ).all()
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
    return {
        "events": [
            _audit_data(event)
            for event in events
            if _audit_visible_to_user(event, context.user)
        ]
    }


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
        raise HTTPException(status_code=403, detail="已批准的计划只能由工作区管理员修改")
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
                raise HTTPException(status_code=422, detail="计划步骤不属于当前计划")
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
        raise HTTPException(status_code=404, detail="工作计划不存在")
    if not session.exec(select(WorkPlanStep.id).where(WorkPlanStep.plan_id == plan.id)).first():
        raise HTTPException(status_code=422, detail="工作计划至少需要一个步骤才能批准")
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
        raise HTTPException(status_code=404, detail="工作计划步骤不存在")
    can_update = (
        context.user.is_platform_admin
        or context.membership.role in {"owner", "admin"}
        or step.assignee_id == context.user.id
        or task.assignee_id == context.user.id
        or task.reporter_id == context.user.id
    )
    if not can_update:
        raise HTTPException(status_code=403, detail="没有更新该计划步骤的权限")
    if request.status is not None:
        if request.status not in STEP_STATUSES:
            raise HTTPException(status_code=422, detail="工作计划步骤状态无效")
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
            import traceback
            traceback.print_exc()
            assistant_message.content = "".join(collected) or f"[AI request did not complete: {str(exc)}]"
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
        raise HTTPException(status_code=404, detail=f"技能“{request.skill_name}”不存在")
    _validate_mcp_server_selection(engine, request.mcp_servers)
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


def _task_execution_prompt(
    session: Session,
    workspace_id: str,
    task: Task,
    plan: WorkPlan,
    step: WorkPlanStep | None,
) -> str:
    """Build bounded task context without exposing another workspace's data."""
    attachments = session.exec(
        select(Attachment)
        .where(
            Attachment.workspace_id == workspace_id,
            Attachment.task_id == task.id,
        )
        .order_by(Attachment.created_at.desc())
        .limit(12)
    ).all()
    excerpts: list[str] = []
    remaining = 20_000
    for attachment in attachments:
        if not attachment.extracted_text or remaining <= 0:
            continue
        excerpt = attachment.extracted_text[:remaining]
        excerpts.append(f"[Attached file: {attachment.original_name}]\n{excerpt}")
        remaining -= len(excerpt)
    current_step = (
        f"Step: {step.title}\nInstructions: {step.instructions or 'No additional instructions.'}"
        if step
        else "Step: Produce the next useful, reviewable deliverable for this plan."
    )
    context_files = "\n\n".join(excerpts) or "No text context files were attached to this task."
    return (
        "You are carrying out governed work inside a team workspace. "
        "Use only the task context below. Return a concise, reviewable deliverable with "
        "what you did, concrete evidence, assumptions, and the recommended next action. "
        "Do not claim that an external action happened unless a tool result proves it.\n\n"
        f"Task: {task.title}\nDescription: {task.description or 'No description provided.'}\n"
        f"Objective: {plan.objective or 'No objective provided.'}\n{current_step}\n\n"
        f"Task context files:\n{context_files}"
    )


def _can_manage_task_execution(
    context: WorkspaceContext,
    task: Task,
    step: WorkPlanStep | None,
) -> bool:
    """Keep execution, cancellation, and retry authorisation identical."""
    return bool(
        context.user.is_platform_admin
        or context.membership.role in {"owner", "admin"}
        or (step and step.assignee_id == context.user.id)
        or task.assignee_id == context.user.id
        or task.reporter_id == context.user.id
    )


def _expire_stale_agent_runs(session: Session, workspace_id: str) -> None:
    """Release slots left running after a worker crash or an abandoned stream."""
    timeout_seconds = max(1, settings.agent_run_timeout_seconds)
    cutoff = now_utc() - timedelta(seconds=timeout_seconds)
    stale_runs = session.exec(
        select(AgentRun).where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.status == "running",
            AgentRun.started_at < cutoff,
        )
    ).all()
    if not stale_runs:
        return
    for stale_run in stale_runs:
        stale_run.status = "failed"
        stale_run.completed_at = now_utc()
        stale_run.error_message = "AI 执行超过允许时长，已被停止。"
        session.add(stale_run)
        write_audit(
            session,
            actor_id=stale_run.requested_by,
            workspace_id=workspace_id,
            action="agent_run.timed_out",
            target_type="agent_run",
            target_id=stale_run.id,
            metadata={"timeout_seconds": timeout_seconds},
        )
        record_agent_run("timed_out")
    session.commit()


def _run_cancelled(session: Session, run: AgentRun) -> bool:
    """Refresh the row so a separate cancellation request is observed."""
    session.expire(run)
    session.refresh(run)
    return run.status == "cancelled"


@router.get("/v1/tasks/{task_id}/runs")
def list_task_runs(
    task_id: str,
    limit: int = Query(20, ge=1, le=100),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _task_or_404(session, context.workspace.id, task_id)
    runs = session.exec(
        select(AgentRun)
        .where(AgentRun.workspace_id == context.workspace.id, AgentRun.task_id == task_id)
        .order_by(AgentRun.started_at.desc())
        .limit(limit)
    ).all()
    return {"runs": [_agent_run_data(run) for run in runs]}


@router.post("/v1/tasks/{task_id}/runs/{run_id}/cancel")
def cancel_task_run(
    task_id: str,
    run_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Request a durable cancellation; the stream stops on its next checkpoint."""
    task = _task_or_404(session, context.workspace.id, task_id)
    run = session.get(AgentRun, run_id)
    if not run or run.workspace_id != context.workspace.id or run.task_id != task.id:
        raise HTTPException(status_code=404, detail="AI 执行记录不存在")
    step = session.get(WorkPlanStep, run.step_id) if run.step_id else None
    if not _can_manage_task_execution(context, task, step):
        raise HTTPException(status_code=403, detail="没有取消该任务 AI 执行的权限")
    if run.status != "running":
        return {"run": _agent_run_data(run)}
    run.status = "cancelled"
    run.completed_at = now_utc()
    run.error_message = "AI 执行已被有权限的工作区成员取消。"
    session.add(run)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="agent_run.cancelled",
        target_type="agent_run",
        target_id=run.id,
        metadata={"task_id": task.id, "step_id": run.step_id},
    )
    session.commit()
    record_agent_run("cancelled")
    return {"run": _agent_run_data(run)}


@router.post("/v1/tasks/{task_id}/execute")
async def execute_task_with_agent(
    task_id: str,
    request: TaskExecutionRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
):
    """Run an approved plan step and persist a reviewable execution record."""
    task = _task_or_404(session, context.workspace.id, task_id)
    plan = session.exec(select(WorkPlan).where(WorkPlan.task_id == task.id)).first()
    if not plan or plan.status not in {"approved", "in_progress"}:
        raise HTTPException(status_code=409, detail="请先批准工作计划，再启动 AI 执行")
    step = session.get(WorkPlanStep, request.step_id) if request.step_id else None
    if step and step.plan_id != plan.id:
        raise HTTPException(status_code=404, detail="工作计划步骤不存在")
    if not _can_manage_task_execution(context, task, step):
        raise HTTPException(status_code=403, detail="没有执行该任务步骤的权限")

    model_id = request.model_id or settings.default_model
    engine = get_agent_engine()
    if not engine.skill_manager.get_skill(request.skill_name):
        raise HTTPException(status_code=404, detail=f"技能“{request.skill_name}”不存在")
    _validate_mcp_server_selection(engine, request.mcp_servers)
    effective_role = _authorize_agent_config(context, model_id, request.skill_name, request.mcp_servers)
    _ensure_model_ready(model_id)

    _expire_stale_agent_runs(session, context.workspace.id)
    if request.idempotency_key:
        existing = session.exec(
            select(AgentRun).where(
                AgentRun.workspace_id == context.workspace.id,
                AgentRun.idempotency_key == request.idempotency_key,
            )
        ).first()
        if existing:
            detail = "该请求标识对应的 AI 执行正在运行。" if existing.status == "running" else "该 AI 执行请求已被记录，请创建新的重试请求。"
            raise HTTPException(status_code=409, detail=detail)
    active_runs = session.exec(
        select(AgentRun).where(
            AgentRun.workspace_id == context.workspace.id,
            AgentRun.status == "running",
        )
    ).all()
    max_concurrent = max(1, settings.max_concurrent_agent_runs_per_workspace)
    if len(active_runs) >= max_concurrent:
        raise HTTPException(
            status_code=429,
            detail=f"当前工作区已达到 {max_concurrent} 个 AI 执行的并发上限，请等待运行结束或取消正在运行的执行。",
        )

    retry_parent: AgentRun | None = None
    if request.retry_of_id:
        retry_parent = session.get(AgentRun, request.retry_of_id)
        if not retry_parent or retry_parent.workspace_id != context.workspace.id or retry_parent.task_id != task.id:
            raise HTTPException(status_code=404, detail="要重试的 AI 执行记录不存在")
        if retry_parent.status not in {"failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="只有执行失败或已取消的记录可以重试")

    run = AgentRun(
        workspace_id=context.workspace.id,
        task_id=task.id,
        plan_id=plan.id,
        step_id=step.id if step else None,
        requested_by=context.user.id,
        model_id=model_id,
        skill_name=request.skill_name,
        idempotency_key=request.idempotency_key or None,
        retry_of_id=retry_parent.id if retry_parent else None,
        attempt=(retry_parent.attempt + 1) if retry_parent else 1,
    )
    if step and step.status == "pending":
        step.status = "running"
        step.updated_at = now_utc()
        plan.status = "in_progress"
        plan.updated_at = now_utc()
        session.add(step)
        session.add(plan)
    session.add(run)
    session.flush()
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="agent_run.started",
        target_type="agent_run",
        target_id=run.id,
        metadata={"task_id": task.id, "step_id": run.step_id, "model_id": model_id},
    )
    session.commit()
    prompt = _task_execution_prompt(session, context.workspace.id, task, plan, step)
    config = {
        "model_id": model_id,
        "skill_name": request.skill_name,
        "mcp_servers": request.mcp_servers,
        "thread_id": f"task-run-{run.id}",
    }

    async def stream() -> AsyncGenerator[dict[str, str], None]:
        collected: list[str] = []
        try:
            yield {
                "event": "meta",
                "data": json.dumps({"run": _agent_run_data(run)}, default=str),
            }
            async with asyncio.timeout(max(1, settings.agent_run_timeout_seconds)):
                async for chunk in engine.run(user_role=effective_role, query=prompt, config=config):
                    if _run_cancelled(session, run):
                        yield {"event": "cancelled", "data": json.dumps({"run": _agent_run_data(run)}, default=str)}
                        return
                    collected.append(chunk)
                    yield {"event": "token", "data": chunk}
            if _run_cancelled(session, run):
                yield {"event": "cancelled", "data": json.dumps({"run": _agent_run_data(run)}, default=str)}
                return
            run.status = "succeeded"
            run.output = "".join(collected)
            run.completed_at = now_utc()
            session.add(run)
            write_audit(
                session,
                actor_id=context.user.id,
                workspace_id=context.workspace.id,
                action="agent_run.completed",
                target_type="agent_run",
                target_id=run.id,
                metadata={"status": run.status, "step_id": run.step_id},
            )
            session.commit()
            record_agent_run("succeeded")
            yield {
                "event": "done",
                "data": json.dumps({"run": _agent_run_data(run)}, default=str),
            }
        except Exception as exc:
            if _run_cancelled(session, run):
                yield {"event": "cancelled", "data": json.dumps({"run": _agent_run_data(run)}, default=str)}
                return
            run.status = "failed"
            run.output = "".join(collected)
            run.error_message = (
                f"AI 执行超过 {max(1, settings.agent_run_timeout_seconds)} 秒限制，请检查模型路由后重试。"
                if isinstance(exc, TimeoutError)
                else "AI 执行未完成，请检查模型路由后重试。"
            )
            run.completed_at = now_utc()
            session.add(run)
            write_audit(
                session,
                actor_id=context.user.id,
                workspace_id=context.workspace.id,
                action="agent_run.failed",
                target_type="agent_run",
                target_id=run.id,
                metadata={"step_id": run.step_id},
            )
            session.commit()
            record_agent_run("failed")
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
        raise HTTPException(status_code=422, detail="必须提供文件名")
    original_name = Path(file.filename).name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=415, detail="不允许上传该文件类型")
    if task_id:
        _task_or_404(session, context.workspace.id, task_id)
    if conversation_id:
        _conversation_or_404(session, context, conversation_id)
    if not task_id and not conversation_id:
        raise HTTPException(status_code=422, detail="请将文件关联到任务或对话")

    byte_count = 0
    preview = bytearray()
    limit = settings.max_upload_mb * 1024 * 1024
    buffered_upload = tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024, mode="w+b")
    try:
        while chunk := await file.read(1024 * 1024):
            byte_count += len(chunk)
            if byte_count > limit:
                raise HTTPException(status_code=413, detail=f"文件超过 {settings.max_upload_mb} MB 大小限制")
            buffered_upload.write(chunk)
            if len(preview) < PREVIEW_TEXT_LIMIT:
                preview.extend(chunk[: PREVIEW_TEXT_LIMIT - len(preview)])
    except Exception:
        buffered_upload.close()
        raise
    finally:
        await file.close()

    stored_name = attachment_object_key(context.workspace.id, f"{new_id()}{extension}")
    stored = False
    try:
        storage = get_storage()
        buffered_upload.seek(0)
        storage.put_stream(
            stored_name,
            buffered_upload,
            content_type=file.content_type or "application/octet-stream",
        )
        stored = True
        buffered_upload.seek(0)
        extracted_text = _extract_attachment_text(buffered_upload, extension, bytes(preview))
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
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="附件存储当前不可用") from exc
    except Exception:
        session.rollback()
        if stored:
            try:
                storage.delete(stored_name)
            except StorageError:
                pass
        raise
    finally:
        buffered_upload.close()

    record_attachment_upload(settings.storage_backend.strip().lower())
    return {"attachment": _attachment_data(attachment)}


def _attachment_data(attachment: Attachment) -> dict[str, Any]:
    preview_kind = _attachment_preview_kind(attachment)
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
        "preview_available": preview_kind != "none",
        "preview_kind": preview_kind,
    }


def _attachment_preview_kind(attachment: Attachment) -> str:
    extension = Path(attachment.original_name).suffix.lower()
    if attachment.content_type.startswith("image/") or extension in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    if extension == ".pdf":
        return "pdf"
    if attachment.extracted_text:
        return "text"
    return "none"


def _bounded_zip_member(zip_file: ZipFile, member_name: str) -> bytes:
    try:
        info = zip_file.getinfo(member_name)
    except KeyError:
        return b""
    if info.file_size > PREVIEW_ARCHIVE_MEMBER_LIMIT:
        return b""
    with zip_file.open(info) as source:
        return source.read(PREVIEW_ARCHIVE_MEMBER_LIMIT + 1)[:PREVIEW_ARCHIVE_MEMBER_LIMIT]


def _xml_local_name(node: ElementTree.Element) -> str:
    return node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else ""


def _extract_docx_text(source: Path | Any) -> str:
    try:
        if hasattr(source, "seek"):
            source.seek(0)
        with ZipFile(source) as archive:
            raw = _bounded_zip_member(archive, "word/document.xml")
        if not raw:
            return ""
        root = ElementTree.fromstring(raw)
        return "".join(
            node.text or "" for node in root.iter() if _xml_local_name(node) == "t"
        )[:PREVIEW_TEXT_LIMIT]
    except (BadZipFile, ElementTree.ParseError, OSError):
        return ""


def _extract_xlsx_text(source: Path | Any) -> str:
    try:
        if hasattr(source, "seek"):
            source.seek(0)
        with ZipFile(source) as archive:
            shared_root = ElementTree.fromstring(_bounded_zip_member(archive, "xl/sharedStrings.xml") or b"<sst/>")
            shared_strings = [
                "".join(node.itertext())
                for node in shared_root.iter()
                if _xml_local_name(node) == "si"
            ]
            sheet_root = ElementTree.fromstring(_bounded_zip_member(archive, "xl/worksheets/sheet1.xml") or b"<worksheet/>")
        rows: list[str] = []
        for row in (node for node in sheet_root.iter() if _xml_local_name(node) == "row"):
            values: list[str] = []
            for cell in (node for node in row.iter() if _xml_local_name(node) == "c"):
                value_node = next((node for node in cell.iter() if _xml_local_name(node) == "v"), None)
                value = value_node.text if value_node is not None and value_node.text else ""
                if cell.attrib.get("t") == "s" and value.isdigit():
                    index = int(value)
                    value = shared_strings[index] if index < len(shared_strings) else ""
                values.append(value)
            if values:
                rows.append("\t".join(values))
            if sum(len(item) + 1 for item in rows) >= PREVIEW_TEXT_LIMIT:
                break
        return "\n".join(rows)[:PREVIEW_TEXT_LIMIT]
    except (BadZipFile, ElementTree.ParseError, OSError):
        return ""


def _extract_attachment_text(source: Path | Any, extension: str, first_bytes: bytes) -> str:
    if extension in {".txt", ".md", ".csv", ".json"}:
        return first_bytes.decode("utf-8", errors="replace")[:PREVIEW_TEXT_LIMIT]
    if extension == ".docx":
        return _extract_docx_text(source)
    if extension == ".xlsx":
        return _extract_xlsx_text(source)
    return ""


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
) -> StreamingResponse:
    attachment = session.get(Attachment, attachment_id)
    if not attachment or attachment.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="附件不存在")
    try:
        stream = get_storage().open_stream(attachment.stored_name)
    except ObjectNotFound as exc:
        raise HTTPException(status_code=404, detail="附件文件当前不可用") from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="附件存储当前不可用") from exc
    safe_filename = re.sub(r'[\\"\r\n]+', "_", attachment.original_name) or "attachment"
    disposition = f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{quote(attachment.original_name)}"
    return StreamingResponse(
        stream,
        media_type=attachment.content_type,
        headers={"Content-Disposition": disposition},
        background=BackgroundTask(stream.close),
    )


@router.get("/v1/attachments/{attachment_id}/preview")
def preview_attachment(
    attachment_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Return a bounded, authenticated preview descriptor for a task file."""
    attachment = session.get(Attachment, attachment_id)
    if not attachment or attachment.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="附件不存在")
    attachment_data = _attachment_data(attachment)
    preview_kind = attachment_data["preview_kind"]
    messages = {
        "image": "图片将在通过权限校验的下载后由浏览器预览。",
        "pdf": "PDF 将在通过权限校验的下载后由浏览器预览。",
        "text": None,
        "none": "文本、Markdown、CSV、JSON、Word、Excel、图片和 PDF 文件支持受控预览。",
    }
    return {
        "attachment": attachment_data,
        "text": attachment.extracted_text,
        "preview_kind": preview_kind,
        "preview_available": preview_kind != "none",
        "message": messages[preview_kind],
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


@router.post("/v1/models/{model_id:path}/probe")
async def probe_model(
    model_id: str,
    user: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Perform one real, bounded inference to validate an operator's route."""
    if model_id not in ModelHub.list_supported_models():
        raise HTTPException(status_code=404, detail="不支持的模型")
    _ensure_model_ready(model_id)
    try:
        response = await asyncio.wait_for(
            ModelHub().generate(
                model_id=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": "Reply with exactly: futureAgent model verification",
                    }
                ],
                temperature=0,
                stream=False,
            ),
            timeout=30,
        )
        choices = getattr(response, "choices", [])
        content = choices[0].message.content if choices else ""
        sample = AgentEngine._content_to_text(content)[:240] or str(content)[:240]
        if not sample:
            raise RuntimeError("模型未返回验证响应")
    except HTTPException:
        raise
    except Exception as exc:
        write_audit(
            session,
            actor_id=user.id,
            action="model.probe_failed",
            target_type="model",
            target_id=model_id,
        )
        session.commit()
        raise HTTPException(
            status_code=502,
            detail="已配置的模型路由没有返回验证响应。",
        ) from exc
    write_audit(
        session,
        actor_id=user.id,
        action="model.probed",
        target_type="model",
        target_id=model_id,
        metadata={"sample_length": len(sample)},
    )
    session.commit()
    return {"model_id": model_id, "status": "verified", "sample": sample}


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
        raise HTTPException(status_code=400, detail="技能路径名称必须与请求内容名称一致")
    manager = SkillManager()
    if skill_name == "default" or not manager.get_skill(skill_name):
        raise HTTPException(status_code=404, detail=f"可编辑技能“{skill_name}”不存在")
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
        raise HTTPException(status_code=404, detail=f"技能“{skill_name}”不存在")
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
        raise HTTPException(status_code=409, detail="权限策略已存在")
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
        raise HTTPException(status_code=404, detail="权限策略不存在")
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
        "storage": {
            "backend": settings.storage_backend,
            "s3_configured": bool(settings.storage_s3_bucket and settings.storage_s3_access_key_id and settings.storage_s3_secret_access_key),
        },
        "database": {
            "backend": "postgresql" if settings.database_url.lower().startswith(("postgresql", "postgresql+")) else "sqlite",
        },
        "operations": {
            "migrations_on_startup": settings.run_migrations_on_startup,
            "metrics_protected": bool(settings.metrics_bearer_token),
            "local_mcp_tools_enabled": settings.enable_local_mcp_tools,
            "agent_run_timeout_seconds": settings.agent_run_timeout_seconds,
            "max_concurrent_agent_runs_per_workspace": settings.max_concurrent_agent_runs_per_workspace,
        },
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
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.id == admin.id and request.is_active is False:
        raise HTTPException(status_code=409, detail="不能停用自己的账号")
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
    return {
        "events": [
            _audit_data(event)
            for event in events
            if _audit_visible_to_user(event, context.user)
        ]
    }


@router.get("/v1/admin/audit-events")
def admin_list_audit_events(
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    events = session.exec(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)).all()
    return {
        "events": [
            _audit_data(event)
            for event in events
            if _audit_visible_to_user(event, user)
        ]
    }


# Keep the operating-agent module isolated from the general project/task API
# while mounting it below the same authenticated /api/v1 boundary.
from api.business_routes import router as business_router

router.include_router(business_router, prefix="/v1/business")
