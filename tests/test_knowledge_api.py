"""知识库 API 测试：成员读写、只读成员被拒、删除级联清理向量切块。"""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select

import db.database as database
from db.knowledge_models import KnowledgeChunk
from main import app

TEST_PASSWORD = "S3ed-" + uuid4().hex[:13] + "!"


class KnowledgeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_engine = database.engine
        database.engine = create_engine(
            f"sqlite:///{Path(cls.temp_dir.name, 'kb-api-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        cls.client = TestClient(app)
        cls.client.__enter__()

        owner = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "kb-owner@example.com",
                "password": TEST_PASSWORD,
                "display_name": "KB Owner",
                "workspace_name": "KB workspace",
            },
        )
        assert owner.status_code == 201, owner.text
        cls.owner_token = owner.json()["access_token"]
        cls.workspace_id = owner.json()["workspaces"][0]["id"]

        for email, display, role in (
            ("kb-member@example.com", "KB Member", "member"),
            ("kb-viewer@example.com", "KB Viewer", "viewer"),
        ):
            created = cls.client.post(
                "/api/v1/auth/register",
                json={
                    "email": email,
                    "password": TEST_PASSWORD,
                    "display_name": display,
                    "workspace_name": f"{display} home",
                },
            )
            assert created.status_code == 201, created.text
            if role == "member":
                cls.member_token = created.json()["access_token"]
            else:
                cls.viewer_token = created.json()["access_token"]
            joined = cls.client.post(
                f"/api/v1/workspaces/{cls.workspace_id}/members",
                json={"email": email, "role": role},
                headers=cls.headers(cls.owner_token),
            )
            assert joined.status_code in {200, 201}, joined.text

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        database.engine.dispose()
        database.engine = cls.original_engine
        # Windows 上 SQLite 文件句柄可能晚于断言释放，容忍清理竞态
        import contextlib

        with contextlib.suppress(OSError):
            cls.temp_dir.cleanup()

    @classmethod
    def headers(cls, token=None):
        return {
            "Authorization": f"Bearer {token or cls.owner_token}",
            "X-Workspace-ID": cls.workspace_id,
        }

    def _create(self, title="设备维护手册", content="传送带每周需要润滑一次。"):
        created = self.client.post(
            "/api/v1/knowledge-bases",
            json={"title": title, "description": "现场手册", "content": content},
            headers=self.headers(),
        )
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()["knowledge_base"]

    def test_a_create_list_update_delete_round_trip(self):
        kb = self._create()
        listed = self.client.get("/api/v1/knowledge-bases", headers=self.headers())
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertTrue(any(item["id"] == kb["id"] for item in listed.json()["knowledge_bases"]))

        updated = self.client.patch(
            f"/api/v1/knowledge-bases/{kb['id']}",
            json={"content": "传送带每周润滑一次，张力异常先停机。"},
            headers=self.headers(),
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertIn("停机", updated.json()["knowledge_base"]["content"])

        deleted = self.client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=self.headers())
        self.assertEqual(deleted.status_code, 204, deleted.text)
        remaining = self.client.get("/api/v1/knowledge-bases", headers=self.headers()).json()
        self.assertFalse(any(item["id"] == kb["id"] for item in remaining["knowledge_bases"]))

    def test_b_upload_rejects_binary_and_accepts_text(self):
        rejected = self.client.post(
            "/api/v1/knowledge-bases/upload",
            files={"file": ("扫描件.pdf", io.BytesIO(b"%PDF-1.4 binary"), "application/pdf")},
            headers=self.headers(),
        )
        self.assertEqual(rejected.status_code, 415, rejected.text)

        accepted = self.client.post(
            "/api/v1/knowledge-bases/upload",
            files={"file": ("流程规范.md", io.BytesIO("# 流程\n先停机再上报。".encode()), "text/markdown")},
            data={"title": "流程规范"},
            headers=self.headers(),
        )
        self.assertEqual(accepted.status_code, 201, accepted.text)
        body = accepted.json()["knowledge_base"]
        self.assertEqual(body["title"], "流程规范")
        self.assertEqual(body["file_name"], "流程规范.md")

    def test_c_viewer_cannot_write_but_can_read(self):
        readable = self.client.get("/api/v1/knowledge-bases", headers=self.headers(self.viewer_token))
        self.assertEqual(readable.status_code, 200, readable.text)
        denied = self.client.post(
            "/api/v1/knowledge-bases",
            json={"title": "只读成员创建", "content": "不该成功"},
            headers=self.headers(self.viewer_token),
        )
        self.assertEqual(denied.status_code, 403, denied.text)

    def test_d_member_cannot_delete_but_manager_can(self):
        kb = self._create(title="成员删除用例")
        denied = self.client.delete(
            f"/api/v1/knowledge-bases/{kb['id']}",
            headers=self.headers(self.member_token),
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        allowed = self.client.delete(
            f"/api/v1/knowledge-bases/{kb['id']}",
            headers=self.headers(),
        )
        self.assertEqual(allowed.status_code, 204, allowed.text)

    def test_e_delete_cascades_vector_chunks(self):
        """删除文档必须连带清掉向量块，否则已删除内容还会被检索召回。"""
        kb = self._create(title="级联删除用例")
        with Session(database.engine) as session:
            session.add(
                KnowledgeChunk(
                    workspace_id=self.workspace_id,
                    kb_id=kb["id"],
                    chunk_index=0,
                    content="传送带每周润滑一次。",
                    embedding_json="[0.1, 0.2]",
                )
            )
            session.commit()
            self.assertTrue(
                session.exec(select(KnowledgeChunk).where(KnowledgeChunk.kb_id == kb["id"])).all()
            )

        deleted = self.client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=self.headers())
        self.assertEqual(deleted.status_code, 204, deleted.text)
        with Session(database.engine) as session:
            leftovers = session.exec(
                select(KnowledgeChunk).where(KnowledgeChunk.kb_id == kb["id"])
            ).all()
        self.assertEqual(leftovers, [])

    def test_f_write_endpoints_rebuild_vector_chunks(self):
        """写入必须真的触发切块重建：同步路由里少一次 await 就会静默不建索引。"""
        calls = []

        def fake_embed(texts):
            calls.append(list(texts))
            return [[0.1] * 8 for _ in texts]

        with patch("core.knowledge_retrieval.embedding_enabled", return_value=True), \
                patch("core.knowledge_retrieval.embed_texts", side_effect=fake_embed):
            kb = self._create(title="索引重建用例", content="传送带每周润滑一次，张力异常先停机。" * 10)
        self.assertTrue(calls)
        with Session(database.engine) as session:
            chunks = session.exec(
                select(KnowledgeChunk).where(KnowledgeChunk.kb_id == kb["id"])
            ).all()
        self.assertTrue(chunks)
        self.assertTrue(all(chunk.embedding_json not in ("", "[]") for chunk in chunks))

    def test_g_cross_workspace_documents_are_not_visible(self):
        """知识库按工作区隔离：另一个工作区的文档既不可见也不能改。"""
        other = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "kb-other@example.com",
                "password": TEST_PASSWORD,
                "display_name": "KB Other",
                "workspace_name": "Other workspace",
            },
        )
        assert other.status_code == 201, other.text
        other_headers = {
            "Authorization": f"Bearer {other.json()['access_token']}",
            "X-Workspace-ID": other.json()["workspaces"][0]["id"],
        }
        theirs = self.client.post(
            "/api/v1/knowledge-bases",
            json={"title": "别的工作区文档", "content": "传送带只能由二号工作区访问。"},
            headers=other_headers,
        )
        self.assertEqual(theirs.status_code, 201, theirs.text)
        theirs_id = theirs.json()["knowledge_base"]["id"]

        mine = self.client.get("/api/v1/knowledge-bases", headers=self.headers()).json()
        self.assertFalse(any(item["id"] == theirs_id for item in mine["knowledge_bases"]))
        patch = self.client.patch(
            f"/api/v1/knowledge-bases/{theirs_id}",
            json={"title": "越权改名"},
            headers=self.headers(),
        )
        self.assertEqual(patch.status_code, 404, patch.text)


if __name__ == "__main__":
    unittest.main()
