from __future__ import annotations

import json
import hashlib
import hmac
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from mcp.shared.memory import create_connected_server_and_client_session

from core.skill_manager import SkillManager
from mcp_server import server


def workspace_meta(workspace_id: str, key: str) -> dict[str, str]:
    signature = hmac.new(
        key.encode("utf-8"),
        workspace_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "futureagent_workspace": workspace_id,
        "futureagent_workspace_signature": signature,
    }


class WorkspaceToolTests(unittest.TestCase):
    def test_file_tools_round_trip_and_reject_path_escape(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "WORKSPACE_ROOT", Path(directory).resolve()
        ):
            result = server.write_file("notes/result.txt", "hello")
            self.assertIn("notes/result.txt", result)
            self.assertEqual(server.read_file("notes/result.txt"), "hello")
            self.assertEqual(server.list_files("notes")[0]["name"], "result.txt")
            with self.assertRaises(ValueError):
                server.read_file("../outside.txt")
            with self.assertRaises(ValueError):
                server.write_file("../outside.txt", "blocked")

    def test_edit_file_is_exact_bounded_and_non_destructive_on_error(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "WORKSPACE_ROOT", Path(directory).resolve()),
            patch.object(server, "MAX_FILE_SIZE", 30),
        ):
            server.write_file("notes.txt", "alpha\nbeta\nbeta\n")

            with self.assertRaisesRegex(ValueError, "出现 2 次"):
                server.edit_file("notes.txt", "beta", "changed")
            self.assertEqual(server.read_file("notes.txt"), "alpha\nbeta\nbeta\n")

            result = server.edit_file(
                "notes.txt", "beta", "changed", replace_all=True
            )
            self.assertEqual(result["replacements"], 2)
            self.assertEqual(server.read_file("notes.txt"), "alpha\nchanged\nchanged\n")

            with self.assertRaisesRegex(ValueError, "未找到"):
                server.edit_file("notes.txt", "missing", "value")
            with self.assertRaisesRegex(ValueError, "超过"):
                server.edit_file("notes.txt", "alpha", "x" * 30)
            self.assertEqual(server.read_file("notes.txt"), "alpha\nchanged\nchanged\n")

    def test_read_and_write_file_size_limits_leave_no_partial_file(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "WORKSPACE_ROOT", Path(directory).resolve()),
            patch.object(server, "MAX_FILE_SIZE", 8),
        ):
            with self.assertRaisesRegex(ValueError, "超过"):
                server.write_file("too-large.txt", "123456789")
            self.assertFalse((Path(directory) / "too-large.txt").exists())

            oversized = Path(directory) / "external.txt"
            oversized.write_bytes(b"123456789")
            with self.assertRaisesRegex(ValueError, "超过"):
                server.read_file("external.txt")

    def test_csv_reader_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "WORKSPACE_ROOT", Path(directory).resolve()
        ):
            server.write_file("data.csv", "name,value\na,1\nb,2\n")
            result = server.read_csv("data.csv", limit=1)
            self.assertEqual(result["columns"], ["name", "value"])
            self.assertEqual(result["rows"], [{"name": "a", "value": "1"}])


class WebToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_rejects_loopback_before_opening_http_client(self):
        with self.assertRaisesRegex(ValueError, "本地或私有"):
            await server.fetch_url("http://127.0.0.1/private")

    async def test_search_returns_normalized_public_results(self):
        page = """
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs">
          Example documentation
        </a>
        <a class="result__snippet">A concise result summary.</a>
        """

        async def fake_fetch(_url, *, preserve_html=False):
            self.assertTrue(preserve_html)
            return {"text": page}

        with patch.object(server, "_fetch_web_resource", fake_fetch):
            result = await server.web_search("futureAgent", limit=3)

        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["provider"], "duckduckgo_html")
        self.assertEqual(result["results"][0]["url"], "https://example.com/docs")
        self.assertIn("concise result", result["results"][0]["snippet"])

    async def test_search_failure_has_actionable_diagnostic_without_api_key(self):
        async def unavailable(_url, *, preserve_html=False):
            raise OSError("upstream detail")

        with patch.object(server, "_fetch_web_resource", unavailable):
            with self.assertRaisesRegex(RuntimeError, "无需 API 密钥"):
                await server.web_search("futureAgent")

    async def test_fake_ip_dns_range_requires_explicit_opt_in(self):
        records = [(2, 1, 6, "", ("198.18.1.2", 443))]
        with (
            patch.object(server.socket, "getaddrinfo", return_value=records),
            patch.object(server, "ALLOW_DNS_FAKE_IPS", False),
        ):
            with self.assertRaisesRegex(ValueError, "本地或私有"):
                await server._resolve_public_url("https://example.test/")

        with (
            patch.object(server.socket, "getaddrinfo", return_value=records),
            patch.object(server, "ALLOW_DNS_FAKE_IPS", True),
        ):
            target = await server._resolve_public_url("https://example.test/")
        self.assertEqual(target.connect_url, "https://198.18.1.2/")

    async def test_fetch_connects_to_the_validated_ip_without_second_dns_lookup(self):
        dns_calls = []
        captured = {}

        def changing_dns(*_args):
            dns_calls.append(True)
            address = "93.184.216.34" if len(dns_calls) == 1 else "127.0.0.1"
            return [(2, 1, 6, "", (address, 443))]

        class FakeResponse:
            status_code = 200
            headers = {"content-type": "text/plain; charset=utf-8"}
            encoding = "utf-8"

            async def aiter_bytes(self):
                yield b"pinned"

        class FakeStream:
            async def __aenter__(self):
                return FakeResponse()

            async def __aexit__(self, *_args):
                return False

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            def stream(self, method, url, **kwargs):
                captured.update({"method": method, "url": url, **kwargs})
                return FakeStream()

        with (
            patch.object(server.socket, "getaddrinfo", changing_dns),
            patch.object(server.httpx, "AsyncClient", FakeClient),
        ):
            result = await server.fetch_url("https://example.test/docs?q=1")

        self.assertEqual(len(dns_calls), 1)
        self.assertEqual(captured["url"], "https://93.184.216.34/docs?q=1")
        self.assertEqual(captured["headers"]["Host"], "example.test")
        self.assertEqual(captured["extensions"]["sni_hostname"], "example.test")
        self.assertEqual(result["url"], "https://example.test/docs?q=1")
        self.assertEqual(result["text"], "pinned")

    def test_builtin_server_registers_file_and_network_tools(self):
        names = {tool.name for tool in server.mcp._tool_manager.list_tools()}
        self.assertTrue(
            {
                "list_files",
                "read_file",
                "write_file",
                "edit_file",
                "read_csv",
                "fetch_url",
                "web_search",
            }.issubset(names)
        )


class McpProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_list_and_call_tools_over_mcp_protocol(self):
        signing_key = "protocol-test-signing-key"
        meta = workspace_meta("workspace-a", signing_key)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "WORKSPACE_ROOT", Path(directory).resolve()),
            patch.object(server, "WORKSPACE_SIGNING_KEY", signing_key),
        ):
            async with create_connected_server_and_client_session(
                server.mcp,
                read_timeout_seconds=timedelta(seconds=5),
                raise_exceptions=True,
            ) as session:
                response = await session.list_tools()
                names = {tool.name for tool in response.tools}
                self.assertIn("edit_file", names)

                written = await session.call_tool(
                    "write_file",
                    {"path": "protocol.txt", "content": "before"},
                    meta=meta,
                )
                self.assertFalse(written.isError)
                edited = await session.call_tool(
                    "edit_file",
                    {
                        "path": "protocol.txt",
                        "old_text": "before",
                        "new_text": "after",
                    },
                    meta=meta,
                )
                self.assertFalse(edited.isError)
                read = await session.call_tool(
                    "read_file", {"path": "protocol.txt"}, meta=meta
                )
                self.assertFalse(read.isError)
                self.assertEqual(read.content[0].text, "after")

    async def test_file_tools_reject_forged_scope_and_isolate_workspaces(self):
        signing_key = "tenant-isolation-test-key"
        workspace_a = workspace_meta("workspace-a", signing_key)
        workspace_b = workspace_meta("workspace-b", signing_key)
        forged = {
            "futureagent_workspace": "workspace-a",
            "futureagent_workspace_signature": "0" * 64,
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "WORKSPACE_ROOT", Path(directory).resolve()),
            patch.object(server, "WORKSPACE_SIGNING_KEY", signing_key),
        ):
            async with create_connected_server_and_client_session(
                server.mcp,
                read_timeout_seconds=timedelta(seconds=5),
                raise_exceptions=True,
            ) as session:
                written = await session.call_tool(
                    "write_file",
                    {"path": "private.txt", "content": "workspace-a-only"},
                    meta=workspace_a,
                )
                self.assertFalse(written.isError)

                other_workspace = await session.call_tool(
                    "read_file", {"path": "private.txt"}, meta=workspace_b
                )
                self.assertTrue(other_workspace.isError)

                forged_result = await session.call_tool(
                    "read_file", {"path": "private.txt"}, meta=forged
                )
                self.assertTrue(forged_result.isError)

                escaped = await session.call_tool(
                    "read_file", {"path": "../private.txt"}, meta=workspace_a
                )
                self.assertTrue(escaped.isError)


class PythonToolRegistrationTests(unittest.TestCase):
    def _tool_names_from_fresh_process(self, enabled: bool) -> set[str]:
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment["MCP_ENABLE_PYTHON_TOOL"] = "true" if enabled else "false"
            environment["MCP_WORKSPACE_ROOT"] = directory
            command = (
                "import json; from mcp_server.server import mcp; "
                "print(json.dumps(sorted(t.name for t in mcp._tool_manager.list_tools())))"
            )
            completed = subprocess.run(
                [sys.executable, "-c", command],
                cwd=Path(__file__).parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
            )
        return set(json.loads(completed.stdout.strip().splitlines()[-1]))

    def test_python_tool_is_default_off_and_registers_when_enabled(self):
        self.assertNotIn("run_python", self._tool_names_from_fresh_process(False))
        self.assertIn("run_python", self._tool_names_from_fresh_process(True))

    def test_python_tool_executes_and_enforces_timeout_and_output_bound(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "WORKSPACE_ROOT", Path(directory).resolve()
        ):
            completed = server.run_python("print(6 * 7)")
            self.assertEqual(completed["exit_code"], 0)
            self.assertEqual(completed["stdout"].strip(), "42")

            bounded = server.run_python("print('x' * 25000)")
            self.assertTrue(bounded["truncated"])
            self.assertLessEqual(len(bounded["stdout"]), server.MAX_OUTPUT_SIZE)

            with self.assertRaises(TimeoutError):
                server.run_python("import time; time.sleep(2)", timeout_seconds=1)


class BundledSkillMappingTests(unittest.TestCase):
    def test_skill_whitelists_only_reference_builtin_or_optional_tools(self):
        tool_names = {tool.name for tool in server.mcp._tool_manager.list_tools()}
        tool_names.add("run_python")  # optional, registered only when enabled
        manager = SkillManager(Path(__file__).parents[1] / "skills")
        for skill_name in ("chatbot", "coder", "data_analyst"):
            skill = manager.get_skill(skill_name)
            self.assertIsNotNone(skill)
            self.assertLessEqual(set(skill.allowed_tool_names), tool_names)

        coder = manager.get_skill("coder")
        self.assertTrue({"list_files", "edit_file"}.issubset(coder.allowed_tool_names))


if __name__ == "__main__":
    unittest.main()
