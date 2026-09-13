"""Workspace preferences column.

设置面板里的开关（规则与记忆、浏览器、自动化任务权限档位、已安装插件）原先
没有任何落库位置。放进工作区表的一列 JSON，而不是拆成多张表：它们都是
"每工作区一份、随设置面板整体读写"的偏好，拆表只会把一次读写变成 N 次查询。

Revision ID: 20260913_22
Revises: 20260912_21
Create Date: 2026-09-13
"""

from alembic import op
import sqlalchemy as sa


revision = "20260913_22"
down_revision = "20260912_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        # 存量工作区回填 "{}"，读取侧对空值和坏 JSON 都按默认值处理。
        batch.add_column(
            sa.Column(
                "preferences_json",
                sa.String(length=20000),
                nullable=False,
                server_default="{}",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("preferences_json")
