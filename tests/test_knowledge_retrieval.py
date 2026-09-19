"""知识检索召回层测试：分词、打分排序与工作区隔离。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

import db.database as database
from core.assistant_ai import render_knowledge_context
from core.knowledge_retrieval import keyword_tokens, retrieve_knowledge, workspace_has_knowledge
from db.knowledge_models import KnowledgeBase
from db.models import Attachment, User, Workspace


class KnowledgeRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_engine = database.engine
        database.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name, 'kb-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        with Session(database.engine) as session:
            session.add(User(id="u1", email="u@example.com", display_name="U", password_hash="x"))
            session.add(Workspace(id="w1", name="一号", slug="w1", owner_id="u1"))
            session.add(Workspace(id="w2", name="二号", slug="w2", owner_id="u1"))
            session.flush()
            session.add(
                KnowledgeBase(
                    id="kb1",
                    workspace_id="w1",
                    title="设备操作手册",
                    content="开机前必须检查传送带张力，发现异常先停机再上报。",
                    created_by="u1",
                )
            )
            session.add(
                KnowledgeBase(
                    id="kb2",
                    workspace_id="w1",
                    title="报销流程",
                    content="差旅报销需要在月底前提交发票。",
                    created_by="u1",
                )
            )
            session.add(
                Attachment(
                    id="a1",
                    workspace_id="w1",
                    uploaded_by="u1",
                    original_name="维护台账.pdf",
                    stored_name="stored-a1.pdf",
                    extracted_text="文档记录传送带需要每周润滑一次。",
                )
            )
            # 另一个工作区的同名资料，用于验证隔离
            session.add(
                KnowledgeBase(
                    id="kb3",
                    workspace_id="w2",
                    title="二号设备手册",
                    content="传送带只能由二号工作区访问。",
                    created_by="u1",
                )
            )
            session.commit()

    def tearDown(self):
        database.engine.dispose()
        database.engine = self.original_engine
        self.temp_dir.cleanup()

    def test_keyword_tokens_extracts_words_and_bigrams(self):
        tokens = keyword_tokens("传送带张力 pump")
        self.assertIn("pump", tokens)
        self.assertIn("传送", tokens)
        self.assertIn("送带", tokens)
        self.assertIn("张力", tokens)
        self.assertNotIn("pum", tokens)

    def test_retrieve_ranks_hits_and_excludes_other_workspaces(self):
        with Session(database.engine) as session:
            results = retrieve_knowledge(session, "w1", "传送带 张力 检查", limit=5)
        self.assertTrue(results)
        identifiers = [item["id"] for item in results]
        # 手册与维护附件都命中；报销流程不应出现
        self.assertIn("kb1", identifiers)
        self.assertIn("a1", identifiers)
        self.assertNotIn("kb2", identifiers)
        # 隔离：二号工作区的文档不可出现在一号的召回里
        self.assertNotIn("kb3", identifiers)
        top = results[0]
        self.assertTrue(top["snippet"])
        self.assertGreaterEqual(top["score"], 2)

    def test_retrieve_returns_empty_without_hit_or_query(self):
        with Session(database.engine) as session:
            self.assertEqual(retrieve_knowledge(session, "w1", "完全无关的查询词汇"), [])
            self.assertEqual(retrieve_knowledge(session, "w1", ""), [])

    def test_workspace_probe_and_prompt_context_rendering(self):
        """对话注入的前置条件与渲染：没建知识库就完全不加提示词内容。"""
        with Session(database.engine) as session:
            self.assertTrue(workspace_has_knowledge(session, "w1"))
            self.assertFalse(workspace_has_knowledge(session, "w-none"))
            hits = retrieve_knowledge(session, "w1", "传送带 张力 检查", limit=2)
        context = render_knowledge_context(hits)
        self.assertIn("【工作区知识库检索结果】", context)
        self.assertIn("[1]", context)
        self.assertIn("标注编号", context)
        self.assertEqual(render_knowledge_context([]), "")


if __name__ == "__main__":
    unittest.main()
