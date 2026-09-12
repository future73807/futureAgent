"""Product-facing API tests: auth, tenancy, work plans and persistence."""
from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zipfile import ZipFile

# 密码不在源码里保存字面量：每个测试进程随机生成，只要求单次运行内自洽。
TEST_PASSWORD = "S3ed-" + uuid4().hex[:13] + "!"

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

import db.database as database
from config import settings
from api.routes import _conversation_agent_query
from db.models import ChatMessage, Conversation, now_utc
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
                "password": TEST_PASSWORD,
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
                "password": TEST_PASSWORD,
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

    def test_agent_chat_persists_completed_tool_trace(self):
        registered = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "trace-owner@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Trace Owner",
                "workspace_name": "Trace workspace",
            },
        )
        self.assertEqual(registered.status_code, 201, registered.text)
        headers = self.auth_headers(
            registered.json()["access_token"],
            registered.json()["workspaces"][0]["id"],
        )
        conversation = self.client.post(
            "/api/v1/conversations",
            headers=headers,
            json={"title": "Tool trace", "model_id": "gpt-4o-mini"},
        )
        conversation_id = conversation.json()["conversation"]["id"]

        class FakeSkillManager:
            @staticmethod
            def get_skill(name):
                return object() if name == "default" else None

        class FakeMcpManager:
            servers = {"web_tools": "http://tools.invalid/mcp"}

        class FakeEngine:
            skill_manager = FakeSkillManager()
            mcp_manager = FakeMcpManager()

            @staticmethod
            def validate_permissions(*_args, **_kwargs):
                return None

            async def run(self, **kwargs):
                kwargs["config"]["tool_trace"].append(
                    {
                        "name": "web_search",
                        "tool_call_id": "call-chat-1",
                        "status": "success",
                        "result_preview": "verified result",
                    }
                )
                yield "Answer grounded in the tool result."

        with (
            patch("api.routes.get_agent_engine", return_value=FakeEngine()),
            patch("api.routes._ensure_model_ready"),
        ):
            response = self.client.post(
                "/api/v1/chat/agent",
                headers=headers,
                json={
                    "query": "Search and answer",
                    "model_id": "gpt-4o-mini",
                    "skill_name": "default",
                    "conversation_id": conversation_id,
                    "mcp_servers": ["web_tools"],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("event: done", response.text)
        messages = self.client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=headers,
        ).json()["messages"]
        assistant = next(message for message in reversed(messages) if message["role"] == "assistant")
        self.assertEqual(assistant["tool_trace"][0]["name"], "web_search")
        self.assertEqual(assistant["tool_trace"][0]["tool_call_id"], "call-chat-1")

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
            json={"email": "owner@example.com", "password": TEST_PASSWORD},
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

        with Session(database.engine) as session:
            session.add(
                ChatMessage(
                    conversation_id=conversation_id,
                    role="assistant",
                    content="Earlier launch context",
                )
            )
            session.commit()
            prompt = _conversation_agent_query(
                session,
                session.get(Conversation, conversation_id),
                "Review the brief",
            )
        self.assertIn("Earlier launch context", prompt)
        self.assertIn("Commercial acceptance criteria", prompt)
        self.assertIn("Review the brief", prompt)

        with Session(database.engine) as session:
            conversation = session.get(Conversation, conversation_id)
            conversation.summary = "关键结论：发射窗口已确认。"
            session.add(conversation)
            session.commit()
            prompt_with_summary = _conversation_agent_query(
                session,
                session.get(Conversation, conversation_id),
                "Review the brief",
            )
        self.assertIn("关键结论：发射窗口已确认。", prompt_with_summary)

        from core.checkpointer import get_checkpointer

        with patch("core.checkpointer.settings", SimpleNamespace(checkpoint_conn_str="sqlite:///memory")):
            import asyncio

            self.assertIsNone(asyncio.run(get_checkpointer()))

        audits = self.client.get("/api/v1/audit-events", headers=headers)
        self.assertEqual(audits.status_code, 200, audits.text)
        self.assertTrue(any(event["action"] == "attachment.uploaded" for event in audits.json()["events"]))

    def test_conversation_attachments_are_private_from_regular_members(self):
        owner = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "private-owner@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Private Owner",
                "workspace_name": "Private workspace",
            },
        )
        colleague = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "private-member@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Private Member",
                "workspace_name": "Member home",
            },
        )
        self.assertEqual(owner.status_code, 201, owner.text)
        self.assertEqual(colleague.status_code, 201, colleague.text)
        workspace_id = owner.json()["workspaces"][0]["id"]
        owner_headers = self.auth_headers(owner.json()["access_token"], workspace_id)
        member_headers = self.auth_headers(colleague.json()["access_token"], workspace_id)
        added = self.client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            headers=owner_headers,
            json={"email": "private-member@example.com", "role": "member"},
        )
        self.assertEqual(added.status_code, 201, added.text)

        conversation = self.client.post(
            "/api/v1/conversations",
            headers=owner_headers,
            json={"title": "Owner-only research", "model_id": "gpt-4o-mini"},
        )
        conversation_id = conversation.json()["conversation"]["id"]
        uploaded = self.client.post(
            "/api/v1/attachments",
            headers=owner_headers,
            data={"conversation_id": conversation_id},
            files={"file": ("private.txt", b"owner-only evidence", "text/plain")},
        )
        attachment = uploaded.json()["attachment"]

        listed = self.client.get("/api/v1/attachments", headers=member_headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertNotIn(
            attachment["id"],
            {item["id"] for item in listed.json()["attachments"]},
        )
        filtered = self.client.get(
            f"/api/v1/attachments?conversation_id={conversation_id}",
            headers=member_headers,
        )
        self.assertEqual(filtered.status_code, 403, filtered.text)
        self.assertEqual(
            self.client.get(attachment["preview_url"], headers=member_headers).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(attachment["download_url"], headers=member_headers).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(attachment["download_url"], headers=owner_headers).content,
            b"owner-only evidence",
        )

    def test_model_unavailability_is_reported_before_sse_starts(self):
        # 断言前提是 gpt-4o-mini 没有任何可用凭据；开发者本机 .env 可能为
        # 真实联调填了 key，不隔离的话结果会随 .env 漂移。显式清空凭据后，
        # 验证的仍是同一件事：没有可用路由时必须在 SSE 开流前拒绝。
        with (
            patch.object(settings, "openai_api_key", ""),
            patch.object(settings, "litellm_proxy_url", ""),
        ):
            response = self.client.post(
                "/api/v1/chat/completions",
                headers=self.auth_headers(self.owner_token, self.owner_workspace),
                json={"query": "Verify the preflight", "model_id": "gpt-4o-mini"},
            )
        self.assertEqual(response.status_code, 503, response.text)

    def test_chat_provider_failure_is_sanitized_in_stream_history_and_logs(self):
        owner_headers = self.auth_headers(self.owner_token, self.owner_workspace)
        conversation = self.client.post(
            "/api/v1/conversations",
            headers=owner_headers,
            json={"title": "Sanitized provider failure", "model_id": "gpt-4o-mini"},
        )
        self.assertEqual(conversation.status_code, 201, conversation.text)
        conversation_id = conversation.json()["conversation"]["id"]
        sensitive_detail = "upstream-secret-detail sk-should-never-be-stored"

        with (
            patch("api.routes._ensure_model_ready"),
            patch(
                "api.routes.ModelHub.generate",
                new=AsyncMock(side_effect=RuntimeError(sensitive_detail)),
            ),
            patch("api.routes.logger.error") as safe_log,
        ):
            response = self.client.post(
                "/api/v1/chat/completions",
                headers=owner_headers,
                json={
                    "query": "Trigger a sanitized provider failure",
                    "model_id": "gpt-4o-mini",
                    "conversation_id": conversation_id,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(sensitive_detail, response.text)
        self.assertIn("AI 服务未能完成本次请求", response.text)
        self.assertTrue(safe_log.called)
        self.assertNotIn(sensitive_detail, repr(safe_log.call_args))

        messages = self.client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=owner_headers,
        )
        self.assertEqual(messages.status_code, 200, messages.text)
        assistant = next(
            item
            for item in reversed(messages.json()["messages"])
            if item["role"] == "assistant"
        )
        self.assertEqual(assistant["content"], "[AI request did not complete]")
        self.assertNotIn(sensitive_detail, assistant["content"])

    def test_ollama_is_not_advertised_ready_when_runtime_is_offline(self):
        from core.model_hub import ModelHub

        headers = self.auth_headers(self.owner_token, self.owner_workspace)
        with (
            patch.object(settings, "litellm_proxy_url", ""),
            patch.object(settings, "ollama_base_url", "http://127.0.0.1:11434"),
            patch.object(ModelHub, "_available_ollama_models", return_value=None),
        ):
            response = self.client.get("/api/v1/models", headers=headers)
            chat = self.client.post(
                "/api/v1/chat/completions",
                headers=headers,
                json={"query": "Do not open a false-ready stream", "model_id": "ollama/llama3"},
            )
        detail = next(
            item for item in response.json()["details"] if item["id"] == "ollama/llama3"
        )
        self.assertTrue(detail["configured"])
        self.assertFalse(detail["ready"])
        self.assertEqual(chat.status_code, 503, chat.text)
        self.assertIn("不可达", chat.json()["detail"])

    def test_settings_separate_provider_configuration_from_runtime_availability(self):
        from core.model_hub import ModelHub
        from db.models import User

        with Session(database.engine) as session:
            owner = session.get(User, self.owner_id)
            owner.is_platform_admin = True
            session.add(owner)
            session.commit()

        headers = self.auth_headers(self.owner_token, self.owner_workspace)
        with (
            patch.object(settings, "openai_api_key", "sk-your-openai-key"),
            patch.object(settings, "anthropic_api_key", ""),
            patch.object(settings, "google_api_key", ""),
            patch.object(settings, "longcat_api_key", ""),
            patch.object(settings, "ollama_base_url", "http://127.0.0.1:11434"),
            patch.object(ModelHub, "_available_ollama_models", return_value=None),
        ):
            offline = self.client.get("/api/v1/settings", headers=headers)

        self.assertEqual(offline.status_code, 200, offline.text)
        payload = offline.json()
        self.assertFalse(payload["providers"]["openai"])
        self.assertTrue(payload["providers"]["ollama"])
        self.assertEqual(payload["provider_status"]["openai"]["availability"], "not_configured")
        self.assertEqual(payload["provider_status"]["ollama"]["availability"], "offline")

        with (
            patch.object(settings, "ollama_base_url", "http://127.0.0.1:11434"),
            patch.object(ModelHub, "_available_ollama_models", return_value={"llama3", "qwen2.5"}),
        ):
            online = self.client.get("/api/v1/settings", headers=headers)
        self.assertEqual(online.json()["provider_status"]["ollama"], {
            "configured": True,
            "availability": "online",
            "installed_model_count": 2,
        })

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

    def test_usage_summary_is_workspace_scoped_and_admin_protected(self):
        from db.models import UsageRecord, User

        member_workspace = self.client.get(
            "/api/v1/workspaces", headers=self.auth_headers(self.member_token)
        ).json()["workspaces"][0]["id"]
        with Session(database.engine) as session:
            session.add(
                UsageRecord(
                    workspace_id=self.owner_workspace,
                    user_id=self.owner_id,
                    model_id="usage-model-owner",
                    skill_name="chatbot",
                    source="chat",
                    source_id="conv-owner",
                    agent_mode="chat",
                    input_tokens=100,
                    output_tokens=40,
                    total_tokens=140,
                    llm_calls=1,
                    tool_calls=2,
                    duration_ms=1200,
                )
            )
            session.add(
                UsageRecord(
                    workspace_id=member_workspace,
                    user_id=self.member_id,
                    model_id="usage-model-member",
                    skill_name="chatbot",
                    source="agent_run",
                    source_id="run-member",
                    agent_mode="agent",
                    input_tokens=7,
                    output_tokens=3,
                    total_tokens=10,
                    llm_calls=1,
                )
            )
            session.commit()

        owner = self.client.get(
            "/api/v1/usage/summary?range=all&group_by=model",
            headers=self.auth_headers(self.owner_token, self.owner_workspace),
        )
        self.assertEqual(owner.status_code, 200, owner.text)
        payload = owner.json()
        keys = {group["key"] for group in payload["groups"]}
        self.assertIn("usage-model-owner", keys)
        # 工作区隔离：别人的用量不得出现在本工作区汇总里。
        self.assertNotIn("usage-model-member", keys)
        owner_group = next(
            group for group in payload["groups"] if group["key"] == "usage-model-owner"
        )
        self.assertEqual(owner_group["total_tokens"], 140)
        self.assertEqual(owner_group["tool_calls"], 2)
        # 未登记单价的模型不得编造成本。
        self.assertIsNone(owner_group["cost"])
        self.assertEqual(owner_group["priced_rows"], 0)
        self.assertIsNone(payload["totals"]["cost"])

        member = self.client.get(
            "/api/v1/usage/summary?range=all",
            headers=self.auth_headers(self.member_token, member_workspace),
        )
        member_keys = {group["key"] for group in member.json()["groups"]}
        self.assertIn("usage-model-member", member_keys)
        self.assertNotIn("usage-model-owner", member_keys)

        # member 从未被提升为平台管理员，用它验证平台级接口的保护。
        denied = self.client.get(
            "/api/v1/admin/usage/summary",
            headers=self.auth_headers(self.member_token, member_workspace),
        )
        self.assertEqual(denied.status_code, 403)

        # 同类中较早的测试会把 owner 提升为平台管理员且不回滚；
        # 这里先保存原值再恢复，避免本测试改变后续测试依赖的状态。
        with Session(database.engine) as session:
            original_admin = session.get(User, self.owner_id).is_platform_admin
            account = session.get(User, self.owner_id)
            account.is_platform_admin = True
            session.add(account)
            session.commit()
        try:
            platform = self.client.get(
                "/api/v1/admin/usage/summary?range=all",
                headers=self.auth_headers(self.owner_token, self.owner_workspace),
            )
            self.assertEqual(platform.status_code, 200, platform.text)
            platform_keys = {group["key"] for group in platform.json()["groups"]}
            self.assertTrue(
                {"usage-model-owner", "usage-model-member"}.issubset(platform_keys)
            )
        finally:
            with Session(database.engine) as session:
                account = session.get(User, self.owner_id)
                account.is_platform_admin = original_admin
                session.add(account)
                session.commit()

    def test_permission_mode_is_owner_only_capped_and_validated(self):
        owner_headers = self.auth_headers(self.owner_token, self.owner_workspace)
        listing = self.client.get("/api/v1/workspaces", headers=owner_headers)
        current = next(
            item for item in listing.json()["workspaces"] if item["id"] == self.owner_workspace
        )
        # 存量工作区升级后必须落在最严格档位，不得静默放宽。
        self.assertEqual(current["permission_mode"], "default")
        self.assertEqual(current["max_permission_mode"], "full_access")

        invalid = self.client.put(
            f"/api/v1/workspaces/{self.owner_workspace}/permission-mode",
            headers=owner_headers,
            json={"permission_mode": "yolo"},
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)

        # 管理员（非所有者）无权调整档位。
        delegated = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "perm-admin@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Perm Admin",
                "workspace_name": "Perm home",
            },
        )
        self.assertEqual(delegated.status_code, 201, delegated.text)
        invited = self.client.post(
            f"/api/v1/workspaces/{self.owner_workspace}/members",
            headers=owner_headers,
            json={"email": "perm-admin@example.com", "role": "admin"},
        )
        self.assertEqual(invited.status_code, 201, invited.text)
        admin_headers = self.auth_headers(
            delegated.json()["access_token"], self.owner_workspace
        )
        forbidden = self.client.put(
            f"/api/v1/workspaces/{self.owner_workspace}/permission-mode",
            headers=admin_headers,
            json={"permission_mode": "full_access"},
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

        try:
            updated = self.client.put(
                f"/api/v1/workspaces/{self.owner_workspace}/permission-mode",
                headers=owner_headers,
                json={"permission_mode": "full_access"},
            )
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(updated.json()["workspace"]["permission_mode"], "full_access")

            # 部署上限为 default 时，显式配置更宽档位必须报错而非静默失效。
            with patch.object(settings, "max_permission_mode", "default"):
                capped = self.client.put(
                    f"/api/v1/workspaces/{self.owner_workspace}/permission-mode",
                    headers=owner_headers,
                    json={"permission_mode": "auto_approve"},
                )
                self.assertEqual(capped.status_code, 422, capped.text)
                # 读取时生效档位也被上限压回 default。
                restrained = self.client.get("/api/v1/workspaces", headers=owner_headers)
                effective = next(
                    item for item in restrained.json()["workspaces"]
                    if item["id"] == self.owner_workspace
                )
                self.assertEqual(effective["permission_mode"], "default")
                self.assertEqual(effective["max_permission_mode"], "default")

            audits = self.client.get("/api/v1/audit-events", headers=owner_headers)
            self.assertTrue(
                any(
                    event["action"] == "workspace.permission_mode_updated"
                    for event in audits.json()["events"]
                )
            )
        finally:
            restore = self.client.put(
                f"/api/v1/workspaces/{self.owner_workspace}/permission-mode",
                headers=owner_headers,
                json={"permission_mode": "default"},
            )
            self.assertEqual(restore.status_code, 200, restore.text)

    def test_auto_approve_mode_approves_plan_on_save_and_default_does_not(self):
        owner_headers = self.auth_headers(self.owner_token, self.owner_workspace)
        project = self.client.post(
            "/api/v1/projects",
            headers=owner_headers,
            json={"name": "Approval modes", "description": "Verify auto approval", "color": "#5B5BD6"},
        )
        self.assertEqual(project.status_code, 201, project.text)
        task = self.client.post(
            "/api/v1/tasks",
            headers=owner_headers,
            json={"project_id": project.json()["project"]["id"], "title": "Auto approve me"},
        )
        self.assertEqual(task.status_code, 201, task.text)
        task_id = task.json()["task"]["id"]
        plan_body = {
            "objective": "Verify approval behaviour",
            "steps": [{"title": "Only step", "instructions": "Do the thing."}],
        }

        draft = self.client.put(
            f"/api/v1/tasks/{task_id}/plan", headers=owner_headers, json=plan_body
        )
        self.assertEqual(draft.status_code, 200, draft.text)
        self.assertEqual(draft.json()["plan"]["status"], "draft")

        try:
            promoted = self.client.put(
                f"/api/v1/workspaces/{self.owner_workspace}/permission-mode",
                headers=owner_headers,
                json={"permission_mode": "auto_approve"},
            )
            self.assertEqual(promoted.status_code, 200, promoted.text)

            automatic = self.client.put(
                f"/api/v1/tasks/{task_id}/plan", headers=owner_headers, json=plan_body
            )
            self.assertEqual(automatic.status_code, 200, automatic.text)
            plan = automatic.json()["plan"]
            self.assertEqual(plan["status"], "approved")
            self.assertEqual(plan["approved_by"], self.owner_id)
            self.assertTrue(plan["approved_at"])

            audits = self.client.get("/api/v1/audit-events", headers=owner_headers)
            auto_events = [
                event for event in audits.json()["events"]
                if event["action"] == "work_plan.auto_approved"
            ]
            self.assertTrue(auto_events)
            self.assertEqual(auto_events[0]["metadata"]["permission_mode"], "auto_approve")
        finally:
            restore = self.client.put(
                f"/api/v1/workspaces/{self.owner_workspace}/permission-mode",
                headers=owner_headers,
                json={"permission_mode": "default"},
            )
            self.assertEqual(restore.status_code, 200, restore.text)

        # 档位恢复后，保存计划重新回到草稿，必须人工批准。
        manual = self.client.put(
            f"/api/v1/tasks/{task_id}/plan", headers=owner_headers, json=plan_body
        )
        self.assertEqual(manual.status_code, 200, manual.text)
        self.assertEqual(manual.json()["plan"]["status"], "draft")

    def test_request_cannot_escalate_above_the_workspace_permission_mode(self):
        from api.routes import _effective_permission_mode
        from db.models import Workspace

        workspace = Workspace(
            id="ws-1", name="n", slug="s", owner_id="u-1", permission_mode="default"
        )
        # 向上提权被静默丢弃，而不是报错。
        self.assertEqual(_effective_permission_mode(workspace, "full_access"), "default")
        self.assertEqual(_effective_permission_mode(workspace, "auto_approve"), "default")
        self.assertEqual(_effective_permission_mode(workspace), "default")

        workspace.permission_mode = "full_access"
        # 向下收紧生效。
        self.assertEqual(_effective_permission_mode(workspace, "default"), "default")
        self.assertEqual(_effective_permission_mode(workspace, "auto_approve"), "auto_approve")
        self.assertEqual(_effective_permission_mode(workspace), "full_access")

        # 部署上限优先于工作区档位。
        with patch.object(settings, "max_permission_mode", "auto_approve"):
            self.assertEqual(_effective_permission_mode(workspace), "auto_approve")
        # 非法上限按最严格处理，失败方向是“更严”。
        with patch.object(settings, "max_permission_mode", "nonsense"):
            self.assertEqual(_effective_permission_mode(workspace), "default")
        # 历史数据里的未知档位也归到 default。
        workspace.permission_mode = "legacy-unknown"
        self.assertEqual(_effective_permission_mode(workspace), "default")

    def test_multiple_tasks_can_share_a_project_and_status_column(self):
        """同一看板列必须能放多个任务。

        单列聚合在 SQLModel 的 exec() 下返回标量而不是 Row；按 Row 取
        下标会让“列里已有任务”时的创建抛 TypeError→500，而空列时
        max 为 NULL 反而正常——只建一个任务的测试永远发现不了。
        """
        headers = self.auth_headers(self.owner_token, self.owner_workspace)
        project = self.client.post(
            "/api/v1/projects",
            headers=headers,
            json={"name": "Multi task column", "description": "d", "color": "#5B5BD6"},
        )
        self.assertEqual(project.status_code, 201, project.text)
        project_id = project.json()["project"]["id"]

        sort_orders = []
        for index in range(3):
            created = self.client.post(
                "/api/v1/tasks",
                headers=headers,
                json={
                    "project_id": project_id,
                    "title": f"同列任务 {index}",
                    "description": "验证同状态列可重复创建",
                    "priority": "medium",
                    "status": "todo",
                    "labels": [],
                },
            )
            self.assertEqual(created.status_code, 201, created.text)
            sort_orders.append(created.json()["task"]["sort_order"])

        # 新任务排到列尾， sort_order 递增且不重复。
        self.assertEqual(sort_orders, sorted(set(sort_orders)))
        self.assertEqual(sort_orders, [10, 20, 30])

        listed = self.client.get(
            "/api/v1/tasks", headers=headers, params={"project_id": project_id}
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()["tasks"]), 3)

        # 不同状态列各自从头计数，互不干扰。
        other_column = self.client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"project_id": project_id, "title": "进行中列首个", "status": "in_progress"},
        )
        self.assertEqual(other_column.status_code, 201, other_column.text)
        self.assertEqual(other_column.json()["task"]["sort_order"], 10)

    def test_supervised_modes_require_their_termination_criterion(self):
        owner_headers = self.auth_headers(self.owner_token, self.owner_workspace)
        # goal 靠目标判定达成，缺了它监督者只能一直迭代到烧完预算。
        goal_missing = self.client.post(
            "/api/v1/chat/agent",
            headers=owner_headers,
            json={"query": "x", "model_id": "gpt-4o-mini", "skill_name": "default", "mode": "goal"},
        )
        self.assertEqual(goal_missing.status_code, 422, goal_missing.text)
        self.assertIn("目标", goal_missing.json()["detail"])

        loop_missing = self.client.post(
            "/api/v1/chat/agent",
            headers=owner_headers,
            json={"query": "x", "model_id": "gpt-4o-mini", "skill_name": "default", "mode": "loop"},
        )
        self.assertEqual(loop_missing.status_code, 422, loop_missing.text)
        self.assertIn("停止条件", loop_missing.json()["detail"])

        unknown_mode = self.client.post(
            "/api/v1/chat/agent",
            headers=owner_headers,
            json={"query": "x", "model_id": "gpt-4o-mini", "skill_name": "default", "mode": "turbo"},
        )
        self.assertEqual(unknown_mode.status_code, 422, unknown_mode.text)

    def test_agent_mode_is_persisted_so_a_retry_reproduces_it(self):
        owner_headers = self.auth_headers(self.owner_token, self.owner_workspace)
        project = self.client.post(
            "/api/v1/projects",
            headers=owner_headers,
            json={"name": "Mode persistence", "description": "Verify mode is stored", "color": "#5B5BD6"},
        )
        self.assertEqual(project.status_code, 201, project.text)
        task = self.client.post(
            "/api/v1/tasks",
            headers=owner_headers,
            json={"project_id": project.json()["project"]["id"], "title": "Goal mode run"},
        )
        task_id = task.json()["task"]["id"]
        plan = self.client.put(
            f"/api/v1/tasks/{task_id}/plan",
            headers=owner_headers,
            json={"objective": "完成报告", "steps": [{"title": "起草章节", "instructions": "写出三章"}]},
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
            servers: dict = {}

        class FakeEngine:
            skill_manager = FakeSkillManager()
            mcp_manager = FakeMcpManager()

            @staticmethod
            def validate_permissions(*_args, **_kwargs):
                return None

            async def run(self, **kwargs):
                yield "goal mode output"
                # 真实的监督节点在最后一个 token 之后才写判定。顺序写反了
                # 就会错过“循环结束后再冲一次”的路径，末轮事件丢失也不会被发现。
                kwargs["config"]["iterations"].append(
                    {"iteration": 1, "verdict": "met", "reason": "已达成"}
                )

        with (
            patch("api.routes.get_agent_engine", return_value=FakeEngine()),
            patch("api.routes._ensure_model_ready"),
        ):
            response = self.client.post(
                f"/api/v1/tasks/{task_id}/execute",
                headers=owner_headers,
                json={
                    "model_id": "gpt-4o-mini",
                    "skill_name": "default",
                    "step_id": step_id,
                    "mode": "goal",
                    "goal": "完成报告",
                    "success_criteria": "包含三章",
                    "max_iterations": 3,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("event: iteration", response.text)

        runs = self.client.get(f"/api/v1/tasks/{task_id}/runs", headers=owner_headers)
        self.assertEqual(runs.status_code, 200, runs.text)
        run = runs.json()["runs"][0]
        self.assertEqual(run["agent_mode"], "goal")
        self.assertEqual(run["iterations"][0]["verdict"], "met")
        self.assertEqual(run["iterations"][0]["reason"], "已达成")

    def test_plan_step_exposes_latest_run_status_for_pending_review(self):
        """步骤被人工复核前，前端要靠“最近一次执行成功”把进度算作半步。"""
        owner_headers = self.auth_headers(self.owner_token, self.owner_workspace)
        project = self.client.post(
            "/api/v1/projects",
            headers=owner_headers,
            json={"name": "Pending review", "description": "Track executed steps", "color": "#5B5BD6"},
        )
        self.assertEqual(project.status_code, 201, project.text)
        task = self.client.post(
            "/api/v1/tasks",
            headers=owner_headers,
            json={"project_id": project.json()["project"]["id"], "title": "Two-step task"},
        )
        task_id = task.json()["task"]["id"]
        plan = self.client.put(
            f"/api/v1/tasks/{task_id}/plan",
            headers=owner_headers,
            json={
                "objective": "验证执行状态回传",
                "steps": [
                    {"title": "已执行步骤", "instructions": "会被 AI 跑一次"},
                    {"title": "未执行步骤", "instructions": "保持待执行"},
                ],
            },
        )
        self.assertEqual(plan.status_code, 200, plan.text)
        self.assertIsNone(plan.json()["plan"]["steps"][0]["latest_run_status"])
        approved = self.client.post(f"/api/v1/tasks/{task_id}/plan/approve", headers=owner_headers)
        self.assertEqual(approved.status_code, 200, approved.text)
        executed_step_id = approved.json()["plan"]["steps"][0]["id"]

        class FakeSkillManager:
            @staticmethod
            def get_skill(name):
                return object() if name == "default" else None

        class FakeMcpManager:
            servers: dict = {}

        class FakeEngine:
            skill_manager = FakeSkillManager()
            mcp_manager = FakeMcpManager()

            @staticmethod
            def validate_permissions(*_args, **_kwargs):
                return None

            async def run(self, **kwargs):
                yield "done"

        with (
            patch("api.routes.get_agent_engine", return_value=FakeEngine()),
            patch("api.routes._ensure_model_ready"),
        ):
            response = self.client.post(
                f"/api/v1/tasks/{task_id}/execute",
                headers=owner_headers,
                json={"model_id": "gpt-4o-mini", "skill_name": "default", "step_id": executed_step_id, "mode": "agent"},
            )
        self.assertEqual(response.status_code, 200, response.text)

        refreshed = self.client.get(f"/api/v1/tasks/{task_id}/plan", headers=owner_headers)
        steps = refreshed.json()["plan"]["steps"]
        self.assertEqual(steps[0]["latest_run_status"], "succeeded")
        self.assertIsNone(steps[1]["latest_run_status"])

    def test_subagent_usage_is_persisted_against_the_parent_run(self):
        owner_headers = self.auth_headers(self.owner_token, self.owner_workspace)
        project = self.client.post(
            "/api/v1/projects",
            headers=owner_headers,
            json={"name": "Subagent usage", "description": "Verify attribution", "color": "#5B5BD6"},
        )
        task = self.client.post(
            "/api/v1/tasks",
            headers=owner_headers,
            json={"project_id": project.json()["project"]["id"], "title": "Delegate work"},
        )
        task_id = task.json()["task"]["id"]
        plan = self.client.put(
            f"/api/v1/tasks/{task_id}/plan",
            headers=owner_headers,
            json={"objective": "分发子任务", "steps": [{"title": "执行子任务", "instructions": "交给子代理"}]},
        )
        self.client.post(f"/api/v1/tasks/{task_id}/plan/approve", headers=owner_headers)
        step_id = plan.json()["plan"]["steps"][0]["id"]

        class FakeSkillManager:
            @staticmethod
            def get_skill(name):
                return object() if name == "default" else None

        class FakeMcpManager:
            servers: dict = {}

        class FakeEngine:
            skill_manager = FakeSkillManager()
            mcp_manager = FakeMcpManager()

            @staticmethod
            def validate_permissions(*_args, **_kwargs):
                return None

            async def run(self, **kwargs):
                config = kwargs["config"]
                config["usage_by_message"]["parent-call"] = {
                    "input_tokens": 50, "output_tokens": 10, "total_tokens": 60,
                }
                # 两个子代理：一个成功，一个超时但已消耗 token。
                config["subagent_usage"] = [
                    {
                        "model_id": "child-model", "skill_name": "coder", "status": "succeeded",
                        "depth": 1, "tool_calls": 2, "duration_ms": 800,
                        "usage": {"input_tokens": 30, "output_tokens": 5, "total_tokens": 35, "llm_calls": 1},
                    },
                    {
                        "model_id": "child-model", "skill_name": "coder", "status": "timeout",
                        "depth": 1, "tool_calls": 0, "duration_ms": 1500,
                        "usage": {"input_tokens": 8, "output_tokens": 0, "total_tokens": 8, "llm_calls": 1},
                    },
                ]
                yield "delegated output"

        with (
            patch("api.routes.get_agent_engine", return_value=FakeEngine()),
            patch("api.routes._ensure_model_ready"),
        ):
            response = self.client.post(
                f"/api/v1/tasks/{task_id}/execute",
                headers=owner_headers,
                json={"model_id": "gpt-4o-mini", "skill_name": "default", "step_id": step_id},
            )
        self.assertEqual(response.status_code, 200, response.text)

        from sqlmodel import Session, select
        from db.models import UsageRecord

        run_id = self.client.get(
            f"/api/v1/tasks/{task_id}/runs", headers=owner_headers
        ).json()["runs"][0]["id"]
        with Session(database.engine) as session:
            rows = session.exec(
                select(UsageRecord).where(UsageRecord.source_id == run_id)
            ).all()
        parents = [row for row in rows if row.source == "agent_run"]
        children = [row for row in rows if row.source == "subagent"]
        self.assertEqual(len(parents), 1)
        self.assertEqual(parents[0].total_tokens, 60)
        self.assertIsNone(parents[0].parent_run_id)
        # 失败与超时的子代理同样入账，因为 token 已经真实消耗。
        self.assertEqual(len(children), 2)
        self.assertEqual({row.parent_run_id for row in children}, {run_id})
        self.assertEqual(sorted(row.total_tokens for row in children), [8, 35])
        self.assertTrue(all(row.model_id == "child-model" for row in children))

        detail = self.client.get(f"/api/v1/tasks/{task_id}/runs", headers=owner_headers)
        usage = detail.json()["runs"][0]["usage"]
        # run 总量包含子代理，并单独给出明细。
        self.assertEqual(usage["total_tokens"], 60 + 35 + 8)
        self.assertEqual(usage["subagent_records"], 2)
        self.assertEqual(len(usage["subagents"]), 2)

    def test_assistant_message_carries_agent_mode_usage_and_iterations(self):
        """对话即工作台：消息自身要携带执行上下文，前端才能就地渲染卡片。"""
        headers = self.auth_headers(self.owner_token, self.owner_workspace)
        conversation = self.client.post(
            "/api/v1/conversations",
            headers=headers,
            json={"title": "Message context", "model_id": "gpt-4o-mini"},
        )
        self.assertEqual(conversation.status_code, 201, conversation.text)
        conversation_id = conversation.json()["conversation"]["id"]

        class FakeSkillManager:
            @staticmethod
            def get_skill(name):
                return object() if name == "default" else None

        class FakeMcpManager:
            servers: dict = {}

        class FakeEngine:
            skill_manager = FakeSkillManager()
            mcp_manager = FakeMcpManager()

            @staticmethod
            def validate_permissions(*_args, **_kwargs):
                return None

            async def run(self, **kwargs):
                config = kwargs["config"]
                config["usage_by_message"]["call-1"] = {
                    "input_tokens": 11, "output_tokens": 7, "total_tokens": 18,
                }
                yield "第一段"
                # 真实监督节点在最后一个 token 之后才写判定。
                config["iterations"].append(
                    {"iteration": 1, "verdict": "not_met", "reason": "还差一步"}
                )

        with (
            patch("api.routes.get_agent_engine", return_value=FakeEngine()),
            patch("api.routes._ensure_model_ready"),
        ):
            response = self.client.post(
                "/api/v1/chat/agent",
                headers=headers,
                json={
                    "query": "推进目标",
                    "model_id": "gpt-4o-mini",
                    "skill_name": "default",
                    "conversation_id": conversation_id,
                    "mode": "goal",
                    "goal": "完成报告",
                    "success_criteria": "包含三章",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)

        messages = self.client.get(
            f"/api/v1/conversations/{conversation_id}/messages", headers=headers
        ).json()["messages"]
        assistant = next(m for m in reversed(messages) if m["role"] == "assistant")
        self.assertEqual(assistant["agent_mode"], "goal")
        self.assertEqual(assistant["usage"]["total_tokens"], 18)
        self.assertEqual(assistant["usage"]["llm_calls"], 1)
        self.assertEqual(assistant["iterations"][0]["verdict"], "not_met")
        self.assertEqual(assistant["iterations"][0]["reason"], "还差一步")

        # 用户消息不携带执行上下文，但字段必须存在且为安全默认值。
        user_message = next(m for m in messages if m["role"] == "user")
        self.assertEqual(user_message["agent_mode"], "agent")
        self.assertIsNone(user_message["usage"])
        self.assertEqual(user_message["iterations"], [])

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
            servers = {"web_tools": "http://tools.invalid/mcp"}

        class FakeEngine:
            skill_manager = FakeSkillManager()
            mcp_manager = FakeMcpManager()

            @staticmethod
            def validate_permissions(*_args, **_kwargs):
                return None

            async def run(self, **kwargs):
                kwargs["config"]["tool_trace"].append(
                    {
                        "name": "web_search",
                        "tool_call_id": "call-run-1",
                        "status": "success",
                        "result_preview": "acceptance evidence source",
                    }
                )
                # 模拟引擎按模型调用上报用量，验证路由侧确实落库。
                kwargs["config"]["usage_by_message"]["call-run-1"] = {
                    "input_tokens": 120,
                    "output_tokens": 30,
                    "total_tokens": 150,
                }
                yield "Release note draft with acceptance evidence."

        with (
            patch("api.routes.get_agent_engine", return_value=FakeEngine()),
            patch("api.routes._ensure_model_ready"),
        ):
            response = self.client.post(
                f"/api/v1/tasks/{task_id}/execute",
                headers=owner_headers,
                json={"model_id": "gpt-4o-mini", "skill_name": "default", "step_id": step_id, "mcp_servers": [], "idempotency_key": "release-note-first-run"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("event: done", response.text)

        runs = self.client.get(f"/api/v1/tasks/{task_id}/runs", headers=owner_headers)
        self.assertEqual(runs.status_code, 200, runs.text)
        self.assertEqual(len(runs.json()["runs"]), 1)
        self.assertEqual(runs.json()["runs"][0]["status"], "succeeded")
        self.assertEqual(runs.json()["runs"][0]["attempt"], 1)
        self.assertEqual(runs.json()["runs"][0]["mcp_servers"], [])
        self.assertEqual(runs.json()["runs"][0]["tool_trace"][0]["name"], "web_search")
        self.assertIn("acceptance evidence", runs.json()["runs"][0]["output"])
        first_run_id = runs.json()["runs"][0]["id"]

        from sqlmodel import Session, select
        from db.models import AgentRun, UsageRecord

        # 成功执行必须留下一条可汇总的真实用量记录。
        with Session(database.engine) as session:
            usage_rows = session.exec(
                select(UsageRecord).where(UsageRecord.source_id == first_run_id)
            ).all()
        self.assertEqual(len(usage_rows), 1)
        self.assertEqual(usage_rows[0].source, "agent_run")
        self.assertEqual(usage_rows[0].total_tokens, 150)
        self.assertEqual(usage_rows[0].input_tokens, 120)
        self.assertEqual(usage_rows[0].output_tokens, 30)
        self.assertEqual(usage_rows[0].llm_calls, 1)
        self.assertEqual(usage_rows[0].tool_calls, 1)
        self.assertEqual(usage_rows[0].workspace_id, self.owner_workspace)

        with Session(database.engine) as session:
            retry_parent = AgentRun(
                workspace_id=self.owner_workspace,
                task_id=task_id,
                plan_id=approved.json()["plan"]["id"],
                step_id=step_id,
                requested_by=self.owner_id,
                model_id="gpt-4o-mini",
                skill_name="default",
                mcp_servers_json='["web_tools"]',
                tool_trace_json='[{"name":"fetch_url","tool_call_id":"parent-call","status":"error","result_preview":"provider unavailable"}]',
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
                json={"model_id": "gpt-4o-mini", "skill_name": "default", "step_id": step_id, "mcp_servers": ["web_tools"], "retry_of_id": retry_parent_id, "idempotency_key": "release-note-retry-run"},
            )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(retry.status_code, 200, retry.text)
        retry_runs = self.client.get(f"/api/v1/tasks/{task_id}/runs", headers=owner_headers).json()["runs"]
        retry_run = next(run for run in retry_runs if run["retry_of_id"] == retry_parent_id)
        self.assertEqual(retry_run["retry_of_id"], retry_parent_id)
        self.assertEqual(retry_run["attempt"], 2)
        self.assertEqual(retry_run["mcp_servers"], ["web_tools"])
        self.assertEqual(retry_run["tool_trace"][0]["tool_call_id"], "call-run-1")

        with Session(database.engine) as session:
            cancellable = AgentRun(
                workspace_id=self.owner_workspace,
                task_id=task_id,
                plan_id=approved.json()["plan"]["id"],
                step_id=step_id,
                requested_by=self.owner_id,
                model_id="gpt-4o-mini",
                skill_name="default",
                mcp_servers_json='["web_tools"]',
                tool_trace_json='[{"name":"fetch_url","tool_call_id":"cancelled-call","status":"success","result_preview":"saved before cancellation"}]',
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
        self.assertEqual(cancelled.json()["run"]["mcp_servers"], ["web_tools"])
        self.assertEqual(
            cancelled.json()["run"]["tool_trace"][0]["tool_call_id"],
            "cancelled-call",
        )

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

    def test_pdf_extractor_returns_text_and_degrades(self):
        from api.routes import _extract_pdf_text

        def build_text_pdf(text: str) -> bytes:
            stream = f"BT /F1 14 Tf 72 720 Td ({text}) Tj ET".encode()
            objects = [
                b"<< /Type /Catalog /Pages 2 0 R >>",
                b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
                b"/Resources << /Font << /F1 5 0 R >> >> >>",
                b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            ]
            output = bytearray(b"%PDF-1.4\n")
            offsets: list[int] = []
            for number, body in enumerate(objects, start=1):
                offsets.append(len(output))
                output += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
            xref_at = len(output)
            output += f"xref\n0 {len(objects) + 1}\n".encode()
            output += b"0000000000 65535 f \n"
            for offset in offsets:
                output += f"{offset:010d} 00000 n \n".encode()
            output += (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_at}\n%%EOF"
            ).encode()
            return bytes(output)

        from io import BytesIO

        from pypdf import PdfWriter

        with tempfile.TemporaryDirectory() as directory:
            text_pdf = Path(directory) / "brief.pdf"
            text_pdf.write_bytes(build_text_pdf("Quarterly delivery brief"))
            self.assertIn("Quarterly delivery brief", _extract_pdf_text(text_pdf))

            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            buffer = BytesIO()
            writer.write(buffer)
            blank_pdf = Path(directory) / "blank.pdf"
            blank_pdf.write_bytes(buffer.getvalue())
            self.assertEqual(_extract_pdf_text(blank_pdf), "")

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

    def test_mcp_tool_listing_matches_workspace_role_permissions(self):
        viewer = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "mcp-viewer@example.com",
                "password": TEST_PASSWORD,
                "display_name": "MCP Viewer",
                "workspace_name": "Viewer home",
            },
        )
        self.assertEqual(viewer.status_code, 201, viewer.text)
        joined = self.client.post(
            f"/api/v1/workspaces/{self.owner_workspace}/members",
            headers=self.auth_headers(self.owner_token, self.owner_workspace),
            json={"email": "mcp-viewer@example.com", "role": "viewer"},
        )
        self.assertEqual(joined.status_code, 201, joined.text)

        discovered = {
            "name": "local_tools",
            "url": "http://mcp.invalid/mcp",
            "status": "online",
            "tools": [
                "list_files",
                "read_file",
                "write_file",
                "edit_file",
                "read_csv",
                "fetch_url",
                "web_search",
            ],
        }
        probe = AsyncMock(
            side_effect=[
                [{**discovered, "tools": list(discovered["tools"])}],
                [{**discovered, "tools": list(discovered["tools"])}],
            ]
        )
        with (
            patch.object(settings, "enable_local_mcp_tools", True),
            patch("api.routes.MCPManager.list_servers", probe),
        ):
            owner = self.client.get(
                "/api/v1/mcp/servers?probe=true",
                headers=self.auth_headers(self.owner_token, self.owner_workspace),
            )
            viewer_result = self.client.get(
                "/api/v1/mcp/servers?probe=true",
                headers=self.auth_headers(
                    viewer.json()["access_token"], self.owner_workspace
                ),
            )

        self.assertEqual(owner.status_code, 200, owner.text)
        self.assertEqual(viewer_result.status_code, 200, owner.text)
        self.assertEqual(set(owner.json()["servers"][0]["tools"]), set(discovered["tools"]))
        self.assertEqual(
            set(viewer_result.json()["servers"][0]["tools"]),
            {"list_files", "read_file", "read_csv", "fetch_url", "web_search"},
        )

    def test_conversation_message_pagination(self):
        headers = self.auth_headers(self.owner_token, self.owner_workspace)
        created = self.client.post(
            "/api/v1/conversations",
            json={"title": "分页样例对话"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        conversation_id = created.json()["conversation"]["id"]
        for index in range(8):
            message = ChatMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=f"历史消息 {index}",
            )
            with Session(database.engine) as session:
                session.add(message)
                session.commit()

        full = self.client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=headers,
        )
        self.assertEqual(full.status_code, 200, full.text)
        self.assertFalse(full.json()["has_more"])
        self.assertEqual(len(full.json()["messages"]), 8)

        page = self.client.get(
            f"/api/v1/conversations/{conversation_id}/messages?limit=3",
            headers=headers,
        )
        self.assertEqual(page.status_code, 200, page.text)
        payload = page.json()
        self.assertTrue(payload["has_more"])
        self.assertEqual(len(payload["messages"]), 3)
        self.assertEqual(payload["messages"][0]["content"], "历史消息 5")
        self.assertEqual(payload["messages"][-1]["content"], "历史消息 7")

        anchor = payload["messages"][-1]["id"]
        older = self.client.get(
            f"/api/v1/conversations/{conversation_id}/messages?limit=3&before_id={anchor}",
            headers=headers,
        )
        self.assertEqual(older.status_code, 200, older.text)
        older_payload = older.json()
        self.assertEqual(len(older_payload["messages"]), 3)
        self.assertEqual(older_payload["messages"][0]["content"], "历史消息 4")
        self.assertTrue(older_payload["has_more"])

    def test_workspace_search_scopes_and_types(self):
        headers = self.auth_headers(self.owner_token, self.owner_workspace)
        project = self.client.post(
            "/api/v1/projects",
            json={"name": "搜索样例项目", "description": "用于验证全局搜索"},
            headers=headers,
        )
        self.assertEqual(project.status_code, 201, project.text)
        project_id = project.json()["project"]["id"]
        task = self.client.post(
            "/api/v1/tasks",
            json={"title": "搜索样例任务", "project_id": project_id, "labels": ["检索"]},
            headers=headers,
        )
        self.assertEqual(task.status_code, 201, task.text)
        conversation = self.client.post(
            "/api/v1/conversations",
            json={"title": "搜索样例对话"},
            headers=headers,
        )
        conversation_id = conversation.json()["conversation"]["id"]
        with Session(database.engine) as session:
            session.add(
                ChatMessage(
                    conversation_id=conversation_id,
                    role="assistant",
                    content="这句话里藏着搜索样例关键词。",
                )
            )
            session.commit()

        result = self.client.get(
            "/api/v1/search?q=%E6%90%9C%E7%B4%A2%E6%A0%B7%E4%BE%8B",
            headers=headers,
        )
        self.assertEqual(result.status_code, 200, result.text)
        found = {item["type"] for item in result.json()["results"]}
        self.assertIn("project", found)
        self.assertIn("task", found)
        self.assertIn("conversation", found)
        self.assertIn("message", found)

        unrelated = self.client.get(
            "/api/v1/search?q=%E4%B8%8D%E5%AD%98%E5%9C%A8%E7%9A%84%E5%85%B3%E9%94%AE%E8%AF%8D",
            headers=self.auth_headers(self.owner_token, self.owner_workspace),
        )
        self.assertEqual(unrelated.status_code, 200, unrelated.text)
        self.assertEqual(unrelated.json()["results"], [])

    def test_task_comments_flow_and_permission(self):
        headers = self.auth_headers(self.owner_token, self.owner_workspace)
        # 独立成员账号，避免污染其它测试的隔离断言
        commenter = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "comment-member@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Comment Member",
                "workspace_name": "Commenter home",
            },
        )
        self.assertEqual(commenter.status_code, 201, commenter.text)
        commenter_id = commenter.json()["user"]["id"]
        commenter_token = commenter.json()["access_token"]
        joined = self.client.post(
            f"/api/v1/workspaces/{self.owner_workspace}/members",
            json={"email": "comment-member@example.com", "role": "member"},
            headers=headers,
        )
        self.assertIn(joined.status_code, {200, 201})
        project = self.client.post(
            "/api/v1/projects",
            json={"name": "评论样例项目"},
            headers=headers,
        )
        project_id = project.json()["project"]["id"]
        task = self.client.post(
            "/api/v1/tasks",
            json={"title": "评论样例任务", "project_id": project_id, "assignee_id": commenter_id},
            headers=headers,
        )
        self.assertEqual(task.status_code, 201, task.text)
        task_id = task.json()["task"]["id"]

        created = self.client.post(
            f"/api/v1/tasks/{task_id}/comments",
            json={"content": "请优先处理验收标准部分。"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["comment"]["author_name"], "Owner")

        member_headers = self.auth_headers(commenter_token, self.owner_workspace)
        listed = self.client.get(f"/api/v1/tasks/{task_id}/comments", headers=member_headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()["comments"]), 1)

        member_reply = self.client.post(
            f"/api/v1/tasks/{task_id}/comments",
            json={"content": "收到，明天给出初稿。"},
            headers=member_headers,
        )
        self.assertEqual(member_reply.status_code, 201, member_reply.text)

        # 被指派人应收到评论通知
        notifications = self.client.get(
            "/api/v1/notifications",
            headers=member_headers,
        )
        comment_notifications = [
            item for item in notifications.json()["notifications"] if item["type"] == "task" and "新任务评论" in item["title"]
        ]
        self.assertTrue(comment_notifications)

        # viewer 不能评论
        viewer = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "comment-viewer2@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Comment Viewer",
                "workspace_name": "Viewer comments",
            },
        )
        viewer_token = viewer.json()["access_token"]
        self.client.post(
            f"/api/v1/workspaces/{self.owner_workspace}/members",
            json={"email": "comment-viewer@example.com", "role": "viewer"},
            headers=headers,
        )
        denied = self.client.post(
            f"/api/v1/tasks/{task_id}/comments",
            json={"content": "只读成员尝试评论"},
            headers=self.auth_headers(viewer_token, self.owner_workspace),
        )
        self.assertEqual(denied.status_code, 403)

    def test_conversation_delete_cascades_and_isolates(self):
        headers = self.auth_headers(self.owner_token, self.owner_workspace)
        created = self.client.post(
            "/api/v1/conversations",
            json={"title": "待删除对话"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        conversation_id = created.json()["conversation"]["id"]

        upload = self.client.post(
            "/api/v1/attachments",
            data={"conversation_id": conversation_id},
            files={"file": ("delete-me.txt", b"temporary attachment", "text/plain")},
            headers=headers,
        )
        self.assertEqual(upload.status_code, 201, upload.text)

        with Session(database.engine) as session:
            session.add(ChatMessage(conversation_id=conversation_id, role="assistant", content="临时消息"))
            session.commit()

        # 非所有者不可见也不可删除
        other = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "delete-outsider@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Delete Outsider",
                "workspace_name": "Outsider home",
            },
        )
        outsider_token = other.json()["access_token"]
        forbidden = self.client.delete(
            f"/api/v1/conversations/{conversation_id}",
            headers=self.auth_headers(outsider_token, self.owner_workspace),
        )
        self.assertIn(forbidden.status_code, {403, 404})

        deleted = self.client.delete(
            f"/api/v1/conversations/{conversation_id}",
            headers=headers,
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)

        gone = self.client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=headers,
        )
        self.assertEqual(gone.status_code, 404, gone.text)
        attachments_after = self.client.get(
            f"/api/v1/attachments?conversation_id={conversation_id}",
            headers=headers,
        )
        # 会话删除后，附件查询要么 404，要么返回空列表
        if attachments_after.status_code == 200:
            self.assertEqual(attachments_after.json()["attachments"], [])
        else:
            self.assertEqual(attachments_after.status_code, 404)


if __name__ == "__main__":
    unittest.main()
