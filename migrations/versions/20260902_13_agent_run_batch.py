"""Batch id for parallel plan execution.

Revision ID: 20260902_13
Revises: 20260902_12
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_13"
down_revision = "20260902_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("batch_id", sa.String(length=64), nullable=True))
        batch.create_index("ix_agent_runs_batch_id", ["batch_id"])


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_index("ix_agent_runs_batch_id")
        batch.drop_column("batch_id")
