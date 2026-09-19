"""Recreate scheduled_jobs as generic "run the agent on a schedule" jobs.

`20260919_25` 把旧的定时调度连同汇报/经营智能体一起删了——它当时的任务类型全是
"生成那两块功能的报告"。这里按新的单一任务类型重建这张表：**定时执行智能体任务**
（提示词 + 模型 + 技能 + 运行模式，可选自建智能体人设），执行结果落成一次对话并
推送站内通知。

表在 `_25` 里已被删除，因此这里是纯粹的建表；对停在更早版本的库，迁移链会先建
旧表、再删、再按新结构建回来，最终结构一致。

Revision ID: 20260919_27
Revises: 20260919_26
Create Date: 2026-09-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260919_27"
down_revision = "20260919_26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "scheduled_jobs" in existing:
        return
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("cron", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("prompt", sa.String(length=4000), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("skill_name", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=True),
        sa.Column("mcp_servers_json", sa.String(length=2000), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=False),
        sa.Column("last_message", sa.String(length=500), nullable=False),
        sa.Column("last_conversation_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_scheduled_jobs_workspace_id"), "scheduled_jobs", ["workspace_id"], unique=False
    )
    op.create_index(
        op.f("ix_scheduled_jobs_created_by"), "scheduled_jobs", ["created_by"], unique=False
    )


def downgrade() -> None:
    """回到"没有定时任务"的状态：删表。真实数据只在 upgrade 之前存在。"""
    op.execute(sa.text('DROP TABLE IF EXISTS "scheduled_jobs"'))
