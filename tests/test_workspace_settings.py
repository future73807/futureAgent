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

    def test_c_workspace_preferences_round_trip(self):
        """设置面板的开关必须真的落库并原样读回。"""
        initial = self.client.get(
            f"/api/v1/workspaces/{self.workspace_id}/preferences",
            headers=self.headers(),
        )
        self.assertEqual(initial.status_code, 200, initial.text)
        # 未设置过的工作区拿到的是完整默认值，而不是缺字段的空对象。
        self.assertTrue(initial.json()["preferences"]["memory_enabled"])
        self.assertEqual(initial.json()["preferences"]["rules"], [])

        payload = {
            "memory_enabled": False,
            "include_agents_md": False,
            "include_claude_md": True,
            "rules": ["先给结论再给理由", "  ", "不要编造数据"],
            "browser": {
                "allow_internal": True,
                "allow_external": True,
                "default_target": "external",
                "auto_screenshot": False,
                "data_cleared_at": "2026-09-13T00:00:00Z",
            },
            "installed_plugins": ["local_tools"],
        }
        saved = self.client.put(
            f"/api/v1/workspaces/{self.workspace_id}/preferences",
            json=payload,
            headers=self.headers(),
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        stored = saved.json()["preferences"]
        self.assertFalse(stored["memory_enabled"])
        self.assertFalse(stored["include_agents_md"])
        # 空白规则被丢弃，不留空条目
        self.assertEqual(stored["rules"], ["先给结论再给理由", "不要编造数据"])
        self.assertEqual(stored["browser"]["default_target"], "external")
        self.assertEqual(stored["installed_plugins"], ["local_tools"])

        # 工作区列表也要带上偏好：设置面板首屏直接读它，不再多发一次请求。
        workspaces = self.client.get("/api/v1/workspaces", headers=self.headers()).json()["workspaces"]
        listed = next(ws for ws in workspaces if ws["id"] == self.workspace_id)
        self.assertEqual(listed["preferences"]["rules"], ["先给结论再给理由", "不要编造数据"])

    def test_d_plain_member_cannot_write_preferences(self):
        """成员可读不可写：规则会影响所有人的对话行为，只能由所有者改。"""
        member_login = self.client.post(
            "/api/v1/auth/login",
            json={"email": "ws-member@example.com", "password": TEST_PASSWORD},
        )
        member_token = member_login.json()["access_token"]
        readable = self.client.get(
            f"/api/v1/workspaces/{self.workspace_id}/preferences",
            headers=self.headers(member_token),
        )
        self.assertEqual(readable.status_code, 200, readable.text)
        denied = self.client.put(
            f"/api/v1/workspaces/{self.workspace_id}/preferences",
            json={"rules": ["成员不该能写"]},
            headers=self.headers(member_token),
        )
        self.assertEqual(denied.status_code, 403, denied.text)

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
