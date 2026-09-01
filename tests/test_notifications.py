"""通知中心 API 测试：任务指派触发、已读流转与出口管理。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

import db.database as database
from config import settings
from main import app

TEST_PASSWORD = "S3ed-" + uuid4().hex[:13] + "!"


class NotificationCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_upload_dir = settings.upload_dir
        cls.original_storage_backend = settings.storage_backend
        cls.original_engine = database.engine
        settings.upload_dir = str(Path(cls.temp_dir.name) / "attachments")
        settings.storage_backend = "local"
        database.engine = create_engine(
            f"sqlite:///{Path(cls.temp_dir.name, 'notify-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        cls.client = TestClient(app)
        cls.client.__enter__()

        owner = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "notify-owner@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Notify Owner",
                "workspace_name": "Notify workspace",
            },
        )
        assert owner.status_code == 201, owner.text
        cls.owner_token = owner.json()["access_token"]
        cls.workspace_id = owner.json()["workspaces"][0]["id"]

        member = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "notify-member@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Notify Member",
                "workspace_name": "Member home",
            },
        )
        assert member.status_code == 201, member.text
        cls.member_token = member.json()["access_token"]
        cls.member_id = member.json()["user"]["id"]

        joined = cls.client.post(
            f"/api/v1/workspaces/{cls.workspace_id}/members",
            json={"email": "notify-member@example.com", "role": "member"},
            headers=cls.auth_headers(cls.owner_token),
        )
        assert joined.status_code in {200, 201}, joined.text

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        database.engine.dispose()
        database.engine = cls.original_engine
        settings.upload_dir = cls.original_upload_dir
        settings.storage_backend = cls.original_storage_backend
        cls.temp_dir.cleanup()

    @classmethod
    def auth_headers(cls, token, workspace_id=None):
        headers = {"Authorization": f"Bearer {token}"}
        if workspace_id:
            headers["X-Workspace-ID"] = workspace_id
        return headers

    def test_task_assignment_creates_notification_flow(self):
        project = self.client.post(
            "/api/v1/projects",
            json={"name": "通知样例项目"},
            headers=self.auth_headers(self.owner_token, self.workspace_id),
        )
        self.assertEqual(project.status_code, 201, project.text)
        project_id = project.json()["project"]["id"]

        created = self.client.post(
            "/api/v1/tasks",
            json={"title": "通知样例任务", "project_id": project_id, "assignee_id": self.member_id},
            headers=self.auth_headers(self.owner_token, self.workspace_id),
        )
        self.assertEqual(created.status_code, 201, created.text)

        member_view = self.client.get(
            "/api/v1/notifications",
            headers=self.auth_headers(self.member_token, self.workspace_id),
        )
        self.assertEqual(member_view.status_code, 200, member_view.text)
        payload = member_view.json()
        self.assertGreaterEqual(payload["unread_count"], 1)
        matched = [item for item in payload["notifications"] if item["ref_id"] == created.json()["task"]["id"]]
        self.assertTrue(matched)
        self.assertEqual(matched[0]["type"], "task")
        self.assertFalse(matched[0]["read"])

        notification_id = matched[0]["id"]
        owner_view = self.client.get(
            "/api/v1/notifications",
            headers=self.auth_headers(self.owner_token, self.workspace_id),
        )
        owner_unread = owner_view.json()["unread_count"]
        for item in [n for n in owner_view.json()["notifications"] if n["ref_id"] == created.json()["task"]["id"]]:
            # 指派人自己创建时不会给自己发通知；这里 owner 是创建者，不应收到
            self.fail("指派操作不应通知执行人自己")
        self.assertEqual(owner_unread, 0)

        marked = self.client.post(
            f"/api/v1/notifications/{notification_id}/read",
            headers=self.auth_headers(self.member_token, self.workspace_id),
        )
        self.assertEqual(marked.status_code, 200, marked.text)
        self.assertTrue(marked.json()["notification"]["read"])

        after = self.client.get(
            "/api/v1/notifications",
            headers=self.auth_headers(self.member_token, self.workspace_id),
        )
        self.assertEqual(after.json()["unread_count"] + 1, payload["unread_count"])

        read_all = self.client.post(
            "/api/v1/notifications/read-all",
            headers=self.auth_headers(self.member_token, self.workspace_id),
        )
        self.assertEqual(read_all.status_code, 200, read_all.text)
        final = self.client.get(
            "/api/v1/notifications",
            headers=self.auth_headers(self.member_token, self.workspace_id),
        )
        self.assertEqual(final.json()["unread_count"], 0)

    def test_notification_target_crud_and_validation(self):
        headers = self.auth_headers(self.owner_token, self.workspace_id)
        created = self.client.post(
            "/api/v1/notifications/targets",
            json={"name": "运维群机器人", "kind": "wecom", "url": "https://example.com/webhook/notify"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        target_id = created.json()["target"]["id"]

        listed = self.client.get("/api/v1/notifications/targets", headers=headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()["targets"]), 1)

        invalid_kind = self.client.post(
            "/api/v1/notifications/targets",
            json={"name": "坏样例", "kind": "sms", "url": "https://example.com/x"},
            headers=headers,
        )
        self.assertEqual(invalid_kind.status_code, 422)

        patched = self.client.patch(
            f"/api/v1/notifications/targets/{target_id}",
            json={"enabled": False},
            headers=headers,
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertFalse(patched.json()["target"]["enabled"])

        # 成员无权管理出口
        denied = self.client.get(
            "/api/v1/notifications/targets",
            headers=self.auth_headers(self.member_token, self.workspace_id),
        )
        self.assertEqual(denied.status_code, 403)

        deleted = self.client.delete(
            f"/api/v1/notifications/targets/{target_id}",
            headers=headers,
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)


if __name__ == "__main__":
    unittest.main()
