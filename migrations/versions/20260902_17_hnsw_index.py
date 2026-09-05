"""HNSW vector index for knowledge chunks (PostgreSQL only).

pgvector 的 HNSW 索引要求列带固定维度：本迁移先把 ``embedding_vec``
调整为 ``vector(EMBEDDING_DIM)``（维度来自配置，默认 1024 对应
qwen3-embedding），再创建余弦距离的 HNSW 索引。SQLite 环境整个跳过，
保持 JSON + 进程内余弦的降级路径。

更换 embedding 模型导致维度变化时：更新 EMBEDDING_DIM 后，对任一知识
库文档执行更新即可触发重切块与回填（旧维度行会在回填时统一重写）。

Revision ID: 20260902_17
Revises: 20260902_16
Create Date: 2026-09-03
"""

from alembic import op


revision = "20260902_17"
down_revision = "20260902_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from config import settings
    from sqlalchemy import text

    dim = max(1, int(settings.embedding_dim))
    m = max(2, int(settings.hnsw_m))
    ef_construction = max(1, int(settings.hnsw_ef_construction))
    index_name = "ix_knowledge_chunks_embedding_vec_hnsw"
    bind.execute(text(f"ALTER TABLE knowledge_chunks ALTER COLUMN embedding_vec TYPE vector({dim})"))
    bind.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
    bind.execute(text(
        f"CREATE INDEX IF NOT EXISTS {index_name} "
        f"ON knowledge_chunks USING hnsw (embedding_vec vector_cosine_ops) "
        f"WITH (m = {m}, ef_construction = {ef_construction})"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    bind.execute(text("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_vec_hnsw"))
    bind.execute(text("ALTER TABLE knowledge_chunks ALTER COLUMN embedding_vec TYPE vector"))
