"""Create the governed workspace schema.

Revision ID: 20260725_00
Revises:
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa


revision = "20260725_00"
down_revision = None
branch_labels = None
depends_on = None


def _id_column() -> sa.Column:
    return sa.Column("id", sa.String(length=64), nullable=False)


def upgrade() -> None:
    op.create_table(
        "users",
        _id_column(),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "workspaces",
        _id_column(),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])

    op.create_table(
        "memberships",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_membership"),
    )
    op.create_index("ix_memberships_workspace_id", "memberships", ["workspace_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "projects",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_workspace_id", "projects", ["workspace_id"])
    op.create_index("ix_projects_created_by", "projects", ["created_by"])

    op.create_table(
        "tasks",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.String(length=8000), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("assignee_id", sa.String(length=64), nullable=True),
        sa.Column("reporter_id", sa.String(length=64), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("labels_json", sa.String(length=2000), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "project_id", "assignee_id", "reporter_id"):
        op.create_index(f"ix_tasks_{column}", "tasks", [column])

    op.create_table(
        "work_plans",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("objective", sa.String(length=8000), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("approved_by", sa.String(length=64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_work_plan_task"),
    )
    for column in ("workspace_id", "task_id", "created_by", "approved_by"):
        op.create_index(f"ix_work_plans_{column}", "work_plans", [column])

    op.create_table(
        "work_plan_steps",
        _id_column(),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("instructions", sa.String(length=8000), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("assignee_id", sa.String(length=64), nullable=True),
        sa.Column("output_summary", sa.String(length=8000), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["work_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_plan_steps_plan_id", "work_plan_steps", ["plan_id"])
    op.create_index("ix_work_plan_steps_assignee_id", "work_plan_steps", ["assignee_id"])

    op.create_table(
        "conversations",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("skill_name", sa.String(length=120), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "owner_id", "project_id"):
        op.create_index(f"ix_conversations_{column}", "conversations", [column])

    op.create_table(
        "chat_messages",
        _id_column(),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("content", sa.String(length=100000), nullable=False),
        sa.Column("tool_trace_json", sa.String(length=200000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])

    op.create_table(
        "attachments",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("stored_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("extracted_text", sa.String(length=100000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_name"),
    )
    for column in ("workspace_id", "uploaded_by", "task_id", "conversation_id"):
        op.create_index(f"ix_attachments_{column}", "attachments", [column])
    op.create_index("ix_attachments_stored_name", "attachments", ["stored_name"], unique=True)

    op.create_table(
        "audit_events",
        _id_column(),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=80), nullable=False),
        sa.Column("metadata_json", sa.String(length=8000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_workspace_id", "audit_events", ["workspace_id"])
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])

    op.create_table(
        "refresh_sessions",
        _id_column(),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])


def downgrade() -> None:
    for table in (
        "refresh_sessions",
        "audit_events",
        "attachments",
        "chat_messages",
        "conversations",
        "work_plan_steps",
        "work_plans",
        "tasks",
        "projects",
        "memberships",
        "workspaces",
        "users",
    ):
        op.drop_table(table)
