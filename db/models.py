"""工作台的持久化数据模型。

所有业务数据都以 workspace 为边界，避免把演示阶段的全局数据直接暴露给所有用户。
"""
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import Index, UniqueConstraint
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
    # 审批与工具广度档位：default（计划必须人工批准）/ auto_approve
    # （保存即批准）/ full_access（自动批准且跳过步骤级复核）。
    # 它只放宽人工审批环节，不影响 Casbin RBAC、租户目录隔离与
    # run_python 的永久禁用；单次请求只能在此基准上向下收紧。
    permission_mode: str = Field(default="default", max_length=16)
    # 工作区级偏好（JSON 字符串）。放一列而不是建多张表：这些都是"每工作区
    # 一份、随设置面板整体读写"的开关，拆表只会让读写变成 N 次查询。
    # 见 api/routes.py 的 WorkspacePreferencesRequest，字段在那里做白名单校验。
    preferences_json: str = Field(default="{}", max_length=20000)
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
    # 归档：默认不出现在列表/看板，但计划、执行记录与评论都留着，可随时恢复。
    archived: bool = Field(default=False)
    archived_at: datetime | None = Field(default=None)
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
    model_id: str = Field(default="glm-5.3-flash", max_length=120)
    skill_name: str = Field(default="chatbot", max_length=120)
    archived: bool = Field(default=False)
    # 滚动摘要：长对话按阈值压缩为要点，替代无限平铺历史。
    summary: str = Field(default="", max_length=8000)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(foreign_key="conversations.id", index=True)
    role: str = Field(max_length=24)
    content: str = Field(default="", max_length=100_000)
    tool_trace_json: str = Field(default="[]", max_length=200_000)
    # 对话即工作台：助手消息需要携带自己的执行上下文，才能在前端
    # 就地渲染模式标记、真实用量与 goal/loop 轮次判定，而不是只留一段文本。
    agent_mode: str = Field(default="agent", max_length=16)
    usage_json: str | None = Field(default=None, max_length=4000)
    iterations_json: str | None = Field(default=None, max_length=40_000)
    created_at: datetime = Field(default_factory=now_utc)


class AgentRunBatch(SQLModel, table=True):
    """一次并行编排的批次记录：终态与各结果计数，供历史查看。

    ``id`` 即 agent_runs.batch_id，两表通过该键关联。
    status: running / succeeded（全部成功）/ partial（部分失败）/ failed
    （全部失败）/ cancelled（被人工取消）。
    """

    __tablename__ = "agent_run_batches"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    plan_id: str | None = Field(default=None, foreign_key="work_plans.id", index=True)
    total_steps: int = Field(default=0)
    succeeded_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    cancelled_count: int = Field(default=0)
    status: str = Field(default="running", max_length=16)
    model_id: str = Field(max_length=120)
    skill_name: str = Field(max_length=120)
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    finished_at: datetime | None = Field(default=None)


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
    # 运行模式必须随 run 保存，否则重试无法复现原来的执行语义
    # （与 mcp_servers_json 的持久化理由一致）。
    agent_mode: str = Field(default="agent", max_length=16)
    # 监督模式（goal/loop）的轮次判定证据；非监督模式为空列表。
    iterations_json: str | None = Field(default=None, max_length=40_000)
    # NULL marks executions created before MCP selection was persisted.  New
    # runs always write a JSON list, including an explicit empty list.
    mcp_servers_json: str | None = Field(default=None, max_length=4000)
    # 同一批并行编排执行的批次标识；单独执行的 run 为空。用于整批跟踪与批量取消。
    batch_id: str | None = Field(default=None, max_length=64, index=True)
    # As with MCP selection, NULL distinguishes historical runs from a new run
    # that completed without calling a tool (stored as an explicit ``[]``).
    # Each trace entry is bounded before persistence so provider/tool output
    # cannot grow the row without limit.
    tool_trace_json: str | None = Field(default=None, max_length=200_000)
    idempotency_key: str | None = Field(default=None, max_length=96, index=True)
    retry_of_id: str | None = Field(default=None, foreign_key="agent_runs.id", index=True)
    attempt: int = Field(default=1)
    status: str = Field(default="running", max_length=24)  # running/succeeded/failed/cancelled
    output: str = Field(default="", max_length=100_000)
    error_message: str = Field(default="", max_length=4000)
    started_at: datetime = Field(default_factory=now_utc)
    completed_at: datetime | None = Field(default=None)


