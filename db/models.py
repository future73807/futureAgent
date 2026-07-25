"""工作台的持久化数据模型。

所有业务数据都以 workspace 为边界，避免把演示阶段的全局数据直接暴露给所有用户。
"""
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, UniqueConstraint
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


# ---------------------------------------------------------------------------
# 经营智能体：所有表都以 workspace 为硬边界。访问控制不依赖前端传入的
# "老板/员工" 字段，而由路由根据 Workspace.owner_id、Membership 和记录的
# 私有归属在服务端判定。
# ---------------------------------------------------------------------------


class BusinessAssistant(SQLModel, table=True):
    """一个受工作区和归属用户保护的经营助手配置。

    ``boss_private`` 与 ``personal_private`` 必须带 ``owner_user_id``；
    ``company_public`` 使用固定的 ``scope_subject_id=company``。数据库约束
    配合路由层校验，避免 SQL 的 NULL 唯一性语义让多个公司助手混入同一工作区。
    """

    __tablename__ = "business_assistants"
    __table_args__ = (
        CheckConstraint(
            "agent_type IN ('boss_private', 'personal_private', 'company_public') "
            "AND ((agent_type = 'company_public' AND owner_user_id IS NULL "
            "AND scope_subject_id = 'company') OR "
            "(agent_type IN ('boss_private', 'personal_private') "
            "AND owner_user_id IS NOT NULL "
            "AND scope_subject_id = 'user:' || owner_user_id))",
            name="ck_business_assistants_type_subject",
        ),
        UniqueConstraint(
            "workspace_id",
            "agent_type",
            "scope_subject_id",
            name="uq_business_assistants_workspace_type_subject",
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    agent_type: str = Field(max_length=32)  # boss_private/personal_private/company_public
    name: str = Field(max_length=120)
    description: str = Field(default="", max_length=2000)
    owner_user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    scope_subject_id: str = Field(max_length=64)
    enabled: bool = Field(default=True)
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class BusinessDataSource(SQLModel, table=True):
    """An authorised inbound source without a plaintext credential column.

    ``ingest_token_hash`` is a one-way digest of a generated ingestion token.
    The plaintext token is returned only during create/rotation and is never
    serialised from this model or written to an audit event.
    """

    __tablename__ = "business_data_sources"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    name: str = Field(max_length=160)
    source_type: str = Field(max_length=32)  # api/webhook/file_import
    connection_mode: str = Field(default="api", max_length=32)
    endpoint_url: str = Field(default="", max_length=1000)
    authorization_reference: str = Field(default="", max_length=240)
    data_scope: str = Field(default="company", max_length=32)
    owner_user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    ingest_token_hash: str = Field(default="", max_length=128)
    ingest_token_last_rotated_at: datetime | None = Field(default=None)
    enabled: bool = Field(default=True)
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class BusinessRecord(SQLModel, table=True):
    """A normalized business record received from an authorised source."""

    __tablename__ = "business_records"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "external_id",
            name="uq_business_records_source_external_id",
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    source_id: str = Field(foreign_key="business_data_sources.id", index=True)
    external_id: str = Field(max_length=160)
    record_type: str = Field(max_length=64)
    title: str = Field(max_length=240)
    content: str = Field(default="", max_length=16000)
    payload_json: str = Field(default="{}", max_length=50000)
    occurred_on: date = Field(index=True)
    occurred_at: datetime = Field(index=True)
    ingest_batch_id: str = Field(max_length=64, index=True)
    data_scope: str = Field(default="company", max_length=32)
    owner_user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)


class BusinessAlertRule(SQLModel, table=True):
    """Keyword rules used by the deterministic MVP alert engine."""

    __tablename__ = "business_alert_rules"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    name: str = Field(max_length=160)
    record_type: str = Field(default="", max_length=64)
    keywords_json: str = Field(default="[]", max_length=4000)
    severity: str = Field(default="warning", max_length=16)
    data_scope: str = Field(default="company", max_length=32)
    owner_user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    enabled: bool = Field(default=True)
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class BusinessAlert(SQLModel, table=True):
    """A rule-triggered or manually recorded operating alert."""

    __tablename__ = "business_alerts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "dedupe_key",
            name="uq_business_alerts_workspace_dedupe_key",
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    rule_id: str | None = Field(default=None, foreign_key="business_alert_rules.id", index=True)
    source_id: str | None = Field(default=None, foreign_key="business_data_sources.id", index=True)
    record_id: str | None = Field(default=None, foreign_key="business_records.id", index=True)
    data_scope: str = Field(default="company", max_length=32)
    owner_user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    level: str = Field(default="warning", max_length=16)
    status: str = Field(default="open", max_length=16)  # open/acknowledged/resolved
    title: str = Field(max_length=240)
    summary: str = Field(default="", max_length=4000)
    dedupe_key: str = Field(max_length=240)
    acknowledged_by: str | None = Field(default=None, foreign_key="users.id", index=True)
    acknowledged_at: datetime | None = Field(default=None)
    resolved_by: str | None = Field(default=None, foreign_key="users.id", index=True)
    resolved_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class BusinessDailyReport(SQLModel, table=True):
    """A deterministic, date-scoped production report generated from records."""

    __tablename__ = "business_daily_reports"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "report_date",
            name="uq_business_daily_reports_workspace_date",
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    report_date: date = Field(index=True)
    summary: str = Field(default="", max_length=12000)
    metrics_json: str = Field(default="{}", max_length=12000)
    generated_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class BusinessBossTask(SQLModel, table=True):
    """A boss-issued follow-up task visible only to the boss and assignee."""

    __tablename__ = "business_boss_tasks"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    title: str = Field(max_length=240)
    description: str = Field(default="", max_length=8000)
    status: str = Field(default="todo", max_length=24)
    priority: str = Field(default="medium", max_length=16)
    boss_user_id: str = Field(foreign_key="users.id", index=True)
    assignee_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    alert_id: str | None = Field(default=None, foreign_key="business_alerts.id", index=True)
    created_by: str = Field(foreign_key="users.id", index=True)
    progress_note: str = Field(default="", max_length=4000)
    due_date: date | None = Field(default=None)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class BusinessAssistantMessage(SQLModel, table=True):
    """Private per-user assistant conversation messages, never workspace-wide."""

    __tablename__ = "business_assistant_messages"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    assistant_id: str = Field(foreign_key="business_assistants.id", index=True)
    owner_user_id: str = Field(foreign_key="users.id", index=True)
    role: str = Field(max_length=16)  # user/assistant
    content: str = Field(default="", max_length=16000)
    citations_json: str = Field(default="[]", max_length=12000)
    created_at: datetime = Field(default_factory=now_utc)


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
    # ``private`` events are visible only to ``owner_user_id``.  Existing
    # workspace events retain the default and are compatible with the older
    # audit table schema after migration 20260725_03.
    visibility: str = Field(default="workspace", max_length=32)
    owner_user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)


class RefreshSession(SQLModel, table=True):
    __tablename__ = "refresh_sessions"

    id: str = Field(default_factory=new_id, primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    expires_at: datetime
    revoked: bool = Field(default=False)
    created_at: datetime = Field(default_factory=now_utc)
