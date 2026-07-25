"""Add workspace-scoped operating-agent data and governance records.

Revision ID: 20260725_03
Revises: 20260725_02
Create Date: 2026-07-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260725_03"
down_revision = "20260725_02"
branch_labels = None
depends_on = None


def _id_column() -> sa.Column:
    return sa.Column("id", sa.String(length=64), nullable=False)


def upgrade() -> None:
    op.create_table(
        "business_assistants",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("agent_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=True),
        sa.Column("scope_subject_id", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "agent_type IN ('boss_private', 'personal_private', 'company_public') "
            "AND ((agent_type = 'company_public' AND owner_user_id IS NULL "
            "AND scope_subject_id = 'company') OR "
            "(agent_type IN ('boss_private', 'personal_private') "
            "AND owner_user_id IS NOT NULL "
            "AND scope_subject_id = 'user:' || owner_user_id))",
            name="ck_business_assistants_type_subject",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "agent_type",
            "scope_subject_id",
            name="uq_business_assistants_workspace_type_subject",
        ),
    )
    for column in ("workspace_id", "owner_user_id", "created_by"):
        op.create_index(f"ix_business_assistants_{column}", "business_assistants", [column])

    op.create_table(
        "business_data_sources",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("connection_mode", sa.String(length=32), nullable=False),
        sa.Column("endpoint_url", sa.String(length=1000), nullable=False),
        sa.Column("authorization_reference", sa.String(length=240), nullable=False),
        sa.Column("data_scope", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=True),
        sa.Column("ingest_token_hash", sa.String(length=128), nullable=False),
        sa.Column("ingest_token_last_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "owner_user_id", "created_by"):
        op.create_index(f"ix_business_data_sources_{column}", "business_data_sources", [column])

    op.create_table(
        "business_records",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=160), nullable=False),
        sa.Column("record_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content", sa.String(length=16000), nullable=False),
        sa.Column("payload_json", sa.String(length=50000), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingest_batch_id", sa.String(length=64), nullable=False),
        sa.Column("data_scope", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["business_data_sources.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "external_id",
            name="uq_business_records_source_external_id",
        ),
    )
    for column in (
        "workspace_id",
        "source_id",
        "occurred_on",
        "occurred_at",
        "ingest_batch_id",
        "owner_user_id",
    ):
        op.create_index(f"ix_business_records_{column}", "business_records", [column])

    op.create_table(
        "business_alert_rules",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("record_type", sa.String(length=64), nullable=False),
        sa.Column("keywords_json", sa.String(length=4000), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("data_scope", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "owner_user_id", "created_by"):
        op.create_index(f"ix_business_alert_rules_{column}", "business_alert_rules", [column])

    op.create_table(
        "business_alerts",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("record_id", sa.String(length=64), nullable=True),
        sa.Column("data_scope", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.String(length=4000), nullable=False),
        sa.Column("dedupe_key", sa.String(length=240), nullable=False),
        sa.Column("acknowledged_by", sa.String(length=64), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=64), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["rule_id"], ["business_alert_rules.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["business_data_sources.id"]),
        sa.ForeignKeyConstraint(["record_id"], ["business_records.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "dedupe_key",
            name="uq_business_alerts_workspace_dedupe_key",
        ),
    )
    for column in (
        "workspace_id",
        "rule_id",
        "source_id",
        "record_id",
        "owner_user_id",
        "acknowledged_by",
        "resolved_by",
    ):
        op.create_index(f"ix_business_alerts_{column}", "business_alerts", [column])

    op.create_table(
        "business_daily_reports",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("summary", sa.String(length=12000), nullable=False),
        sa.Column("metrics_json", sa.String(length=12000), nullable=False),
        sa.Column("generated_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["generated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "report_date",
            name="uq_business_daily_reports_workspace_date",
        ),
    )
    for column in ("workspace_id", "report_date", "generated_by"):
        op.create_index(f"ix_business_daily_reports_{column}", "business_daily_reports", [column])

    op.create_table(
        "business_boss_tasks",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.String(length=8000), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("boss_user_id", sa.String(length=64), nullable=False),
        sa.Column("assignee_id", sa.String(length=64), nullable=True),
        sa.Column("alert_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("progress_note", sa.String(length=4000), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["boss_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["alert_id"], ["business_alerts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "boss_user_id", "assignee_id", "alert_id", "created_by"):
        op.create_index(f"ix_business_boss_tasks_{column}", "business_boss_tasks", [column])

    op.create_table(
        "business_assistant_messages",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("assistant_id", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.String(length=16000), nullable=False),
        sa.Column("citations_json", sa.String(length=12000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["assistant_id"], ["business_assistants.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "assistant_id", "owner_user_id"):
        op.create_index(
            f"ix_business_assistant_messages_{column}",
            "business_assistant_messages",
            [column],
        )

    # Private operating-agent actions share the durable audit trail without
    # becoming visible in the generic workspace/platform audit lists.  The
    # server defaults legacy rows to workspace visibility.
    with op.batch_alter_table("audit_events") as batch:
        batch.add_column(
            sa.Column(
                "visibility",
                sa.String(length=32),
                nullable=False,
                server_default="workspace",
            )
        )
        batch.add_column(sa.Column("owner_user_id", sa.String(length=64), nullable=True))
        batch.create_index("ix_audit_events_owner_user_id", ["owner_user_id"])
        batch.create_foreign_key(
            "fk_audit_events_owner_user_id",
            "users",
            ["owner_user_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("fk_audit_events_owner_user_id", type_="foreignkey")
        batch.drop_index("ix_audit_events_owner_user_id")
        batch.drop_column("owner_user_id")
        batch.drop_column("visibility")
    for table in (
        "business_assistant_messages",
        "business_boss_tasks",
        "business_daily_reports",
        "business_alerts",
        "business_alert_rules",
        "business_records",
        "business_data_sources",
        "business_assistants",
    ):
        op.drop_table(table)
