"""知识库数据模型（RAG 语料与向量切块）。

以 workspace 为边界：文档与其切块都只属于一个工作区，检索时按工作区过滤。
Postgres 下切块另有 pgvector 原生列 ``embedding_vec``（见迁移 20260902_16/17），
由 ``core.knowledge_retrieval`` 用原始 SQL 回填与检索。
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def new_id() -> str:
    return uuid4().hex


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeBase(SQLModel, table=True):
    """知识库文档。

    支持上传文件或手动创建的文档，供智能体检索引用。
    """

    __tablename__ = "knowledge_bases"

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    title: str = Field(max_length=240)
    description: str = Field(default="", max_length=2000)
    content: str = Field(default="", max_length=100_000)
    file_name: str = Field(default="", max_length=255)
    file_type: str = Field(default="", max_length=64)
    file_size: int = Field(default=0)
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class KnowledgeChunk(SQLModel, table=True):
    """知识库文档的向量切块。

    向量以 JSON 数组持久化（不依赖 pgvector），检索时在进程内做余弦
    计算；``kb_updated_at`` 用于丢弃过期切块。
    """

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("kb_id", "chunk_index", name="uq_knowledge_chunks_kb_index"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    kb_id: str = Field(foreign_key="knowledge_bases.id", index=True)
    chunk_index: int = Field(default=0)
    content: str = Field(default="", max_length=4000)
    embedding_json: str = Field(default="[]", max_length=40000)
    model_name: str = Field(default="", max_length=120)
    kb_updated_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=now_utc)
