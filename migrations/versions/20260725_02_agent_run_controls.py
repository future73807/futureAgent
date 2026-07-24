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


def upgrade() -> None:
    # Batch mode keeps fresh SQLite test databases and PostgreSQL upgrades on
    # the same migration path; SQLite cannot add a foreign key in place.
    with op.batch_alter_table("agent_runs") as batch:
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
