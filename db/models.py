"""工作台的持久化数据模型。

所有业务数据都以 workspace 为边界，避免把演示阶段的全局数据直接暴露给所有用户。
"""
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def new_id() -> str:
    return uuid4().hex


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(default_factory=new_id, primary_key=True)
    email: str = Field(index=True, unique=True, max_length=320)
    display_name: str = Field(max_length=120)
    password_hash: str
    avatar_url: str | None = Field(default=None, max_length=500)
    is_platform_admin: bool = Field(default=False)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class Workspace(SQLModel, table=True):
    __tablename__ = "workspaces"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(max_length=120)
    slug: str = Field(index=True, unique=True, max_length=80)
    owner_id: str = Field(foreign_key="users.id", index=True)
    plan: str = Field(default="starter", max_length=32)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class Membership(SQLModel, table=True):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_membership"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    role: str = Field(default="member", max_length=32)  # owner/admin/member/viewer
    created_at: datetime = Field(default_factory=now_utc)


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    name: str = Field(max_length=160)
    description: str = Field(default="", max_length=4000)
    color: str = Field(default="#5B5BD6", max_length=16)
    status: str = Field(default="active", max_length=24)
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    title: str = Field(max_length=240)
    description: str = Field(default="", max_length=8000)
    status: str = Field(default="todo", max_length=24)  # backlog/todo/in_progress/review/done
    priority: str = Field(default="medium", max_length=16)
    assignee_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    reporter_id: str = Field(foreign_key="users.id", index=True)
    due_date: date | None = Field(default=None)
    labels_json: str = Field(default="[]", max_length=2000)
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class WorkPlan(SQLModel, table=True):
    """A reviewable execution plan for a task.

    Work plans are deliberately separate from a task description: a user can
    draft and revise a plan before an owner approves execution.  This is the
    durable boundary used by the UI's "Work" mode.
    """

    __tablename__ = "work_plans"
    __table_args__ = (UniqueConstraint("task_id", name="uq_work_plan_task"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    objective: str = Field(default="", max_length=8000)
    status: str = Field(default="draft", max_length=24)  # draft/approved/in_progress/completed
    created_by: str = Field(foreign_key="users.id", index=True)
    approved_by: str | None = Field(default=None, foreign_key="users.id", index=True)
    approved_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class WorkPlanStep(SQLModel, table=True):
    __tablename__ = "work_plan_steps"

    id: str = Field(default_factory=new_id, primary_key=True)
    plan_id: str = Field(foreign_key="work_plans.id", index=True)
    position: int = Field(default=0)
    title: str = Field(max_length=240)
    instructions: str = Field(default="", max_length=8000)
    status: str = Field(default="pending", max_length=24)  # pending/running/blocked/done
    assignee_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    output_summary: str = Field(default="", max_length=8000)
    updated_at: datetime = Field(default_factory=now_utc)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    owner_id: str = Field(foreign_key="users.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    title: str = Field(default="新对话", max_length=240)
    model_id: str = Field(default="gpt-4o-mini", max_length=120)
    skill_name: str = Field(default="chatbot", max_length=120)
    archived: bool = Field(default=False)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(foreign_key="conversations.id", index=True)
    role: str = Field(max_length=24)
    content: str = Field(default="", max_length=100_000)
    tool_trace_json: str = Field(default="[]", max_length=200_000)
    created_at: datetime = Field(default_factory=now_utc)


class AgentRun(SQLModel, table=True):
    """A durable, task-scoped AI execution attempt.

    Conversations are useful for exploratory chat.  A Work-mode run is
    different: it must remain tied to a governed task and preserve the model,
    requested step, output, and terminal state for later review.
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_agent_runs_workspace_idempotency_key",
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    plan_id: str | None = Field(default=None, foreign_key="work_plans.id", index=True)
    step_id: str | None = Field(default=None, foreign_key="work_plan_steps.id", index=True)
    requested_by: str = Field(foreign_key="users.id", index=True)
    model_id: str = Field(max_length=120)
    skill_name: str = Field(max_length=120)
    idempotency_key: str | None = Field(default=None, max_length=96, index=True)
    retry_of_id: str | None = Field(default=None, foreign_key="agent_runs.id", index=True)
    attempt: int = Field(default=1)
    status: str = Field(default="running", max_length=24)  # running/succeeded/failed/cancelled
    output: str = Field(default="", max_length=100_000)
    error_message: str = Field(default="", max_length=4000)
    started_at: datetime = Field(default_factory=now_utc)
    completed_at: datetime | None = Field(default=None)


class Attachment(SQLModel, table=True):
    __tablename__ = "attachments"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    uploaded_by: str = Field(foreign_key="users.id", index=True)
    task_id: str | None = Field(default=None, foreign_key="tasks.id", index=True)
    conversation_id: str | None = Field(default=None, foreign_key="conversations.id", index=True)
    original_name: str = Field(max_length=255)
    stored_name: str = Field(max_length=255, unique=True)
    content_type: str = Field(default="application/octet-stream", max_length=120)
    size_bytes: int = Field(default=0)
    extracted_text: str = Field(default="", max_length=100_000)
    created_at: datetime = Field(default_factory=now_utc)


class AuditEvent(SQLModel, table=True):
    __tablename__ = "audit_events"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str | None = Field(default=None, foreign_key="workspaces.id", index=True)
    actor_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    action: str = Field(max_length=120)
    target_type: str = Field(default="", max_length=80)
    target_id: str = Field(default="", max_length=80)
    metadata_json: str = Field(default="{}", max_length=8000)
    created_at: datetime = Field(default_factory=now_utc)


class RefreshSession(SQLModel, table=True):
    __tablename__ = "refresh_sessions"

    id: str = Field(default_factory=new_id, primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    expires_at: datetime
    revoked: bool = Field(default=False)
    created_at: datetime = Field(default_factory=now_utc)
