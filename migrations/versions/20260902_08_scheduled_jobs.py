"""Scheduled automation jobs table.

Revision ID: 20260902_08
Revises: 20260902_07
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_08"
down_revision = "20260902_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False, index=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("cron", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("payload_json", sa.String(length=4000), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=False),
        sa.Column("last_message", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("scheduled_jobs")
