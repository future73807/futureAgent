"""Workspace permission mode column.

Revision ID: 20260911_19
Revises: 20260911_18
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260911_19"
down_revision = "20260911_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 现有工作区一律落在最严格档位，升级本身不得放宽任何审批要求。
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(
            sa.Column(
                "permission_mode",
                sa.String(length=16),
                nullable=False,
                server_default="default",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("permission_mode")
