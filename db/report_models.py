"""汇报智能体数据模型。

所有业务数据都以 workspace 为边界，支持知识库、文件和接口的输入和对接。
"""
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel


def new_id() -> str:
    return uuid4().hex


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ReportAssistant(SQLModel, table=True):
    """汇报智能体配置。
    
    每个工作区只有一个汇报智能体，所有成员都可以使用。
    数据按工作区隔离，成员只能读取本工作区已授权的数据。
    """

    __tablename__ = "report_assistants"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            name="uq_report_assistants_workspace",
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    name: str = Field(max_length=120, default="汇报智能体")
    description: str = Field(default="", max_length=2000)
    enabled: bool = Field(default=True)
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ReportDataSource(SQLModel, table=True):
    """已授权的数据源。

    ``ingest_token_hash`` 是生成的接入令牌的单向摘要。
    明文令牌仅在创建/轮换时返回，不会序列化到模型或审计事件中。
    """

    __tablename__ = "report_data_sources"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    name: str = Field(max_length=160)
    source_type: str = Field(max_length=32)  # api/webhook/file_import/oa/mini_program/production_report/enterprise_robot/custom_api
    connection_mode: str = Field(default="api", max_length=32)
    endpoint_url: str = Field(default="", max_length=1000)
    authorization_reference: str = Field(default="", max_length=240)
    ingest_token_hash: str = Field(default="", max_length=128)
    ingest_token_last_rotated_at: datetime | None = Field(default=None)
    enabled: bool = Field(default=True)
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ReportRecord(SQLModel, table=True):
    """从已授权源接收的标准化业务记录。"""

    __tablename__ = "report_records"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "external_id",
            name="uq_report_records_source_external_id",
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    source_id: str = Field(foreign_key="report_data_sources.id", index=True)
    external_id: str = Field(max_length=160)
    record_type: str = Field(max_length=64)
    title: str = Field(max_length=240)
    content: str = Field(default="", max_length=16000)
    payload_json: str = Field(default="{}", max_length=50000)
    occurred_on: date = Field(index=True)
    occurred_at: datetime = Field(index=True)
    ingest_batch_id: str = Field(max_length=64, index=True)
    created_at: datetime = Field(default_factory=now_utc)


class KnowledgeBase(SQLModel, table=True):
    """知识库文档。

    支持上传文件或手动创建的文档，供汇报智能体引用。
    """

    __tablename__ = "knowledge_bases"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    title: str = Field(max_length=240)
    description: str = Field(default="", max_length=2000)
    content: str = Field(default="", max_length=100_000)
    file_name: str = Field(default="", max_length=255)
    file_type: str = Field(default="", max_length=64)
    file_size: int = Field(default=0)
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ReportAlertRule(SQLModel, table=True):
    """预警规则引擎使用的关键字规则。"""

    __tablename__ = "report_alert_rules"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    name: str = Field(max_length=160)
    record_type: str = Field(default="", max_length=64)
    keywords_json: str = Field(default="[]", max_length=4000)
    severity: str = Field(default="warning", max_length=16)
    enabled: bool = Field(default=True)
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ReportAlert(SQLModel, table=True):
    """规则触发或手动记录的经营预警。"""

    __tablename__ = "report_alerts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "dedupe_key",
            name="uq_report_alerts_workspace_dedupe_key",
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    rule_id: str | None = Field(default=None, foreign_key="report_alert_rules.id", index=True)
    source_id: str | None = Field(default=None, foreign_key="report_data_sources.id", index=True)
    record_id: str | None = Field(default=None, foreign_key="report_records.id", index=True)
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


class ReportDailyReport(SQLModel, table=True):
    """按日期范围生成的生产日报。"""

    __tablename__ = "report_daily_reports"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "report_date",
            name="uq_report_daily_reports_workspace_date",
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


class ReportWeeklyReport(SQLModel, table=True):
    """按周生成的总结报告。"""

    __tablename__ = "report_weekly_reports"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "week_start_date",
            name="uq_report_weekly_reports_workspace_week",
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    week_start_date: date = Field(index=True)
    week_end_date: date = Field(index=True)
    title: str = Field(max_length=240)
    summary: str = Field(default="", max_length=12000)
    metrics_json: str = Field(default="{}", max_length=12000)
    generated_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ReportAssistantMessage(SQLModel, table=True):
    """汇报智能体对话消息。"""

    __tablename__ = "report_assistant_messages"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    role: str = Field(max_length=16)  # user/assistant
    content: str = Field(default="", max_length=16000)
    citations_json: str = Field(default="[]", max_length=12000)
    created_at: datetime = Field(default_factory=now_utc)
