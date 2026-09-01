"""自动化任务调度测试：cron 校验、任务执行与 API 权限。"""
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
from core.scheduler import execute_job, validate_cron
from db.models import ScheduledJob, Workspace, User, now_utc
from main import app

TEST_PASSWORD = "S3ed-" + uuid4().hex[:13] + "!"


class SchedulerUnitTest(unittest.TestCase):
    def test_validate_cron_accepts_standard_expressions(self):
        self.assertTrue(validate_cron("0 18 * * *"))
        self.assertTrue(validate_cron("30 8 * * 1-5"))

    def test_validate_cron_rejects_bad_expressions(self):
        self.assertFalse(validate_cron("not-a-cron"))
        self.assertFalse(validate_cron("99 99 * * *"))
        self.assertFalse(validate_cron(""))

    def test_execute_report_daily_creates_report(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory, 'sched.db').as_posix()}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(User(id="u1", email="s@example.com", display_name="S", password_hash="x"))
                session.add(Workspace(id="w1", name="S", slug="sched-w1", owner_id="u1"))
                session.add(
                    ScheduledJob(
                        id="j1", workspace_id="w1", name="每日汇报日报",
                        job_type="report_daily", cron="0 18 * * *", created_by="u1",
                    )
                )
                session.commit()
                job = session.get(ScheduledJob, "j1")
                status, message = execute_job(session, job)
                self.assertEqual(status, "ok", message)
                self.assertIn("日报已生成", message)
                from db.report_models import ReportDailyReport

                report = session.exec(select(ReportDailyReport)).first()
                self.assertIsNotNone(report)
            engine.dispose()

    def test_execute_unknown_type_marks_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory, 'sched2.db').as_posix()}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(User(id="u1", email="s2@example.com", display_name="S", password_hash="x"))
                session.add(Workspace(id="w1", name="S", slug="sched-w2", owner_id="u1"))
                session.add(
                    ScheduledJob(
                        id="j2", workspace_id="w1", name="坏类型",
                        job_type="nope", cron="0 8 * * *", created_by="u1",
                    )
                )
                session.commit()
                job = session.get(ScheduledJob, "j2")
                status, message = execute_job(session, job)
                self.assertEqual(status, "failed")
                self.assertIn("未知任务类型", message)
            engine.dispose()


class AutomationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_upload_dir = settings.upload_dir
        cls.original_storage_backend = settings.storage_backend
        cls.original_engine = database.engine
        settings.upload_dir = str(Path(cls.temp_dir.name) / "attachments")
        settings.storage_backend = "local"
        database.engine = create_engine(
            f"sqlite:///{Path(cls.temp_dir.name, 'automation-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        cls.client = TestClient(app)
        cls.client.__enter__()
        owner = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "auto-owner@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Auto Owner",
                "workspace_name": "Auto workspace",
            },
        )
        assert owner.status_code == 201, owner.text
        cls.owner_token = owner.json()["access_token"]
        cls.workspace_id = owner.json()["workspaces"][0]["id"]

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

    def test_job_crud_and_run_now(self):
        headers = self.auth_headers(self.owner_token, self.workspace_id)
        created = self.client.post(
            "/api/v1/automation/jobs",
            json={"name": "每日汇报日报", "job_type": "report_daily", "cron": "0 18 * * *"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        job = created.json()["job"]
        self.assertTrue(job["enabled"])
        self.assertEqual(job["job_type_label"], "汇报日报")

        invalid = self.client.post(
            "/api/v1/automation/jobs",
            json={"name": "坏 cron", "job_type": "report_daily", "cron": "abc"},
            headers=headers,
        )
        self.assertEqual(invalid.status_code, 422)

        patched = self.client.patch(
            f"/api/v1/automation/jobs/{job['id']}",
            json={"enabled": False, "cron": "30 7 * * 1-5"},
            headers=headers,
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertFalse(patched.json()["job"]["enabled"])

        run_now = self.client.post(
            f"/api/v1/automation/jobs/{job['id']}/run",
            headers=headers,
        )
        self.assertEqual(run_now.status_code, 200, run_now.text)
        self.assertEqual(run_now.json()["status"], "ok")

        listed = self.client.get("/api/v1/automation/jobs", headers=headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()["jobs"]), 1)

        deleted = self.client.delete(
            f"/api/v1/automation/jobs/{job['id']}",
            headers=headers,
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        emptied = self.client.get("/api/v1/automation/jobs", headers=headers)
        self.assertEqual(emptied.json()["jobs"], [])


if __name__ == "__main__":
    unittest.main()
