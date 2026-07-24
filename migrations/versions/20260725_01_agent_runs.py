"""Add durable, reviewable task-level AI execution records.

Revision ID: 20260725_01
Revises: 20260725_00
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa


revision = "20260725_01"
down_revision = "20260725_00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=True),
        sa.Column("step_id", sa.String(length=64), nullable=True),
        sa.Column("requested_by", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("skill_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("output", sa.String(length=100000), nullable=False),
        sa.Column("error_message", sa.String(length=4000), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["work_plans.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["step_id"], ["work_plan_steps.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "task_id", "plan_id", "step_id", "requested_by"):
        op.create_index(f"ix_agent_runs_{column}", "agent_runs", [column])


def downgrade() -> None:
    op.drop_table("agent_runs")
