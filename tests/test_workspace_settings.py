"""工作区设置能力测试：改名、所有权转移与所有者删除。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select

import db.database as database
from config import settings
from main import app

TEST_PASSWORD = "S3ed-" + uuid4().hex[:13] + "!"


class WorkspaceSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_upload_dir = settings.upload_dir
        cls.original_storage_backend = settings.storage_backend
        cls.original_engine = database.engine
        settings.upload_dir = str(Path(cls.temp_dir.name) / "attachments")
        settings.storage_backend = "local"
        database.engine = create_engine(
            f"sqlite:///{Path(cls.temp_dir.name, 'ws-settings-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        cls.client = TestClient(app)
        cls.client.__enter__()

        owner = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "ws-owner@example.com",
                "password": TEST_PASSWORD,
                "display_name": "WS Owner",
                "workspace_name": "Settings workspace",
            },
        )
        assert owner.status_code == 201, owner.text
        cls.owner_token = owner.json()["access_token"]
        cls.workspace_id = owner.json()["workspaces"][0]["id"]

        member = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "ws-member@example.com",
                "password": TEST_PASSWORD,
                "display_name": "WS Member",
                "workspace_name": "Member home",
            },
        )
        assert member.status_code == 201, member.text
        cls.member_token = member.json()["access_token"]
        cls.member_id = member.json()["user"]["id"]
        joined = cls.client.post(
            f"/api/v1/workspaces/{cls.workspace_id}/members",
            json={"email": "ws-member@example.com", "role": "member"},
            headers=cls.headers(cls.owner_token),
        )
        assert joined.status_code in {200, 201}, joined.text

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        database.engine.dispose()
        database.engine = cls.original_engine
        settings.upload_dir = cls.original_upload_dir
        settings.storage_backend = cls.original_storage_backend
        # Windows 上 SQLite 文件句柄可能晚于断言释放，容忍清理竞态
        import contextlib

        with contextlib.suppress(OSError):
            cls.temp_dir.cleanup()

    @classmethod
    def headers(cls, token=None):
        return {"Authorization": f"Bearer {token or cls.owner_token}"}

    def test_a_rename_workspace(self):
        renamed = self.client.patch(
            f"/api/v1/workspaces/{self.workspace_id}",
            json={"name": "改名后的工作区"},
            headers=self.headers(),
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["workspace"]["name"], "改名后的工作区")

    def test_b_notification_targets_crud_via_settings(self):
        created = self.client.post(
            "/api/v1/notifications/targets",
            json={"name": "设置页机器人", "kind": "feishu", "url": "https://example.com/hook"},
            headers=self.headers(),
        )
        self.assertEqual(created.status_code, 201, created.text)
        target_id = created.json()["target"]["id"]
        listed = self.client.get("/api/v1/notifications/targets", headers=self.headers())
        self.assertTrue(any(item["id"] == target_id for item in listed.json()["targets"]))
        deleted = self.client.delete(
            f"/api/v1/notifications/targets/{target_id}",
            headers=self.headers(),
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_z_owner_transfer_then_new_owner_can_delete(self):
        transferred = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/transfer-owner",
            json={"member_id": self._member_membership_id()},
            headers=self.headers(),
        )
        self.assertEqual(transferred.status_code, 200, transferred.text)
        self.assertEqual(transferred.json()["workspace"]["owner_id"], self.member_id)

        # 原所有者（现为管理员）不能删除；新所有者可以
        denied = self.client.delete(
            f"/api/v1/workspaces/{self.workspace_id}",
            headers=self.headers(),
        )
        self.assertEqual(denied.status_code, 403)

        member_login = self.client.post(
            "/api/v1/auth/login",
            json={"email": "ws-member@example.com", "password": TEST_PASSWORD},
        )
        member_token = member_login.json()["access_token"]
        deleted = self.client.delete(
            f"/api/v1/workspaces/{self.workspace_id}",
            headers=self.headers(member_token),
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        workspaces = self.client.get("/api/v1/auth/me", headers=self.headers(member_token))
        remaining = [ws for ws in workspaces.json()["workspaces"] if ws["id"] == self.workspace_id]
        self.assertEqual(remaining, [])

    def _member_membership_id(self):
        with Session(database.engine) as session:
            from db.models import Membership

            membership = session.exec(
                select(Membership).where(
                    Membership.workspace_id == self.workspace_id,
                    Membership.user_id == self.member_id,
                )
            ).first()
            return membership.id


if __name__ == "__main__":
    unittest.main()
