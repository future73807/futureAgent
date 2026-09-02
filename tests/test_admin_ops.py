"""平台运营管理能力测试：创建用户、重置密码、工作区增删与审计过滤。"""
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


class AdminOpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_upload_dir = settings.upload_dir
        cls.original_storage_backend = settings.storage_backend
        cls.original_engine = database.engine
        settings.upload_dir = str(Path(cls.temp_dir.name) / "attachments")
        settings.storage_backend = "local"
        database.engine = create_engine(
            f"sqlite:///{Path(cls.temp_dir.name, 'admin-ops-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        cls.client = TestClient(app)
        cls.client.__enter__()
        owner = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "ops-admin@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Ops Admin",
                "workspace_name": "Ops home",
            },
        )
        assert owner.status_code == 201, owner.text
        cls.admin_token = owner.json()["access_token"]
        # 提升 为平台管理员（注册流程不直接产出管理员）
        from sqlmodel import Session, select

        from db.models import User

        with Session(database.engine) as session:
            admin_user = session.exec(select(User).where(User.id == owner.json()["user"]["id"])).first()
            admin_user.is_platform_admin = True
            session.add(admin_user)
            session.commit()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        database.engine.dispose()
        database.engine = cls.original_engine
        settings.upload_dir = cls.original_upload_dir
        settings.storage_backend = cls.original_storage_backend
        cls.temp_dir.cleanup()

    @classmethod
    def auth_headers(cls):
        return {"Authorization": f"Bearer {cls.admin_token}"}

    def test_create_user_reset_password_and_workspace_lifecycle(self):
        created = self.client.post(
            "/api/v1/admin/users",
            json={
                "email": "ops-newbie@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Ops Newbie",
            },
            headers=self.auth_headers(),
        )
        self.assertEqual(created.status_code, 201, created.text)
        user_id = created.json()["user"]["id"]

        duplicate = self.client.post(
            "/api/v1/admin/users",
            json={
                "email": "ops-newbie@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Ops Newbie",
            },
            headers=self.auth_headers(),
        )
        self.assertEqual(duplicate.status_code, 409)

        # 用初始密码可以登录
        login = self.client.post(
            "/api/v1/auth/login",
            json={"email": "ops-newbie@example.com", "password": TEST_PASSWORD},
        )
        self.assertEqual(login.status_code, 200, login.text)

        new_password = "N3w-" + uuid4().hex[:13] + "!"
        reset = self.client.post(
            f"/api/v1/admin/users/{user_id}/reset-password",
            json={"password": new_password},
            headers=self.auth_headers(),
        )
        self.assertEqual(reset.status_code, 200, reset.text)

        # 新建工作区并指定所有者
        ws = self.client.post(
            "/api/v1/admin/workspaces",
            json={"name": "Ops 运营工作区", "owner_user_id": user_id},
            headers=self.auth_headers(),
        )
        self.assertEqual(ws.status_code, 201, ws.text)
        workspace = ws.json()["workspace"]
        self.assertTrue(workspace["slug"])

        listed = self.client.get("/api/v1/admin/workspaces", headers=self.auth_headers())
        matched = [item for item in listed.json()["workspaces"] if item["id"] == workspace["id"]]
        self.assertEqual(matched[0]["member_count"], 1)

        # 以所有者身份往工作区写一点数据再删除
        owner_login = self.client.post(
            "/api/v1/auth/login",
            json={"email": "ops-newbie@example.com", "password": new_password},
        )
        self.assertEqual(owner_login.status_code, 200, owner_login.text)
        project = self.client.post(
            "/api/v1/projects",
            json={"name": "待删除项目"},
            headers={
                "Authorization": f"Bearer {owner_login.json()['access_token']}",
                "X-Workspace-ID": workspace["id"],
            },
        )
        self.assertEqual(project.status_code, 201, project.text)

        deleted = self.client.delete(
            f"/api/v1/admin/workspaces/{workspace['id']}",
            headers=self.auth_headers(),
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        after = self.client.get("/api/v1/admin/workspaces", headers=self.auth_headers())
        self.assertFalse(any(item["id"] == workspace["id"] for item in after.json()["workspaces"]))

    def test_audit_filters(self):
        headers = self.auth_headers()
        seeded = self.client.post(
            "/api/v1/admin/users",
            json={
                "email": f"audit-{uuid4().hex[:8]}@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Audit Probe",
            },
            headers=headers,
        )
        self.assertEqual(seeded.status_code, 201, seeded.text)

        filtered = self.client.get(
            "/api/v1/admin/audit-events?limit=50&action=admin.user_created",
            headers=headers,
        )
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertTrue(filtered.json()["events"])
        self.assertTrue(all("admin.user_created" in item["action"] for item in filtered.json()["events"]))

        none_today = self.client.get(
            "/api/v1/admin/audit-events?date_from=2099-01-01&date_to=2099-01-02",
            headers=headers,
        )
        self.assertEqual(none_today.status_code, 200, none_today.text)
        self.assertEqual(none_today.json()["events"], [])


if __name__ == "__main__":
    unittest.main()
