"""End-to-end tests for the authorised operating-agent MVP."""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, Session, create_engine, select

import db.database as database
from api.business_routes import BusinessRecordInput, _ingest_record
from config import settings
from db.models import BusinessDataSource, BusinessRecord, User, now_utc
from main import app


class _FirstResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class BusinessIngestConcurrencyTests(unittest.TestCase):
    def test_unique_conflict_reloads_existing_record_as_idempotent_receipt(self):
        source = BusinessDataSource(
            id="source-1",
            workspace_id="workspace-1",
            name="受控接口",
            source_type="api",
            connection_mode="api",
            created_by="owner-1",
        )
        existing = BusinessRecord(
            id="record-existing",
            workspace_id="workspace-1",
            source_id="source-1",
            external_id="external-1",
            record_type="production_daily",
            title="已有记录",
            occurred_on=date.today(),
            occurred_at=now_utc(),
            ingest_batch_id="batch-existing",
        )
        session = MagicMock()
        session.exec.side_effect = [_FirstResult(None), _FirstResult(existing)]
        session.begin_nested.return_value = nullcontext()
        session.flush.side_effect = IntegrityError("insert", {}, Exception("unique conflict"))

        record, created, alerts = _ingest_record(
            session,
            source=source,
            entry=BusinessRecordInput(external_id="external-1", title="重试事件"),
            batch_id="batch-retry",
            actor_id=None,
            channel="authorised_ingest",
        )

        self.assertIs(record, existing)
        self.assertFalse(created)
        self.assertEqual(alerts, [])


class BusinessAgentApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_engine = database.engine
        cls.original_upload_dir = settings.upload_dir
        cls.original_storage_backend = settings.storage_backend
        settings.upload_dir = str(Path(cls.temp_dir.name) / "attachments")
        settings.storage_backend = "local"
        database.engine = create_engine(
            f"sqlite:///{Path(cls.temp_dir.name, 'business-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        cls.client = TestClient(app)
        cls.client.__enter__()

        cls.owner_token, cls.owner_id, cls.owner_workspace = cls._register(
            "business-owner@example.com", "Business owner", "Business workspace"
        )
        cls.member_token, cls.member_id, _ = cls._register(
            "business-member@example.com", "Business member", "Member workspace"
        )
        cls.outsider_token, cls.outsider_id, cls.outsider_workspace = cls._register(
            "business-outsider@example.com", "Business outsider", "Outsider workspace"
        )
        cls.audit_admin_token, cls.audit_admin_id, _ = cls._register(
            "business-audit-admin@example.com", "Business audit admin", "Audit admin workspace"
        )
        joined = cls.client.post(
            f"/api/v1/workspaces/{cls.owner_workspace}/members",
            headers=cls.headers(cls.owner_token, cls.owner_workspace),
            json={"email": "business-member@example.com", "role": "member"},
        )
        assert joined.status_code == 201, joined.text
        cls.member_membership_id = joined.json()["member"]["id"]
        audit_admin = cls.client.post(
            f"/api/v1/workspaces/{cls.owner_workspace}/members",
            headers=cls.headers(cls.owner_token, cls.owner_workspace),
            json={"email": "business-audit-admin@example.com", "role": "admin"},
        )
        assert audit_admin.status_code == 201, audit_admin.text

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        database.engine.dispose()
        database.engine = cls.original_engine
        settings.upload_dir = cls.original_upload_dir
        settings.storage_backend = cls.original_storage_backend
        cls.temp_dir.cleanup()

    @classmethod
    def _register(cls, email: str, display_name: str, workspace_name: str):
        response = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "BusinessPass123!",
                "display_name": display_name,
                "workspace_name": workspace_name,
            },
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        return payload["access_token"], payload["user"]["id"], payload["workspaces"][0]["id"]

    @classmethod
    def headers(cls, token: str, workspace_id: str):
        return {"Authorization": f"Bearer {token}", "X-Workspace-ID": workspace_id}

    def _create_api_source(self, *, source_type: str = "oa") -> tuple[dict, str]:
        created = self.client.post(
            "/api/v1/business/data-sources",
            headers=self.headers(self.owner_token, self.owner_workspace),
            json={
                "name": f"已授权 {source_type} 数据源",
                "source_type": source_type,
                "connection_mode": "api",
                "access_scope": "只读生产异常与日报字段",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        payload = created.json()
        self.assertIn("ingest_token", payload)
        self.assertIn("ingest_url", payload)
        return payload["data_source"], payload["ingest_token"]

    def _ingest(self, source_id: str, token: str, *, external_id: str, title: str, record_type: str = "production_daily"):
        return self.client.post(
            f"/api/v1/business/ingest/{source_id}",
            headers={"X-Business-Ingest-Token": token},
            json={
                "external_id": external_id,
                "record_type": record_type,
                "title": title,
                "content": "来自已授权业务系统的测试记录",
                "payload": {"line": "A", "count": 1},
                "occurred_on": date.today().isoformat(),
            },
        )

    def test_bootstrapped_assistants_and_private_history_are_strictly_isolated(self):
        owner = self.client.get(
            "/api/v1/business/assistants",
            headers=self.headers(self.owner_token, self.owner_workspace),
        )
        self.assertEqual(owner.status_code, 200, owner.text)
        assistants = owner.json()["assistants"]
        self.assertEqual({item["assistant_type"] for item in assistants}, {"boss_private", "personal_private", "company_public"})
        boss = next(item for item in assistants if item["assistant_type"] == "boss_private")

        chat = self.client.post(
            f"/api/v1/business/assistants/{boss['id']}/chat",
            headers=self.headers(self.owner_token, self.owner_workspace),
            json={"message": "今天有哪些经营异常？"},
        )
        self.assertEqual(chat.status_code, 200, chat.text)
        self.assertFalse(chat.json()["external_model_called"])
        self.assertEqual(chat.json()["engine"], "deterministic_authorized_data")

        history = self.client.get(
            f"/api/v1/business/assistants/{boss['id']}/messages",
            headers=self.headers(self.owner_token, self.owner_workspace),
        )
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual([item["role"] for item in history.json()["messages"][-2:]], ["user", "assistant"])

        member = self.client.get(
            "/api/v1/business/assistants",
            headers=self.headers(self.member_token, self.owner_workspace),
        )
        self.assertEqual(member.status_code, 200, member.text)
        self.assertEqual([item["assistant_type"] for item in member.json()["assistants"]], ["company_public"])
        denied = self.client.get(
            f"/api/v1/business/assistants/{boss['id']}/messages",
            headers=self.headers(self.member_token, self.owner_workspace),
        )
        self.assertEqual(denied.status_code, 404)

        # Becoming a platform administrator must not make a company member a
        # reader of the owner's private assistant history.
        with Session(database.engine) as session:
            member_user = session.get(User, self.member_id)
            member_user.is_platform_admin = True
            session.add(member_user)
            session.commit()
        still_denied = self.client.get(
            f"/api/v1/business/assistants/{boss['id']}/messages",
            headers=self.headers(self.member_token, self.owner_workspace),
        )
        self.assertEqual(still_denied.status_code, 404)

    def test_authorised_ingest_is_one_time_token_only_deduplicated_and_audited(self):
        source, token = self._create_api_source(source_type="production_report")
        self.assertNotIn("endpoint_url", source)
        self.assertNotIn("authorization_reference", source)
        self.assertNotIn("ingest_token_hash", source)

        with Session(database.engine) as session:
            persisted = session.get(BusinessDataSource, source["id"])
            self.assertIsNotNone(persisted)
            self.assertNotEqual(persisted.ingest_token_hash, token)
            self.assertTrue(persisted.ingest_token_hash)

        listed = self.client.get(
            "/api/v1/business/data-sources",
            headers=self.headers(self.member_token, self.owner_workspace),
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertNotIn(token, listed.text)
        self.assertNotIn("ingest_token_hash", listed.text)

        no_token = self.client.post(
            f"/api/v1/business/ingest/{source['id']}",
            json={"external_id": "missing-token", "title": "设备故障"},
        )
        self.assertEqual(no_token.status_code, 401)
        ingested = self._ingest(source["id"], token, external_id="line-a-001", title="设备故障，故障停机")
        self.assertEqual(ingested.status_code, 201, ingested.text)
        self.assertTrue(ingested.json()["created"])
        self.assertTrue(ingested.json()["alerts"])
        self.assertTrue(ingested.json()["record"]["ingest_batch_id"])
        duplicate = self._ingest(source["id"], token, external_id="line-a-001", title="设备故障，故障停机")
        self.assertEqual(duplicate.status_code, 201, duplicate.text)
        self.assertFalse(duplicate.json()["created"])
        self.assertEqual(duplicate.json()["receipt"], {"external_id": "line-a-001", "created": False})
        self.assertNotIn("record", duplicate.json())

        oversized_payload = self.client.post(
            f"/api/v1/business/ingest/{source['id']}",
            headers={"X-Business-Ingest-Token": token},
            json={
                "external_id": "oversized-payload",
                "title": "不应入库的大负载",
                "payload": {"raw": "x" * 50001},
            },
        )
        self.assertEqual(oversized_payload.status_code, 422)

        employee_submission = self.client.post(
            f"/api/v1/business/data-sources/{source['id']}/records",
            headers=self.headers(self.member_token, self.owner_workspace),
            json={"external_id": "member-cannot-write", "title": "测试"},
        )
        self.assertEqual(employee_submission.status_code, 403)

        audit = self.client.get(
            "/api/v1/audit-events",
            headers=self.headers(self.owner_token, self.owner_workspace),
        )
        self.assertEqual(audit.status_code, 200, audit.text)
        self.assertIn("business.record.ingested", {event["action"] for event in audit.json()["events"]})
        self.assertNotIn(token, audit.text)

    def test_reports_alerts_boss_tasks_and_cross_workspace_links_are_protected(self):
        source, token = self._create_api_source(source_type="oa")
        ingested = self._ingest(source["id"], token, external_id=f"report-{source['id']}", title="生产异常：交期延误")
        self.assertEqual(ingested.status_code, 201, ingested.text)
        alert_id = ingested.json()["alerts"][0]["id"]

        report = self.client.post(
            "/api/v1/business/daily-reports/generate",
            headers=self.headers(self.owner_token, self.owner_workspace),
            json={"report_date": date.today().isoformat()},
        )
        self.assertEqual(report.status_code, 200, report.text)
        self.assertTrue(report.json()["daily_report"]["metrics"]["filters"]["private_records_excluded"])
        member_reports = self.client.get(
            "/api/v1/business/daily-reports",
            headers=self.headers(self.member_token, self.owner_workspace),
        )
        self.assertEqual(member_reports.status_code, 200, member_reports.text)
        self.assertTrue(member_reports.json()["daily_reports"])

        acknowledged = self.client.post(
            f"/api/v1/business/alerts/{alert_id}/acknowledge",
            headers=self.headers(self.member_token, self.owner_workspace),
            json={},
        )
        self.assertEqual(acknowledged.status_code, 200, acknowledged.text)
        self.assertEqual(acknowledged.json()["alert"]["status"], "acknowledged")
        member_resolve = self.client.post(
            f"/api/v1/business/alerts/{alert_id}/resolve",
            headers=self.headers(self.member_token, self.owner_workspace),
            json={},
        )
        self.assertEqual(member_resolve.status_code, 403)
        owner_resolve = self.client.post(
            f"/api/v1/business/alerts/{alert_id}/resolve",
            headers=self.headers(self.owner_token, self.owner_workspace),
            json={},
        )
        self.assertEqual(owner_resolve.status_code, 200, owner_resolve.text)
        self.assertEqual(owner_resolve.json()["alert"]["status"], "resolved")
        admin_resolve = self.client.post(
            f"/api/v1/business/alerts/{alert_id}/resolve",
            headers=self.headers(self.audit_admin_token, self.owner_workspace),
            json={},
        )
        self.assertEqual(admin_resolve.status_code, 200, admin_resolve.text)

        created_task = self.client.post(
            "/api/v1/business/tasks",
            headers=self.headers(self.owner_token, self.owner_workspace),
            json={
                "title": "核实设备异常",
                "description": "联系现场负责人并回报",
                "priority": "high",
                "assignee_id": self.member_id,
                "alert_id": alert_id,
            },
        )
        self.assertEqual(created_task.status_code, 201, created_task.text)
        task_id = created_task.json()["task"]["id"]
        member_tasks = self.client.get(
            "/api/v1/business/tasks",
            headers=self.headers(self.member_token, self.owner_workspace),
        )
        self.assertEqual(member_tasks.status_code, 200, member_tasks.text)
        self.assertIn(task_id, {task["id"] for task in member_tasks.json()["tasks"]})
        progress = self.client.patch(
            f"/api/v1/business/tasks/{task_id}",
            headers=self.headers(self.member_token, self.owner_workspace),
            json={"status": "in_progress", "progress_note": "正在现场核实"},
        )
        self.assertEqual(progress.status_code, 200, progress.text)
        forbidden_title = self.client.patch(
            f"/api/v1/business/tasks/{task_id}",
            headers=self.headers(self.member_token, self.owner_workspace),
            json={"title": "员工不应改标题"},
        )
        self.assertEqual(forbidden_title.status_code, 403)
        member_create = self.client.post(
            "/api/v1/business/tasks",
            headers=self.headers(self.member_token, self.owner_workspace),
            json={"title": "员工不能下达老板任务"},
        )
        self.assertEqual(member_create.status_code, 403)

        outsider_source = self.client.post(
            "/api/v1/business/data-sources",
            headers=self.headers(self.outsider_token, self.outsider_workspace),
            json={"name": "外部系统", "source_type": "oa", "connection_mode": "api", "access_scope": "只读"},
        )
        self.assertEqual(outsider_source.status_code, 201, outsider_source.text)
        cross_workspace = self.client.post(
            "/api/v1/business/alerts",
            headers=self.headers(self.owner_token, self.owner_workspace),
            json={"title": "非法跨工作区关联", "source_id": outsider_source.json()["data_source"]["id"]},
        )
        self.assertEqual(cross_workspace.status_code, 404)

    def test_report_assistant_data_knowledge_reports_and_chat_flow(self):
        """Exercise the report-assistant surface that is separate from business routes."""
        owner_headers = self.headers(self.owner_token, self.owner_workspace)

        dashboard = self.client.get("/api/v1/report/dashboard", headers=owner_headers)
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertEqual(dashboard.json()["summary_engine"], "deterministic_authorized_data")

        source_response = self.client.post(
            "/api/v1/report/data-sources",
            headers=owner_headers,
            json={
                "name": "汇报验收数据源",
                "source_type": "api",
                "connection_mode": "api",
                "access_scope": "只读汇报字段",
            },
        )
        self.assertEqual(source_response.status_code, 201, source_response.text)
        source_payload = source_response.json()
        source_id = source_payload["data_source"]["id"]
        ingest_token = source_payload["ingest_token"]
        self.assertNotIn(ingest_token, json.dumps(source_payload["data_source"], ensure_ascii=False))

        ingested = self.client.post(
            f"/api/v1/report/ingest/{source_id}",
            headers={"X-Report-Ingest-Token": ingest_token},
            json={
                "external_id": "report-flow-1",
                "record_type": "production_daily",
                "title": "生产正常，日报已提交",
                "content": "产线 A 已完成当日计划。",
                "payload": {"line": "A", "completed": True},
                "occurred_on": date.today().isoformat(),
            },
        )
        self.assertEqual(ingested.status_code, 201, ingested.text)
        self.assertTrue(ingested.json()["created"])

        duplicate = self.client.post(
            f"/api/v1/report/ingest/{source_id}",
            headers={"X-Report-Ingest-Token": ingest_token},
            json={
                "external_id": "report-flow-1",
                "record_type": "production_daily",
                "title": "重复提交不应覆盖",
                "occurred_on": date.today().isoformat(),
            },
        )
        self.assertEqual(duplicate.status_code, 201, duplicate.text)
        self.assertFalse(duplicate.json()["created"])
        self.assertNotIn("record", duplicate.json())

        knowledge = self.client.post(
            "/api/v1/report/knowledge-bases",
            headers=owner_headers,
            json={
                "title": "验收运行手册",
                "description": "汇报智能体知识库验收",
                "content": "产线 A 的升级流程需要人工复核。",
            },
        )
        self.assertEqual(knowledge.status_code, 201, knowledge.text)
        knowledge_id = knowledge.json()["knowledge_base"]["id"]

        uploaded = self.client.post(
            "/api/v1/report/knowledge-bases/upload",
            headers=owner_headers,
            data={"title": "上传验收文档", "description": "multipart 路径"},
            files={"file": ("runbook.md", "# Runbook\nAll systems ready.".encode(), "text/markdown")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        uploaded_id = uploaded.json()["knowledge_base"]["id"]
        self.assertEqual(uploaded.json()["knowledge_base"]["file_name"], "runbook.md")
        self.assertIn("All systems ready", uploaded.json()["knowledge_base"]["content"])

        unsupported_upload = self.client.post(
            "/api/v1/report/knowledge-bases/upload",
            headers=owner_headers,
            files={"file": ("manual.pdf", b"%PDF-1.7", "application/pdf")},
        )
        self.assertEqual(unsupported_upload.status_code, 415, unsupported_upload.text)

        oversized_upload = self.client.post(
            "/api/v1/report/knowledge-bases/upload",
            headers=owner_headers,
            files={"file": ("oversized.txt", b"x" * 100_001, "text/plain")},
        )
        self.assertEqual(oversized_upload.status_code, 413, oversized_upload.text)

        daily = self.client.post(
            "/api/v1/report/daily-reports/generate",
            headers=owner_headers,
            json={"report_date": date.today().isoformat()},
        )
        self.assertEqual(daily.status_code, 200, daily.text)
        self.assertGreaterEqual(daily.json()["daily_report"]["metrics"]["record_count"], 1)

        invalid_week = self.client.post(
            "/api/v1/report/weekly-reports/generate",
            headers=owner_headers,
            json={
                "week_start_date": "2026-08-10",
                "week_end_date": "2026-08-09",
            },
        )
        self.assertEqual(invalid_week.status_code, 422, invalid_week.text)

        weekly = self.client.post(
            "/api/v1/report/weekly-reports/generate",
            headers=owner_headers,
            json={
                "week_start_date": date.today().isoformat(),
                "week_end_date": date.today().isoformat(),
                "title": "验收周报",
            },
        )
        self.assertEqual(weekly.status_code, 200, weekly.text)
        self.assertEqual(weekly.json()["weekly_report"]["title"], "验收周报")

        chat = self.client.post(
            "/api/v1/report/chat",
            headers=owner_headers,
            json={"message": "汇总今天的生产与知识库信息"},
        )
        self.assertEqual(chat.status_code, 200, chat.text)
        self.assertFalse(chat.json()["external_model_called"])
        self.assertEqual(chat.json()["engine"], "deterministic_authorized_data")
        self.assertTrue(chat.json()["assistant_message"]["citations"])

        history = self.client.get("/api/v1/report/messages", headers=owner_headers)
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual([item["role"] for item in history.json()["messages"][-2:]], ["user", "assistant"])

        for kb_id in (knowledge_id, uploaded_id):
            deleted = self.client.delete(
                f"/api/v1/report/knowledge-bases/{kb_id}", headers=owner_headers
            )
            self.assertEqual(deleted.status_code, 204, deleted.text)

    def test_private_source_and_ownership_transfer_cannot_be_bypassed(self):
        private_source = self.client.post(
            "/api/v1/business/data-sources",
            headers=self.headers(self.owner_token, self.owner_workspace),
            json={
                "name": "老板私密授权源",
                "source_type": "custom_api",
                "connection_mode": "api",
                "data_scope": "boss_private",
                "access_scope": "仅老板私事事项",
            },
        )
        self.assertEqual(private_source.status_code, 201, private_source.text)
        source_id = private_source.json()["data_source"]["id"]
        private_token = private_source.json()["ingest_token"]
        first_private_record = self._ingest(
            source_id,
            private_token,
            external_id="private-repeat-id",
            title="老板私事内容不得回显",
            record_type="private_note",
        )
        self.assertEqual(first_private_record.status_code, 201, first_private_record.text)
        duplicate_private_record = self._ingest(
            source_id,
            private_token,
            external_id="private-repeat-id",
            title="伪造标题",
            record_type="private_note",
        )
        self.assertEqual(duplicate_private_record.status_code, 201, duplicate_private_record.text)
        self.assertEqual(
            duplicate_private_record.json()["receipt"],
            {"external_id": "private-repeat-id", "created": False},
        )
        self.assertNotIn("老板私事内容不得回显", duplicate_private_record.text)
        self.assertNotIn("payload", duplicate_private_record.text)
        member_sources = self.client.get(
            "/api/v1/business/data-sources",
            headers=self.headers(self.member_token, self.owner_workspace),
        )
        self.assertEqual(member_sources.status_code, 200, member_sources.text)
        self.assertNotIn(source_id, {item["id"] for item in member_sources.json()["data_sources"]})
        private_patch = self.client.patch(
            f"/api/v1/business/data-sources/{source_id}",
            headers=self.headers(self.member_token, self.owner_workspace),
            json={"enabled": False},
        )
        self.assertEqual(private_patch.status_code, 403)

        owner_audit = self.client.get(
            "/api/v1/audit-events",
            headers=self.headers(self.owner_token, self.owner_workspace),
        )
        self.assertEqual(owner_audit.status_code, 200, owner_audit.text)
        self.assertIn(source_id, owner_audit.text)

        workspace_admin_audit = self.client.get(
            "/api/v1/audit-events",
            headers=self.headers(self.audit_admin_token, self.owner_workspace),
        )
        self.assertEqual(workspace_admin_audit.status_code, 200, workspace_admin_audit.text)
        self.assertNotIn(source_id, workspace_admin_audit.text)

        with Session(database.engine) as session:
            member_user = session.get(User, self.member_id)
            member_user.is_platform_admin = True
            session.add(member_user)
            session.commit()
        platform_audit = self.client.get(
            "/api/v1/admin/audit-events",
            headers=self.headers(self.member_token, self.owner_workspace),
        )
        self.assertEqual(platform_audit.status_code, 200, platform_audit.text)
        self.assertNotIn(source_id, platform_audit.text)

        # The default private assistants and any private source force an
        # explicit archival/handover before ownership can change.
        transfer = self.client.post(
            f"/api/v1/workspaces/{self.owner_workspace}/transfer-owner",
            headers=self.headers(self.owner_token, self.owner_workspace),
            json={"member_id": self.member_membership_id},
        )
        self.assertEqual(transfer.status_code, 409, transfer.text)
        self.assertIn("私事经营数据", transfer.json()["detail"])

    def test_ownership_transfer_relocks_default_private_assistants(self):
        joined = self.client.post(
            f"/api/v1/workspaces/{self.outsider_workspace}/members",
            headers=self.headers(self.outsider_token, self.outsider_workspace),
            json={"email": "business-audit-admin@example.com", "role": "member"},
        )
        self.assertEqual(joined.status_code, 201, joined.text)
        assistants = self.client.get(
            "/api/v1/business/assistants",
            headers=self.headers(self.outsider_token, self.outsider_workspace),
        )
        self.assertEqual(assistants.status_code, 200, assistants.text)
        former_owner_personal = next(
            item for item in assistants.json()["assistants"] if item["assistant_type"] == "personal_private"
        )
        transfer = self.client.post(
            f"/api/v1/workspaces/{self.outsider_workspace}/transfer-owner",
            headers=self.headers(self.outsider_token, self.outsider_workspace),
            json={"member_id": joined.json()["member"]["id"]},
        )
        self.assertEqual(transfer.status_code, 200, transfer.text)
        former_owner_read = self.client.post(
            f"/api/v1/business/assistants/{former_owner_personal['id']}/chat",
            headers=self.headers(self.outsider_token, self.outsider_workspace),
            json={"message": "原所有者不得继续读取私事助手"},
        )
        self.assertEqual(former_owner_read.status_code, 404)


if __name__ == "__main__":
    unittest.main()
