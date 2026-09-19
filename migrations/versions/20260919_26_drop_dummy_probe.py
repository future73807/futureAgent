"""Drop the stray dummy_probe columns.

``tasks.dummy_probe`` 与 ``conversations.dummy_probe`` 是模型里遗留的调试列：
没有任何迁移创建过它们，但 ``SQLModel.metadata`` 一直声明着它们。后果是
``_matches_schema`` 永远认为"结构落后于模型"——每次启动都打一条假的缺列错误，
无版本旧库也认不出"其实已经是当前结构"，只能退回更早的阶梯版本重放迁移。

只有用 ``create_all`` 建出来的库（空库首次启动的本地环境）真正有这两列，
有版本号的库根本没有；所以这里按列是否存在来决定是否重建表。

Revision ID: 20260919_26
Revises: 20260919_25
Create Date: 2026-09-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260919_26"
down_revision = "20260919_25"
branch_labels = None
depends_on = None

STRAY_COLUMN = "dummy_probe"
AFFECTED_TABLES = ("tasks", "conversations")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in AFFECTED_TABLES:
        columns = {column["name"] for column in inspector.get_columns(table)}
        if STRAY_COLUMN not in columns:
            continue
        # batch 模式：SQLite 不支持直接 DROP COLUMN，需要重建表。
        with op.batch_alter_table(table) as batch:
            batch.drop_column(STRAY_COLUMN)


def downgrade() -> None:
    """不恢复：这一列不属于任何功能，重建它只会让结构判定再次失真。"""
