"""Custom agents table.

「创造模式」让用户自己拼装智能体（人设 + 模型 + 技能 + 工具）。这是一张新表，
不是往工作区偏好 JSON 里塞：智能体是列表型数据，要能单独增删改、按工作区查询、
并记录创建者，塞进 JSON 列会让每次改动都变成整列重写。

Revision ID: 20260913_23
Revises: 20260913_22
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa

revision = "20260913_23"
down_revision = "20260913_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_agents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("summary", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("persona", sa.String(length=8000), nullable=False, server_default=""),
        sa.Column("model_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("skill_name", sa.String(length=80), nullable=False, server_default="default"),
        sa.Column("mcp_servers_json", sa.String(length=2000), nullable=False, server_default="[]"),
        sa.Column("icon", sa.String(length=32), nullable=False, server_default="robot"),
        sa.Column("category", sa.String(length=40), nullable=False, server_default="自定义"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_custom_agents_workspace_id", "custom_agents", ["workspace_id"])
    op.create_index("ix_custom_agents_created_by", "custom_agents", ["created_by"])
    op.create_index("ix_custom_agents_enabled", "custom_agents", ["enabled"])
    op.create_index("ix_custom_agents_created_at", "custom_agents", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_custom_agents_created_at", table_name="custom_agents")
    op.drop_index("ix_custom_agents_enabled", table_name="custom_agents")
    op.drop_index("ix_custom_agents_created_by", table_name="custom_agents")
    op.drop_index("ix_custom_agents_workspace_id", table_name="custom_agents")
    op.drop_table("custom_agents")
