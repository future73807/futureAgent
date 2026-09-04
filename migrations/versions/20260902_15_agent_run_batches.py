"""Parallel batch history table.

Revision ID: 20260902_15
Revises: 20260902_14
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_15"
down_revision = "20260902_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_run_batches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False, index=True),
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=False, index=True),
        sa.Column("plan_id", sa.String(), sa.ForeignKey("work_plans.id"), nullable=True, index=True),
        sa.Column("total_steps", sa.Integer(), nullable=False),
        sa.Column("succeeded_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("cancelled_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("skill_name", sa.String(length=120), nullable=False),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("agent_run_batches")
