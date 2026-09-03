"""月报与 CSV 导出 API 测试。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select

import db.database as database
from config import settings
from main import app

TEST_PASSWORD = "S3ed-" + uuid4().hex[:13] + "!"


class MonthlyReportAndExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_upload_dir = settings.upload_dir
        cls.original_storage_backend = settings.storage_backend
        cls.original_engine = database.engine
        settings.upload_dir = str(Path(cls.temp_dir.name) / "attachments")
        settings.storage_backend = "local"
        database.engine = create_engine(
            f"sqlite:///{Path(cls.temp_dir.name, 'monthly-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        cls.client = TestClient(app)
        cls.client.__enter__()

        owner = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "monthly-owner@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Monthly Owner",
                "workspace_name": "Monthly workspace",
            },
        )
        assert owner.status_code == 201, owner.text
        cls.owner_token = owner.json()["access_token"]
        cls.workspace_id = owner.json()["workspaces"][0]["id"]

        # 审计导出需要平台管理员权限
        from db.models import User

        with Session(database.engine) as session:
            admin_user = session.exec(
                select(User).where(User.id == owner.json()["user"]["id"])
            ).first()
            admin_user.is_platform_admin = True
            session.add(admin_user)
            session.commit()

        project = cls.client.post(
            "/api/v1/projects",
            json={"name": "导出项目"},
            headers=cls.headers(),
        )
        assert project.status_code == 201, project.text
        cls.project_id = project.json()["project"]["id"]
        for index, status in enumerate(["todo", "in_progress", "done"]):
            created = cls.client.post(
                "/api/v1/tasks",
                json={"title": f"导出任务 {index}", "project_id": cls.project_id, "status": status, "labels": ["验收"]},
                headers=cls.headers(),
            )
            assert created.status_code == 201, created.text

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
    def headers(cls):
        return {"Authorization": f"Bearer {cls.owner_token}", "X-Workspace-ID": cls.workspace_id}

    def test_monthly_report_generate_list_and_rerun(self):
        today = date.today()
        generated = self.client.post(
            "/api/v1/report/monthly-reports/generate",
            json={"year": today.year, "month": today.month},
            headers=self.headers(),
        )
        self.assertEqual(generated.status_code, 200, generated.text)
        report = generated.json()["monthly_report"]
        self.assertEqual(report["period_year"], today.year)
        self.assertEqual(report["period_month"], today.month)
        self.assertIn("月报", report["title"])
        self.assertIn("summary", report)

        # 幂等：同月重复生成更新而不新建
        again = self.client.post(
            "/api/v1/report/monthly-reports/generate",
            json={"year": today.year, "month": today.month},
            headers=self.headers(),
        )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["monthly_report"]["id"], report["id"])

        listed = self.client.get("/api/v1/report/monthly-reports", headers=self.headers())
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()["monthly_reports"]), 1)

    def test_task_export_csv_contains_rows(self):
        response = self.client.get("/api/v1/tasks/export", headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/csv", response.headers["content-type"])
        body = response.content.decode("utf-8-sig")
        self.assertIn("标题", body)
        self.assertIn("导出任务 0", body)
        self.assertIn("进行中", body)

    def test_audit_export_csv(self):
        response = self.client.get(
            "/api/v1/admin/audit-events/export?action=task.created",
            headers={"Authorization": f"Bearer {self.owner_token}"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/csv", response.headers["content-type"])
        body = response.content.decode("utf-8-sig")
        self.assertIn("task.created", body)
        self.assertIn("发生时间", body)


if __name__ == "__main__":
    unittest.main()
