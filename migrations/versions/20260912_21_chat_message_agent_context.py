"""Chat message agent context columns.

对话即工作台改造：助手消息需要携带运行模式、真实用量与监督模式的轮次
判定，前端才能在消息流里就地渲染结构化卡片。

Revision ID: 20260912_21
Revises: 20260911_20
Create Date: 2026-09-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260912_21"
down_revision = "20260911_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        # 历史消息没有模式概念，回填为引入模式前的等价语义 agent。
        batch.add_column(
            sa.Column(
                "agent_mode",
                sa.String(length=16),
                nullable=False,
                server_default="agent",
            )
        )
        batch.add_column(sa.Column("usage_json", sa.String(length=4000), nullable=True))
        batch.add_column(
            sa.Column("iterations_json", sa.String(length=40000), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_column("iterations_json")
        batch.drop_column("usage_json")
        batch.drop_column("agent_mode")
