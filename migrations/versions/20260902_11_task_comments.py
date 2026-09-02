"""Task comments table.

Revision ID: 20260902_11
Revises: 20260902_10
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_11"
down_revision = "20260902_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_comments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False, index=True),
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=False, index=True),
        sa.Column("author_id", sa.String(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("content", sa.String(length=4000), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("task_comments")
