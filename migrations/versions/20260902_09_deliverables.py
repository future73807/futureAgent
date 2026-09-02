"""Deliverables table for agent-produced artifacts.

Revision ID: 20260902_09
Revises: 20260902_08
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_09"
down_revision = "20260902_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deliverables",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False, index=True),
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=True, index=True),
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=True, index=True),
        sa.Column("agent_run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=True, index=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source_path", sa.String(length=500), nullable=False),
        sa.Column("stored_name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("registered_by", sa.String(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("deliverables")
