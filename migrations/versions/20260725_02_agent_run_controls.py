"""Add idempotency and retry lineage to governed agent runs.

Revision ID: 20260725_02
Revises: 20260725_01
Create Date: 2026-07-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260725_02"
down_revision = "20260725_01"
branch_labels = None
depends_on = None


def _agent_runs_before_controls() -> sa.Table:
    """batch 重建前的 agent_runs 真实结构（迁移 20260725_01 建出来的样子）。

    不给 copy_from 时 alembic 会「反射现表 + 拿当前模型元数据算列序提示」；
    模型一演进（任何一张表加列），这份提示就可能与反射结果构成环，SQLite 上
    重建 agent_runs 直接抛 CircularDependencyError——全新库跑 alembic 链、
    以及没有版本表的老库自愈升级都会因此失败，而报错指向的却是本文件里
    三条列。把当时的结构写死，这条迁移就与「此刻的模型长什么样」解耦。
    """
    metadata = sa.MetaData()
    return sa.Table(
        "agent_runs",
        metadata,
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=True),
        sa.Column("step_id", sa.String(length=64), nullable=True),
        sa.Column("requested_by", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("skill_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("output", sa.String(length=100000), nullable=False),
        sa.Column("error_message", sa.String(length=4000), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # 重建时必须一并带回这些索引，否则 batch 会把它们丢掉。
        sa.Index("ix_agent_runs_workspace_id", "workspace_id"),
        sa.Index("ix_agent_runs_task_id", "task_id"),
        sa.Index("ix_agent_runs_plan_id", "plan_id"),
        sa.Index("ix_agent_runs_step_id", "step_id"),
        sa.Index("ix_agent_runs_requested_by", "requested_by"),
    )


def upgrade() -> None:
    # Batch mode keeps fresh SQLite test databases and PostgreSQL upgrades on
    # the same migration path; SQLite cannot add a foreign key in place.
    with op.batch_alter_table("agent_runs", copy_from=_agent_runs_before_controls()) as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(length=96), nullable=True))
        batch.add_column(sa.Column("retry_of_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"))
        batch.create_index("ix_agent_runs_idempotency_key", ["idempotency_key"])
        batch.create_index("ix_agent_runs_retry_of_id", ["retry_of_id"])
        batch.create_foreign_key("fk_agent_runs_retry_of_id", "agent_runs", ["retry_of_id"], ["id"])
        batch.create_unique_constraint(
            "uq_agent_runs_workspace_idempotency_key",
            ["workspace_id", "idempotency_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("uq_agent_runs_workspace_idempotency_key", type_="unique")
        batch.drop_constraint("fk_agent_runs_retry_of_id", type_="foreignkey")
        batch.drop_index("ix_agent_runs_retry_of_id")
        batch.drop_index("ix_agent_runs_idempotency_key")
        batch.drop_column("attempt")
        batch.drop_column("retry_of_id")
        batch.drop_column("idempotency_key")
