"""Knowledge vector chunks table.

Revision ID: 20260902_14
Revises: 20260902_13
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_14"
down_revision = "20260902_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False, index=True),
        sa.Column("kb_id", sa.String(), sa.ForeignKey("knowledge_bases.id"), nullable=False, index=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(length=4000), nullable=False),
        sa.Column("embedding_json", sa.String(length=40000), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("kb_updated_at", sa.DateTime(), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("kb_id", "chunk_index", name="uq_knowledge_chunks_kb_index"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