class UsageRecord(SQLModel, table=True):
    """一次 AI 调用的真实用量快照，对话与工作模式执行统一写入本表。

    数值只来自模型返回的 usage_metadata。提供方未上报时保持 0 且
    ``llm_calls`` 不递增，避免把“没有计量”伪装成“零消耗”。

    ``agent_mode`` 与 ``parent_run_id`` 在建表时就存在，供运行模式与子代理
    阶段直接填充，不再对同一张表重复做迁移。
    """

    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_records_workspace_created", "workspace_id", "created_at"),
        Index("ix_usage_records_workspace_model", "workspace_id", "model_id"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    model_id: str = Field(max_length=120)
    skill_name: str = Field(default="", max_length=120)
    source: str = Field(default="chat", max_length=16)  # chat/agent_run
    # 对话写 conversation_id，工作模式写 agent_run_id。
    source_id: str = Field(default="", max_length=64, index=True)
    agent_mode: str = Field(default="chat", max_length=16)
    parent_run_id: str | None = Field(
        default=None, foreign_key="agent_runs.id", index=True
    )
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    llm_calls: int = Field(default=0)
    tool_calls: int = Field(default=0)
    duration_ms: int = Field(default=0)
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


class Notification(SQLModel, table=True):
    """站内通知：始终定向到单个用户，避免广播越权。"""

    __tablename__ = "notifications"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    type: str = Field(default="system", max_length=24)  # task/plan/run/alert/system
    title: str = Field(max_length=240)
    body: str = Field(default="", max_length=4000)
    link: str = Field(default="", max_length=40)  # 用户端导航 key：board/work/chat/knowledge
    ref_id: str = Field(default="", max_length=80)
    read_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=now_utc, index=True)


class CustomAgent(SQLModel, table=True):
    """用户在工作区里自建的智能体。

    与 ``BusinessAssistant`` 的区别：后者是产品预置的三个固定角色，带
    "老板私聊 / 公事数据"这类数据隔离语义，受数据库约束保护；这里的是用户
    用一句人设 + 模型 + 技能 + 工具自己拼出来的助手，本质是**一组可复用的
    运行预设**——它不引入新的数据边界，权限仍然完全由发起人自己的身份决定。

    人设只影响提示词，不会放宽任何工具授权：``mcp_servers_json`` 里的服务
    在真正执行时仍要过工作区授权档位与工具白名单。
    """

    __tablename__ = "custom_agents"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    created_by: str = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=60)
    summary: str = Field(default="", max_length=200)
    # 人设 / 系统提示词。上限对齐 core/workspace_context.py 的指令长度。
    persona: str = Field(default="", max_length=8000)
    model_id: str = Field(default="", max_length=120)
    skill_name: str = Field(default="default", max_length=80)
    mcp_servers_json: str = Field(default="[]", max_length=2000)
    # 图标用一组固定 key（robot / chart / doc / code / shield / spark），
    # 前端映射成图标组件；存组件名会让前端换图标库时整批数据失效。
    icon: str = Field(default="robot", max_length=32)
    category: str = Field(default="自定义", max_length=40)
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=now_utc, index=True)
    updated_at: datetime = Field(default_factory=now_utc)


class ScheduledJob(SQLModel, table=True):
    """工作区级定时任务：按 cron 到点让智能体跑一次提示词。

    任务本身不携带任何权限，也不代表某个人的身份：执行时用的是发起人的身份与
    工作区最严格的权限档（不自动批准、不自动完成步骤），需要人工决策的动作仍会
    留在工作模式里等人处理。每次执行产出一个新对话，并把结果推送成站内通知。
    """

    __tablename__ = "scheduled_jobs"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    name: str = Field(max_length=120)
    # 目前只有 agent_task 一种；保留这一列是为了让"以后再加任务类型"不必改表。
    job_type: str = Field(default="agent_task", max_length=32)
    cron: str = Field(max_length=64)
    enabled: bool = Field(default=True)
    prompt: str = Field(default="", max_length=4000)
    model_id: str = Field(default="", max_length=120)
    skill_name: str = Field(default="chatbot", max_length=120)
    mode: str = Field(default="chat", max_length=16)  # chat/plan/agent/goal/loop
    agent_id: str | None = Field(default=None, max_length=64)  # 自建智能体预设
    mcp_servers_json: str = Field(default="[]", max_length=2000)
    last_run_at: datetime | None = Field(default=None)
    last_status: str = Field(default="", max_length=16)  # ok/failed
    last_message: str = Field(default="", max_length=500)
    last_conversation_id: str | None = Field(default=None, max_length=64)
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class NotificationTarget(SQLModel, table=True):
    """工作区级通知出口：普通 Webhook 或企业微信/飞书/钉钉群机器人。"""

    __tablename__ = "notification_targets"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    name: str = Field(max_length=120)
    kind: str = Field(default="webhook", max_length=24)  # webhook/wecom/feishu/dingtalk
    url: str = Field(max_length=1000)
    enabled: bool = Field(default=True)
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class Deliverable(SQLModel, table=True):
    """AI 产出或工作区文件登记后的交付物，可下载、可挂到任务/对话。"""

    __tablename__ = "deliverables"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    task_id: str | None = Field(default=None, foreign_key="tasks.id", index=True)
    conversation_id: str | None = Field(default=None, foreign_key="conversations.id", index=True)
    agent_run_id: str | None = Field(default=None, foreign_key="agent_runs.id", index=True)
    name: str = Field(max_length=255)
    kind: str = Field(default="file", max_length=16)  # xlsx/docx/chart/image/pdf/file
    source_path: str = Field(default="", max_length=500)
    stored_name: str = Field(max_length=255, unique=True)
    content_type: str = Field(default="application/octet-stream", max_length=120)
    size_bytes: int = Field(default=0)
    registered_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)


class TaskComment(SQLModel, table=True):
    """任务评论：协作讨论留在任务上，并写入工作区边界。"""

    __tablename__ = "task_comments"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    author_id: str = Field(foreign_key="users.id", index=True)
    content: str = Field(max_length=4000)
    created_at: datetime = Field(default_factory=now_utc)
