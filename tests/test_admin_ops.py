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


    def test_delete_user_only_when_no_data(self):
        """删除账号只对"干净"账号开放：有数据的一律挡回并说明是什么挡住了。"""
        created = self.client.post(
            "/api/v1/admin/users",
            json={
                "email": "ops-cleanup@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Cleanup Target",
            },
            headers=self.auth_headers(),
        )
        self.assertEqual(created.status_code, 201, created.text)
        user_id = created.json()["user"]["id"]

        # 先给他一个工作区：此时删除必须被拒，并提示先转移所有权
        workspace = self.client.post(
            "/api/v1/admin/workspaces",
            json={"name": "Cleanup 工作区", "owner_user_id": user_id},
            headers=self.auth_headers(),
        )
        self.assertEqual(workspace.status_code, 201, workspace.text)
        blocked_by_ownership = self.client.delete(
            f"/api/v1/admin/users/{user_id}", headers=self.auth_headers()
        )
        self.assertEqual(blocked_by_ownership.status_code, 409, blocked_by_ownership.text)
        self.assertIn("所有权", blocked_by_ownership.json()["detail"])

        # 工作区删掉后账号就干净了：这次应当真的被删掉
        workspace_id = workspace.json()["workspace"]["id"]
        self.assertIn(
            self.client.delete(
                f"/api/v1/admin/workspaces/{workspace_id}", headers=self.auth_headers()
            ).status_code,
            (200, 204),
        )
        deleted = self.client.delete(f"/api/v1/admin/users/{user_id}", headers=self.auth_headers())
        self.assertEqual(deleted.status_code, 204, deleted.text)
        listed = self.client.get("/api/v1/admin/users", headers=self.auth_headers())
        self.assertNotIn(user_id, [item["id"] for item in listed.json()["users"]])
        self.assertEqual(
            self.client.delete(f"/api/v1/admin/users/{user_id}", headers=self.auth_headers()).status_code,
            404,
        )

    def test_delete_user_guards_self_admin_and_data(self):
        me = self.client.get("/api/v1/auth/me", headers=self.auth_headers())
        self.assertEqual(me.status_code, 200, me.text)
        my_id = me.json()["user"]["id"]
        self_delete = self.client.delete(f"/api/v1/admin/users/{my_id}", headers=self.auth_headers())
        self.assertEqual(self_delete.status_code, 409, self_delete.text)
        self.assertIn("自己", self_delete.json()["detail"])

        # 平台管理员账号必须先撤销管理员身份
        other_admin = self.client.post(
            "/api/v1/admin/users",
            json={
                "email": "ops-other-admin@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Other Admin",
                "is_platform_admin": True,
            },
            headers=self.auth_headers(),
        )
        self.assertEqual(other_admin.status_code, 201, other_admin.text)
        other_admin_id = other_admin.json()["user"]["id"]
        refused = self.client.delete(f"/api/v1/admin/users/{other_admin_id}", headers=self.auth_headers())
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertIn("管理员", refused.json()["detail"])

        # 有业务数据的账号：创建内容后删除应被拒，并列出挡住的具体表
        with_data = self.client.post(
            "/api/v1/admin/users",
            json={
                "email": "ops-with-data@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Has Data",
            },
            headers=self.auth_headers(),
        )
        with_data_id = with_data.json()["user"]["id"]
        # 让这个账号加入一个现有工作区：它没有拥有工作区，但已有成员关系，
        # 命中的是「还有数据」这条分支，而不是所有权那条。
        workspaces = self.client.get("/api/v1/admin/workspaces", headers=self.auth_headers()).json()["workspaces"]
        membership = self.client.post(
            f"/api/v1/workspaces/{workspaces[0]['id']}/members",
            json={"email": "ops-with-data@example.com", "role": "member"},
            headers=self.auth_headers(),
        )
        self.assertEqual(membership.status_code, 201, membership.text)
        blocked = self.client.delete(f"/api/v1/admin/users/{with_data_id}", headers=self.auth_headers())
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("请改为停用账号", blocked.json()["detail"])


if __name__ == "__main__":
    unittest.main()
