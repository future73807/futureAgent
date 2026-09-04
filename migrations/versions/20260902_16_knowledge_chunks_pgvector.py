"""pgvector native column for knowledge chunks.

PostgreSQL only: enables the vector extension, adds ``embedding_vec``
and backfills it from the JSON column.  SQLite environments skip this
migration entirely and keep the in-process cosine path.

Revision ID: 20260902_16
Revises: 20260902_15
Create Date: 2026-09-03
"""

from alembic import op


revision = "20260902_16"
down_revision = "20260902_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    bind.execute(text("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding_vec vector"))
    # 从 JSON 列回填向量；JSON 解析失败（理论不应发生）的行保持 NULL
    bind.execute(text(
        """
        UPDATE knowledge_chunks
        SET embedding_vec = CAST(embedding_json AS vector)
        WHERE embedding_vec IS NULL AND embedding_json LIKE '[%]'
        """
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    bind.execute(text("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding_vec"))
