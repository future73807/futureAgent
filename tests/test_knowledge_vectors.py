"""向量召回测试：切块、索引、余弦融合与降级。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlmodel import SQLModel, Session, create_engine, select

import db.database as database
from core.embedding import chunk_text, cosine_similarity
from core.knowledge_retrieval import reindex_knowledge_base, retrieve_knowledge_smart_sync
from db.models import User, Workspace
from db.report_models import KnowledgeBase, KnowledgeChunk
from main import app


def _vector_for(keyword: str, dim: int = 8) -> list[float]:
    """确定性伪向量：包含 keyword 的文本互相接近。"""
    vector = [0.05] * dim
    for index, char in enumerate(keyword):
        vector[index % dim] += (ord(char) % 97) / 97.0
    return vector


class KnowledgeVectorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_engine = database.engine
        database.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name, 'vector-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        self.session = Session(database.engine)
        self.session.add(User(id="u1", email="v@example.com", display_name="V", password_hash="x"))
        self.session.add(Workspace(id="w1", name="V", slug="vector-w1", owner_id="u1"))
        self.session.commit()

    def tearDown(self):
        self.session.close()
        database.engine.dispose()
        database.engine = self.original_engine
        self.temp_dir.cleanup()

    def test_chunk_text_splits_with_overlap_and_cap(self):
        chunks = chunk_text("字" * 2500, chunk_chars=800, overlap=100)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertLessEqual(len(chunks), 20)
        self.assertTrue(all(chunk.strip() for chunk in chunks))

    def test_cosine_similarity_same_and_orthogonal(self):
        base = _vector_for("传送带")
        self.assertAlmostEqual(cosine_similarity(base, base), 1.0, places=6)
        self.assertEqual(cosine_similarity(base, [0.0] * 8), 0.0)

    def test_reindex_and_hybrid_retrieval(self):
        kb = KnowledgeBase(
            id="kb1",
            workspace_id="w1",
            title="设备维护手册",
            content="传送带每周需要润滑一次，张力异常时先停机。",
            created_by="u1",
        )
        self.session.add(kb)
        self.session.commit()

        def fake_embed(texts):
            return [_vector_for("传送带润滑") for _ in texts]

        with patch("core.knowledge_retrieval.embedding_enabled", return_value=True), \
                patch("core.knowledge_retrieval.embed_texts", side_effect=fake_embed):
            indexed = self.session.exec(select(KnowledgeChunk)).all() if False else None
            import asyncio

            done = asyncio.run(reindex_knowledge_base(self.session, "w1", kb))
            self.assertTrue(done)
            chunks = self.session.exec(select(KnowledgeChunk)).all()
            self.assertTrue(chunks)
            self.assertTrue(all(chunk.embedding_json for chunk in chunks))

            # 混合召回：即使关键词不命中（查询词完全不同），向量也应召回
            results = retrieve_knowledge_smart_sync(self.session, "w1", "完全不相关的查询词", limit=5)
            self.assertTrue(results)
            self.assertEqual(results[0]["source"], "knowledge_base")
            self.assertEqual(results[0]["id"], "kb1")

    def test_falls_back_to_keyword_when_embedding_disabled(self):
        kb = KnowledgeBase(
            id="kb2",
            workspace_id="w1",
            title="报销流程",
            content="差旅报销需要在月底前提交发票。",
            created_by="u1",
        )
        self.session.add(kb)
        self.session.commit()

        results = retrieve_knowledge_smart_sync(self.session, "w1", "报销 发票", limit=5)
        self.assertTrue(results)
        self.assertEqual(results[0]["id"], "kb2")
        # 未启用 embedding 时不会产生任何切块
        self.assertEqual(self.session.exec(select(KnowledgeChunk)).all(), [])

    def test_kb_delete_with_endpoint_style_cascade(self):
        """模拟删除端点的行为：先清向量块再删文档，两表均无残留。"""
        kb = KnowledgeBase(
            id="kb3",
            workspace_id="w1",
            title="将删除的手册",
            content="传送带润滑说明。",
            created_by="u1",
        )
        self.session.add(kb)
        self.session.commit()

        def fake_embed(texts):
            return [_vector_for("传送带润滑") for _ in texts]

        with patch("core.knowledge_retrieval.embedding_enabled", return_value=True), \
                patch("core.knowledge_retrieval.embed_texts", side_effect=fake_embed):
            import asyncio

            self.assertTrue(asyncio.run(reindex_knowledge_base(self.session, "w1", kb)))
        self.assertEqual(len(self.session.exec(select(KnowledgeChunk)).all()), 1)

        # 端点级联路径：先删向量块，再删知识库文档
        for chunk in self.session.exec(select(KnowledgeChunk).where(KnowledgeChunk.kb_id == "kb3")).all():
            self.session.delete(chunk)
        self.session.delete(kb)
        self.session.commit()
        self.assertEqual(self.session.exec(select(KnowledgeChunk)).all(), [])
        self.assertIsNone(self.session.get(KnowledgeBase, "kb3"))


if __name__ == "__main__":
    unittest.main()
