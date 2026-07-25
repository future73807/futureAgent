"""Product-facing API tests: auth, tenancy, work plans and persistence."""
from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

import db.database as database
from config import settings
from db.models import now_utc
from main import app


class ProductApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_upload_dir = settings.upload_dir
        cls.original_storage_backend = settings.storage_backend
        settings.upload_dir = str(Path(cls.temp_dir.name) / "attachments")
        settings.storage_backend = "local"
        database.engine = create_engine(
            f"sqlite:///{Path(cls.temp_dir.name, 'product-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        cls.client = TestClient(app)
        cls.client.__enter__()

        owner = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "owner@example.com",
                "password": "StrongPass123!",
                "display_name": "Owner",
                "workspace_name": "Owner workspace",
            },
        )
        assert owner.status_code == 201, owner.text
        cls.owner_token = owner.json()["access_token"]
        cls.owner_id = owner.json()["user"]["id"]
        cls.owner_workspace = owner.json()["workspaces"][0]["id"]

        member = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "member@example.com",
                "password": "StrongPass123!",
                "display_name": "Member",
                "workspace_name": "Member workspace",
            },
        )
        assert member.status_code == 201, member.text
        cls.member_token = member.json()["access_token"]
        cls.member_id = member.json()["user"]["id"]

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        database.engine.dispose()
        settings.upload_dir = cls.original_upload_dir
        settings.storage_backend = cls.original_storage_backend
        cls.temp_dir.cleanup()

    @classmethod
    def auth_headers(cls, token, workspace_id=None):
        headers = {"Authorization": f"Bearer {token}"}
        if workspace_id:
            headers["X-Workspace-ID"] = workspace_id
        return headers

    def test_protected_routes_reject_anonymous_and_client_roles(self):
        anonymous = self.client.get("/api/v1/projects")
        self.assertEqual(anonymous.status_code, 401)

        forged = self.client.post(
            "/api/v1/chat/completions",
            headers=self.auth_headers(self.owner_token, self.owner_workspace),
            json={"query": "hello", "model_id": "gpt-4o", "user_role": "admin"},
        )
        self.assertEqual(forged.status_code, 422)

        member_admin = self.client.get(
            "/api/v1/auth/policies",
            headers=self.auth_headers(self.member_token),
        )
        self.assertEqual(member_admin.status_code, 403)

    def test_refresh_session_rotates_and_handles_naive_database_timestamps(self):
        from api.routes import _refresh_session_expired

        self.assertFalse(
            _refresh_session_expired((now_utc() + timedelta(minutes=5)).replace(tzinfo=None))
        )
        self.assertTrue(
            _refresh_session_expired((now_utc() - timedelta(minutes=5)).replace(tzinfo=None))
        )

        login = self.client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "StrongPass123!"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        refreshed = self.client.post("/api/v1/auth/refresh")
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        logout = self.client.post("/api/v1/auth/logout")
        self.assertEqual(logout.status_code, 204, logout.text)
        expired = self.client.post("/api/v1/auth/refresh")
        self.assertEqual(expired.status_code, 401, expired.text)

    def test_workspace_isolation_project_task_and_work_plan_flow(self):
        owner_headers = self.auth_headers(self.owner_token, self.owner_workspace)
        project = self.client.post(
            "/api/v1/projects",
            headers=owner_headers,
            json={"name": "Launch", "description": "Commercial launch board", "color": "#5B5BD6"},
        )
        self.assertEqual(project.status_code, 201, project.text)
        project_id = project.json()["project"]["id"]

        task = self.client.post(
            "/api/v1/tasks",
            headers=owner_headers,
            json={
                "project_id": project_id,
                "title": "Ship authenticated workspace",
                "status": "todo",
                "priority": "high",
                "labels": ["security", "mvp"],
            },
        )
        self.assertEqual(task.status_code, 201, task.text)
        task_id = task.json()["task"]["id"]

        isolated = self.client.get(
            "/api/v1/tasks",
            headers=self.auth_headers(self.member_token, self.owner_workspace),
        )
        self.assertEqual(isolated.status_code, 403)

        add_member = self.client.post(
            f"/api/v1/workspaces/{self.owner_workspace}/members",
            headers=owner_headers,
            json={"email": "member@example.com", "role": "member"},
        )
        self.assertEqual(add_member.status_code, 201, add_member.text)

        plan = self.client.put(
            f"/api/v1/tasks/{task_id}/plan",
            headers=owner_headers,
            json={
                "objective": "Deliver an auditable, protected collaboration flow",
                "steps": [
                    {"title": "Create access controls", "instructions": "Use server tokens"},
                    {
                        "title": "Verify isolation",
                        "instructions": "Exercise workspace boundaries",
                        "assignee_id": self.member_id,
                    },
                ],
            },
        )
        self.assertEqual(plan.status_code, 200, plan.text)
        self.assertEqual(plan.json()["plan"]["status"], "draft")

        approved = self.client.post(
            f"/api/v1/tasks/{task_id}/plan/approve",
            headers=owner_headers,
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["plan"]["status"], "approved")

        member_headers = self.auth_headers(self.member_token, self.owner_workspace)
        member_tasks = self.client.get("/api/v1/tasks", headers=member_headers)
        self.assertEqual(member_tasks.status_code, 200, member_tasks.text)
        self.assertIn(task_id, {item["id"] for item in member_tasks.json()["tasks"]})

        second_step = approved.json()["plan"]["steps"][1]
        running = self.client.patch(
            f"/api/v1/tasks/{task_id}/plan/steps/{second_step['id']}",
            headers=member_headers,
            json={"status": "running", "output_summary": "Isolation test started"},
        )
        self.assertEqual(running.status_code, 200, running.text)
        self.assertEqual(running.json()["plan"]["status"], "in_progress")
        self.assertEqual(running.json()["plan"]["steps"][1]["output_summary"], "Isolation test started")

        task_attachment = self.client.post(
            "/api/v1/attachments",
            headers=owner_headers,
            data={"task_id": task_id},
            files={"file": ("acceptance.md", b"# Acceptance\nReady for review", "text/markdown")},
        )
        self.assertEqual(task_attachment.status_code, 201, task_attachment.text)
        attached = task_attachment.json()["attachment"]
        self.assertTrue(attached["preview_available"])
        preview = self.client.get(attached["preview_url"], headers=owner_headers)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertIn("Ready for review", preview.json()["text"])
        activity = self.client.get(f"/api/v1/tasks/{task_id}/activity", headers=owner_headers)
        self.assertEqual(activity.status_code, 200, activity.text)
        actions = {event["action"] for event in activity.json()["events"]}
        self.assertTrue({"work_plan.approved", "work_plan.step_updated", "attachment.uploaded"}.issubset(actions))

    def test_conversation_attachment_and_audit_are_persistent(self):
        headers = self.auth_headers(self.owner_token, self.owner_workspace)
        conversation = self.client.post(
            "/api/v1/conversations",
            headers=headers,
            json={"title": "Launch research", "model_id": "gpt-4o-mini"},
        )
        self.assertEqual(conversation.status_code, 201, conversation.text)
        conversation_id = conversation.json()["conversation"]["id"]

        upload = self.client.post(
            "/api/v1/attachments",
            headers=headers,
            data={"conversation_id": conversation_id},
            files={"file": ("brief.txt", b"Commercial acceptance criteria", "text/plain")},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        attachment = upload.json()["attachment"]
        self.assertEqual(attachment["original_name"], "brief.txt")

        listed = self.client.get(
            f"/api/v1/attachments?conversation_id={conversation_id}",
            headers=headers,
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()["attachments"]), 1)

        downloaded = self.client.get(attachment["download_url"], headers=headers)
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, b"Commercial acceptance criteria")

        audits = self.client.get("/api/v1/audit-events", headers=headers)
        self.assertEqual(audits.status_code, 200, audits.text)
        self.assertTrue(any(event["action"] == "attachment.uploaded" for event in audits.json()["events"]))

    def test_model_unavailability_is_reported_before_sse_starts(self):
        response = self.client.post(
            "/api/v1/chat/completions",
            headers=self.auth_headers(self.owner_token, self.owner_workspace),
            json={"query": "Verify the preflight", "model_id": "gpt-4o-mini"},
        )
        self.assertEqual(response.status_code, 503, response.text)

    def test_platform_admin_can_record_a_real_model_probe_result(self):
        from sqlmodel import Session
        from db.models import User

        with Session(database.engine) as session:
            owner = session.get(User, self.owner_id)
            owner.is_platform_admin = True
            session.add(owner)
            session.commit()

        async def fake_generate(*_args, **_kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="futureAgent model verification"))])

        with (
            patch("api.routes._ensure_model_ready"),
            patch("api.routes.ModelHub.generate", fake_generate),
        ):
            result = self.client.post(
                "/api/v1/models/gpt-4o-mini/probe",
                headers=self.auth_headers(self.owner_token, self.owner_workspace),
            )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "verified")
        audits = self.client.get("/api/v1/admin/audit-events", headers=self.auth_headers(self.owner_token, self.owner_workspace))
        self.assertTrue(any(event["action"] == "model.probed" for event in audits.json()["events"]))

    def test_liveness_readiness_and_local_metrics_are_available(self):
        live = self.client.get("/api/v1/health/live")
        self.assertEqual(live.status_code, 200, live.text)
        ready = self.client.get("/api/v1/health/ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assertEqual(ready.json()["checks"], {"database": "ok", "storage": "ok"})
        metrics = self.client.get("/api/metrics")
        self.assertEqual(metrics.status_code, 200, metrics.text)
        self.assertIn(b"futureagent_http_requests_total", metrics.content)

    def test_task_execution_persists_a_reviewable_run_and_activity(self):
        owner_headers = self.auth_headers(self.owner_token, self.owner_workspace)
        project = self.client.post(
            "/api/v1/projects",
            headers=owner_headers,
            json={"name": "Agent execution", "description": "Run a governed agent step", "color": "#5B5BD6"},
        )
        self.assertEqual(project.status_code, 201, project.text)
        task = self.client.post(
            "/api/v1/tasks",
            headers=owner_headers,
            json={"project_id": project.json()["project"]["id"], "title": "Draft release note"},
        )
        self.assertEqual(task.status_code, 201, task.text)
        task_id = task.json()["task"]["id"]
        plan = self.client.put(
            f"/api/v1/tasks/{task_id}/plan",
            headers=owner_headers,
            json={"objective": "Produce a reviewable release note", "steps": [{"title": "Draft release note", "instructions": "Summarise the verified change."}]},
        )
        self.assertEqual(plan.status_code, 200, plan.text)
        approved = self.client.post(f"/api/v1/tasks/{task_id}/plan/approve", headers=owner_headers)
        self.assertEqual(approved.status_code, 200, approved.text)
        step_id = approved.json()["plan"]["steps"][0]["id"]

        class FakeSkillManager:
            @staticmethod
            def get_skill(name):
                return object() if name == "default" else None

        class FakeMcpManager:
            servers = {}

        class FakeEngine:
            skill_manager = FakeSkillManager()
            mcp_manager = FakeMcpManager()

            @staticmethod
            def validate_permissions(*_args, **_kwargs):
                return None

            async def run(self, **_kwargs):
                yield "Release note draft with acceptance evidence."

        with (
            patch("api.routes.get_agent_engine", return_value=FakeEngine()),
            patch("api.routes._ensure_model_ready"),
        ):
            response = self.client.post(
                f"/api/v1/tasks/{task_id}/execute",
                headers=owner_headers,
                json={"model_id": "gpt-4o-mini", "skill_name": "default", "step_id": step_id, "idempotency_key": "release-note-first-run"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("event: done", response.text)

        runs = self.client.get(f"/api/v1/tasks/{task_id}/runs", headers=owner_headers)
        self.assertEqual(runs.status_code, 200, runs.text)
        self.assertEqual(len(runs.json()["runs"]), 1)
        self.assertEqual(runs.json()["runs"][0]["status"], "succeeded")
        self.assertEqual(runs.json()["runs"][0]["attempt"], 1)
        self.assertIn("acceptance evidence", runs.json()["runs"][0]["output"])
        first_run_id = runs.json()["runs"][0]["id"]

        from sqlmodel import Session
        from db.models import AgentRun

        with Session(database.engine) as session:
            retry_parent = AgentRun(
                workspace_id=self.owner_workspace,
                task_id=task_id,
                plan_id=approved.json()["plan"]["id"],
                step_id=step_id,
                requested_by=self.owner_id,
                model_id="gpt-4o-mini",
                skill_name="default",
                status="failed",
                error_message="Provider route was unavailable.",
            )
            session.add(retry_parent)
            session.commit()
            session.refresh(retry_parent)
            retry_parent_id = retry_parent.id

        with (
            patch("api.routes.get_agent_engine", return_value=FakeEngine()),
            patch("api.routes._ensure_model_ready"),
        ):
            duplicate = self.client.post(
                f"/api/v1/tasks/{task_id}/execute",
                headers=owner_headers,
                json={"model_id": "gpt-4o-mini", "skill_name": "default", "step_id": step_id, "idempotency_key": "release-note-first-run"},
            )
            retry = self.client.post(
                f"/api/v1/tasks/{task_id}/execute",
                headers=owner_headers,
                json={"model_id": "gpt-4o-mini", "skill_name": "default", "step_id": step_id, "retry_of_id": retry_parent_id, "idempotency_key": "release-note-retry-run"},
            )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(retry.status_code, 200, retry.text)
        retry_runs = self.client.get(f"/api/v1/tasks/{task_id}/runs", headers=owner_headers).json()["runs"]
        retry_run = next(run for run in retry_runs if run["retry_of_id"] == retry_parent_id)
        self.assertEqual(retry_run["retry_of_id"], retry_parent_id)
        self.assertEqual(retry_run["attempt"], 2)

        with Session(database.engine) as session:
            cancellable = AgentRun(
                workspace_id=self.owner_workspace,
                task_id=task_id,
                plan_id=approved.json()["plan"]["id"],
                step_id=step_id,
                requested_by=self.owner_id,
                model_id="gpt-4o-mini",
                skill_name="default",
            )
            session.add(cancellable)
            session.commit()
            session.refresh(cancellable)
            cancellable_id = cancellable.id
        cancelled = self.client.post(
            f"/api/v1/tasks/{task_id}/runs/{cancellable_id}/cancel",
            headers=owner_headers,
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["run"]["status"], "cancelled")

        activity = self.client.get(f"/api/v1/tasks/{task_id}/activity", headers=owner_headers)
        self.assertEqual(activity.status_code, 200, activity.text)
        actions = {event["action"] for event in activity.json()["events"]}
        self.assertTrue({"agent_run.completed", "agent_run.cancelled"}.issubset(actions))

    def test_office_preview_extractors_return_bounded_text(self):
        from api.routes import _extract_docx_text, _extract_xlsx_text

        with tempfile.TemporaryDirectory() as directory:
            docx_path = Path(directory) / "brief.docx"
            with ZipFile(docx_path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Commercial brief</w:t></w:r></w:p></w:body></w:document>',
                )
            self.assertEqual(_extract_docx_text(docx_path), "Commercial brief")

            xlsx_path = Path(directory) / "sheet.xlsx"
            with ZipFile(xlsx_path, "w") as archive:
                archive.writestr(
                    "xl/sharedStrings.xml",
                    '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Metric</t></si><si><t>Ready</t></si></sst>',
                )
                archive.writestr(
                    "xl/worksheets/sheet1.xml",
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row></sheetData></worksheet>',
                )
            self.assertEqual(_extract_xlsx_text(xlsx_path), "Metric\tReady")

    def test_platform_admin_views_are_server_protected(self):
        member_denied = self.client.get(
            "/api/v1/admin/overview",
            headers=self.auth_headers(self.member_token),
        )
        self.assertEqual(member_denied.status_code, 403)

        from sqlmodel import Session
        from db.models import User

        with Session(database.engine) as session:
            owner = session.get(User, self.owner_id)
            owner.is_platform_admin = True
            session.add(owner)
            session.commit()

        admin_headers = self.auth_headers(self.owner_token, self.owner_workspace)
        for endpoint in (
            "/api/v1/admin/overview",
            "/api/v1/admin/users",
            "/api/v1/admin/workspaces",
            "/api/v1/admin/audit-events",
            "/api/v1/settings",
            "/api/v1/auth/policies",
            "/api/v1/models",
            "/api/v1/skills",
            "/api/v1/mcp/servers",
        ):
            response = self.client.get(endpoint, headers=admin_headers)
            self.assertEqual(response.status_code, 200, f"{endpoint}: {response.text}")


if __name__ == "__main__":
    unittest.main()
