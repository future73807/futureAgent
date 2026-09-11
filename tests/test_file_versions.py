"""工作区文件版本与差异分析接口的行为约束。"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

import db.database as database
from api.file_versions import _is_binary_path, _side_by_side_rows, _unified_lines
from main import app

TEST_PASSWORD = "S3ed-file-version-tests!"


class DiffRenderingTests(unittest.TestCase):
    def test_unified_diff_labels_versions_and_current_target(self):
        lines = _unified_lines("a\nb\n", "a\nc\n", "notes.md", 1, 2)
        self.assertIn("--- notes.md@v1", lines)
        self.assertIn("+++ notes.md@v2", lines)
        self.assertIn("-b", lines)
        self.assertIn("+c", lines)

        current = _unified_lines("a\n", "b\n", "notes.md", 1, 0)
        self.assertIn("+++ notes.md@current", current)

    def test_identical_content_produces_no_diff_lines(self):
        self.assertEqual(_unified_lines("same\n", "same\n", "n.md", 1, 2), [])

    def test_side_by_side_rows_classify_each_change(self):
        rows = _side_by_side_rows("a\nb\nc\n", "a\nB\nc\nd\n")
        kinds = [row["kind"] for row in rows]
        self.assertEqual(kinds, ["equal", "replace", "equal", "insert"])
        self.assertEqual(rows[1], {"kind": "replace", "left": "b", "right": "B"})
        self.assertEqual(rows[3], {"kind": "insert", "left": "", "right": "d"})

    def test_deletions_are_reported_on_the_left_side_only(self):
        rows = _side_by_side_rows("keep\ndrop\n", "keep\n")
        self.assertEqual(rows[1], {"kind": "delete", "left": "drop", "right": ""})

    def test_binary_extensions_are_not_offered_a_text_diff(self):
        for path in ("a.xlsx", "b.docx", "c.png", "d.pdf", "e.JPG"):
            self.assertTrue(_is_binary_path(path), path)
        for path in ("a.md", "b.txt", "c.csv", "d.json", "e.unknown"):
            self.assertFalse(_is_binary_path(path), path)


class DiffEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 内存 SQLite 每个连接都是空库，必须用临时文件库。
        cls.temp_dir = TemporaryDirectory()
        database.engine = create_engine(
            f"sqlite:///{Path(cls.temp_dir.name, 'diff-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        cls.client = TestClient(app)
        cls.client.__enter__()
        owner = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "diff-owner@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Diff Owner",
                "workspace_name": "Diff workspace",
            },
        )
        assert owner.status_code == 201, owner.text
        cls.token = owner.json()["access_token"]
        cls.workspace = owner.json()["workspaces"][0]["id"]

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        database.engine.dispose()
        cls.temp_dir.cleanup()

    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Workspace-ID": self.workspace,
        }

    def test_binary_path_reports_unavailable_diff_instead_of_garbage(self):
        versions = [{"version": 1, "size": 10, "sha256": "x", "snapshot": True}]
        with patch(
            "api.file_versions.fetch_file_versions", new=AsyncMock(return_value=versions)
        ):
            response = self.client.get(
                "/api/v1/workspace/files/diff",
                params={"path": "report.xlsx", "from": 1, "to": 0},
                headers=self.headers(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["diff_available"])
        self.assertIn("二进制", payload["reason"])
        self.assertEqual(payload["versions"], versions)

    def test_text_diff_is_generated_server_side(self):
        with (
            patch(
                "api.file_versions.fetch_version_text",
                new=AsyncMock(return_value="alpha\nbeta\n"),
            ),
            patch(
                "api.file_versions.fetch_current_text",
                new=AsyncMock(return_value="alpha\ngamma\n"),
            ),
        ):
            response = self.client.get(
                "/api/v1/workspace/files/diff",
                params={"path": "notes.md", "from": 1, "to": 0},
                headers=self.headers(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["diff_available"])
        self.assertTrue(payload["changed"])
        self.assertIn("-beta", payload["lines"])
        self.assertIn("+gamma", payload["lines"])

    def test_same_version_on_both_sides_is_rejected(self):
        response = self.client.get(
            "/api/v1/workspace/files/diff",
            params={"path": "notes.md", "from": 2, "to": 2},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_version_listing_is_passed_through_with_retention_note(self):
        versions = [{"version": 3, "size": 4, "sha256": "y", "snapshot": False}]
        with patch(
            "api.file_versions.fetch_file_versions", new=AsyncMock(return_value=versions)
        ):
            response = self.client.get(
                "/api/v1/workspace/files/versions",
                params={"path": "notes.md"},
                headers=self.headers(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["versions"], versions)
        self.assertTrue(payload["retention_note"])

    def test_tool_service_failure_is_translated_without_internal_detail(self):
        with patch(
            "api.file_versions.fetch_file_versions",
            new=AsyncMock(side_effect=RuntimeError("http://mcp:8050 refused")),
        ):
            response = self.client.get(
                "/api/v1/workspace/files/versions",
                params={"path": "notes.md"},
                headers=self.headers(),
            )
        self.assertEqual(response.status_code, 502, response.text)
        self.assertNotIn("8050", response.text)

    def test_missing_version_returns_404(self):
        with patch(
            "api.file_versions.fetch_version_text",
            new=AsyncMock(side_effect=FileNotFoundError("版本不存在: 9")),
        ):
            response = self.client.get(
                "/api/v1/workspace/files/diff",
                params={"path": "notes.md", "from": 9, "to": 0},
                headers=self.headers(),
            )
        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
