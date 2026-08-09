"""Persist bounded tool traces for governed agent runs.

Revision ID: 20260809_06
Revises: 20260809_05
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260809_06"
down_revision = "20260809_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(
            sa.Column(
                "tool_trace_json",
                sa.String(length=200_000),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("tool_trace_json")
