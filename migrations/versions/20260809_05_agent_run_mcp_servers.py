"""Persist MCP server selection for governed agent runs.

Revision ID: 20260809_05
Revises: 20260726_04
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260809_05"
down_revision = "20260726_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(
            sa.Column(
                "mcp_servers_json",
                sa.String(length=4000),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("mcp_servers_json")
