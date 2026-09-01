"""Notification center tables.

Revision ID: 20260902_07
Revises: 20260809_06
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_07"
down_revision = "20260809_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("type", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body", sa.String(length=4000), nullable=False),
        sa.Column("link", sa.String(length=40), nullable=False),
        sa.Column("ref_id", sa.String(length=80), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )
    op.create_table(
        "notification_targets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False, index=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notification_targets")
    op.drop_table("notifications")
