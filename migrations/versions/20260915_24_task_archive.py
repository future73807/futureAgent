"""Task archive columns.

工作项原先只能一直挂在看板上：验收、历史任务越积越多，而删除会连带执行记录
与审计线索，不该是默认动作。这里加归档位——归档项默认不出现在列表与看板，
但计划、执行记录、评论都留在库里，随时可以恢复。

Revision ID: 20260915_24
Revises: 20260913_23
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260915_24"
down_revision = "20260913_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        # 存量任务回填 false（未归档），读取侧对 NULL 也按未归档处理。
        batch.add_column(
            sa.Column(
                "archived",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("archived_at")
        batch.drop_column("archived")
