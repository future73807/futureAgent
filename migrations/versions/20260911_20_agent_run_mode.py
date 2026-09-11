"""Agent run mode and iteration evidence columns.

Revision ID: 20260911_20
Revises: 20260911_19
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260911_20"
down_revision = "20260911_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        # 历史记录没有模式概念，回填为引入模式前的等价语义 agent。
        batch.add_column(
            sa.Column(
                "agent_mode",
                sa.String(length=16),
                nullable=False,
                server_default="agent",
            )
        )
        batch.add_column(
            sa.Column("iterations_json", sa.String(length=40000), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("iterations_json")
        batch.drop_column("agent_mode")
