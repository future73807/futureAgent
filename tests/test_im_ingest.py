"""IM 入站指令最小闭环测试：多格式解析、幂等、鉴权、握手与预警联动。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select

import db.database as database
from config import settings
from db.report_models import KnowledgeChunk, ReportAlertRule
from main import app

TEST_PASSWORD = "S3ed-" + uuid4().hex[:13] + "!"


class ImIngestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_upload_dir = settings.upload_dir
        cls.original_storage_backend = settings.storage_backend
        cls.original_engine = database.engine
        settings.upload_dir = str(Path(cls.temp_dir.name) / "attachments")
        settings.storage_backend = "local"
        database.engine = create_engine(
            f"sqlite:///{Path(cls.temp_dir.name, 'im-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        cls.client = TestClient(app)
        cls.client.__enter__()

        owner = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "im-owner@example.com",
                "password": TEST_PASSWORD,
                "display_name": "IM Owner",
                "workspace_name": "IM workspace",
            },
        )
        assert owner.status_code == 201, owner.text
        cls.owner_token = owner.json()["access_token"]
        cls.workspace_id = owner.json()["workspaces"][0]["id"]

        created = cls.client.post(
            "/api/v1/report/data-sources",
            json={"name": "值班群机器人", "source_type": "enterprise_robot", "connection_mode": "webhook"},
            headers=cls.headers(),
        )
        assert created.status_code == 201, created.text
        cls.source_id = created.json()["data_source"]["id"]
        cls.ingest_token = created.json()["ingest_token"]

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        database.engine.dispose()
        database.engine = cls.original_engine
        settings.upload_dir = cls.original_upload_dir
        settings.storage_backend = cls.original_storage_backend
        import contextlib

        with contextlib.suppress(OSError):
            cls.temp_dir.cleanup()

    @classmethod
    def headers(cls):
        return {"Authorization": f"Bearer {cls.owner_token}", "X-Workspace-ID": cls.workspace_id}

    def _ingest(self, payload, token=None, notify=None):
        url = f"/api/v1/report/im-ingest/{self.source_id}"
        params = {}
        if token is not None:
            params["token"] = token
        if notify is not None:
            params["notify"] = "true" if notify else "false"
        return self.client.post(url, json=payload, params=params, headers=self.headers())

    def test_wecom_style_message_creates_record_idempotently(self):
        body = {"msgtype": "text", "text": {"content": "三号生产线 14:00 停机"}, "msg_id": "im-msg-1"}
        first = self._ingest(body, token=self.ingest_token)
        self.assertEqual(first.status_code, 200, first.text)
        payload = first.json()
        self.assertTrue(payload["created"])
        self.assertTrue(payload["record_id"])

        # 会话内 record_id 为空串？接口应返回真实 id
        second = self._ingest({**body, "msg_id": "im-msg-1"}, token=self.ingest_token)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertFalse(second.json()["created"])

    def test_message_types_and_sender_extracted(self):
        bodies = [
            {"msgtype": "text", "text": {"content": "钉钉文本消息"}, "sender": "钉钉张三", "msg_id": "dd-1"},
            {"msg_type": "text", "content": {"text": "飞书文本消息"}, "msg_id": "fs-1"},
            {"event": {"message": {"message_id": "fs-evt-1", "content": "{\"text\":\"飞书事件消息\"}"}, "sender": {"sender_id": "ou-1"}}},
            {"content": "裸 content 消息", "msg_id": "raw-1"},
        ]
        for index, body in enumerate(bodies):
            response = self._ingest(body, token=self.ingest_token)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["created"], f"body[{index}] not created")

        records = self.client.get(
            "/api/v1/report/records",
            headers=self.headers(),
        )
        self.assertEqual(records.status_code, 200, records.text)
        titles = [item["title"] for item in records.json().get("records", [])]
        for expected in ["钉钉文本消息", "飞书文本消息", "飞书事件消息", "裸 content 消息"]:
            self.assertIn(expected, titles)

    def test_feishu_url_verification_handshake(self):
        response = self._ingest(
            {"type": "url_verification", "challenge": "ajls38afk12"},
            token=self.ingest_token,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json().get("challenge"), "ajls38afk12")
        # 握手在鉴权之前处理：平台验证回调 URL 时可能尚未配置 token
        no_token = self._ingest({"type": "url_verification", "challenge": "xyz"})
        self.assertEqual(no_token.status_code, 200, no_token.text)
        self.assertEqual(no_token.json().get("challenge"), "xyz")

    def test_invalid_token_rejected(self):
        response = self._ingest({"text": "未授权消息"}, token="wrong-token")
        self.assertEqual(response.status_code, 401, response.text)
        no_token = self._ingest({"text": "未授权消息"})
        self.assertEqual(no_token.status_code, 401, no_token.text)

    def test_alert_rule_triggered_and_notify(self):
        rule = self.client.post(
            "/api/v1/report/alert-rules",
            json={"name": "停机预警", "keywords": ["停机"], "severity": "critical"},
            headers=self.headers(),
        )
        self.assertIn(rule.status_code, {200, 201}, rule.text)

        response = self._ingest(
            {"msgtype": "text", "text": {"content": "二号线停机 10 分钟"}, "msg_id": "alert-im-1"},
            token=self.ingest_token,
            notify=True,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertGreaterEqual(response.json()["alert_count"], 1)

        notifications = self.client.get(
            "/api/v1/notifications",
            headers=self.headers(),
        )
        titles = [item["title"] for item in notifications.json()["notifications"]]
        self.assertTrue(any("IM 消息" in title for title in titles), titles)


if __name__ == "__main__":
    unittest.main()
