"""Product-facing API tests: auth, tenancy, work plans and persistence."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

import db.database as database
from main import app


class ProductApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
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
