"""Conversation rolling summary column.

Revision ID: 20260902_10
Revises: 20260902_09
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_10"
down_revision = "20260902_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("summary", sa.String(length=8000), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("summary")
