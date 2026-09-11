"""Usage records for real provider-reported token accounting.

Revision ID: 20260911_18
Revises: 20260902_17
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260911_18"
down_revision = "20260902_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("skill_name", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False, index=True),
        # 运行模式与子代理阶段直接填充，建表时即存在以免重复迁移本表。
        sa.Column("agent_mode", sa.String(length=16), nullable=False),
        sa.Column("parent_run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=True, index=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("llm_calls", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    # 汇总接口的两条主查询路径：按时间窗与按模型分组。
    op.create_index(
        "ix_usage_records_workspace_created",
        "usage_records",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_usage_records_workspace_model",
        "usage_records",
        ["workspace_id", "model_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_records_workspace_model", table_name="usage_records")
    op.drop_index("ix_usage_records_workspace_created", table_name="usage_records")
    op.drop_table("usage_records")
