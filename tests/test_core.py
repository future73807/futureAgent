import hashlib
import hmac
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

from auth.auth_manager import AuthManager
from core.agent_engine import AgentEngine
from core.mcp_manager import MCPManager
from core import model_hub
from core.model_hub import ModelHub
from core.skill_manager import Skill, SkillManager
from config import Settings, settings
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from unittest.mock import patch


class SkillManagerTests(unittest.TestCase):
    def test_skill_crud_persists_yaml(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SkillManager(directory)
            skill = Skill(
                name="test_skill",
                description="测试技能",
                system_prompt="你是测试助手。",
                allowed_tool_names=["read_file"],
            )
            manager.save_skill(skill)
            self.assertEqual(SkillManager(directory).get_skill("test_skill"), skill)

            updated = skill.model_copy(update={"description": "更新后的技能"})
            manager.save_skill(updated, overwrite=True)
            self.assertEqual(
                SkillManager(directory).get_skill("test_skill").description,
                "更新后的技能",
            )

            self.assertTrue(manager.delete_skill("test_skill"))
            self.assertFalse((Path(directory) / "test_skill.yaml").exists())

    def test_default_skill_cannot_be_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SkillManager(directory)
            with self.assertRaises(ValueError):
                manager.delete_skill("default")


class AuthManagerTests(unittest.TestCase):
    def test_wildcards_and_policy_persistence(self):
        model = Path(__file__).parents[1] / "auth" / "rbac_model.conf"
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "policy.csv"
            policy.write_text(
                "p, admin, *, *\n"
                "p, developer, model:*, use\n"
                "g, admin, developer\n",
                encoding="utf-8",
            )
            manager = AuthManager(str(model), str(policy))
            self.assertTrue(manager.is_allowed("admin", "anything", "delete"))
            self.assertTrue(manager.is_allowed("developer", "model:new-model", "use"))
            self.assertFalse(manager.is_allowed("developer", "skill:coder", "use"))
            self.assertTrue(manager.add_policy("developer", "skill:*", "use"))
            reloaded = AuthManager(str(model), str(policy))
            self.assertTrue(reloaded.is_allowed("developer", "skill:coder", "use"))


class AgentHelpersTests(unittest.TestCase):
    def test_content_blocks_are_converted_to_text(self):
        content = ["a", {"type": "text", "text": "b"}, {"type": "tool", "name": "x"}]
        self.assertEqual(AgentEngine._content_to_text(content), "ab")

    def test_completed_tool_message_is_recorded_as_a_bounded_trace(self):
        config = {"tool_trace": []}
        AgentEngine._record_tool_trace(
            config,
            ToolMessage(
                content="x" * 3_000,
                name="web_search",
                tool_call_id="call-1",
                status="success",
            ),
        )
        self.assertEqual(config["tool_trace"][0]["name"], "web_search")
        self.assertEqual(config["tool_trace"][0]["tool_call_id"], "call-1")
        self.assertEqual(len(config["tool_trace"][0]["result_preview"]), 2_000)


class ModelReadinessTests(unittest.TestCase):
    def test_placeholder_provider_key_is_not_a_ready_direct_route(self):
        with (
            patch.object(settings, "litellm_proxy_url", ""),
            patch.object(settings, "openai_api_key", "sk-your-openai-key"),
            patch.object(model_hub, "LITELLM_AVAILABLE", True),
        ):
            self.assertFalse(ModelHub.is_model_configured("gpt-4o-mini"))
            self.assertEqual(ModelHub.configuration_source("gpt-4o-mini"), "missing")
            self.assertIn("尚未配置", ModelHub.readiness_error("gpt-4o-mini"))

    def test_longcat_is_selectable_and_uses_openai_compatible_litellm_route(self):
        self.assertIn("LongCat-2.0", ModelHub.list_supported_models())
        self.assertEqual(
            ModelHub._litellm_model_name("LongCat-2.0"),
            "openai/LongCat-2.0",
        )

    def test_ollama_url_is_configured_but_not_ready_when_service_is_offline(self):
        ModelHub._ollama_models_cache.clear()
        with (
            patch.object(settings, "litellm_proxy_url", ""),
            patch.object(settings, "ollama_base_url", "http://127.0.0.1:11434"),
            patch.object(model_hub, "LITELLM_AVAILABLE", True),
            patch(
                "core.model_hub.httpx.Client",
                side_effect=model_hub.httpx.ConnectError("offline"),
            ),
        ):
            self.assertTrue(ModelHub.is_model_configured("ollama/llama3"))
            reason = ModelHub.readiness_error("ollama/llama3")
        self.assertIn("不可达", reason)


class AgentStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_stream_returns_only_model_text(self):
        class FakeModelHub:
            def get_chat_model(self, **_kwargs):
                return FakeListChatModel(responses=["hello"])

        with tempfile.TemporaryDirectory() as directory:
            engine = AgentEngine(
                model_hub=FakeModelHub(),
                mcp_manager=MCPManager({}),
                skill_manager=SkillManager(directory),
                auth_manager=AuthManager(),
            )
            chunks = []
            async for chunk in engine.run(
                "developer",
                "hi",
                {"model_id": "fake-model", "skill_name": "default", "mcp_servers": []},
            ):
                chunks.append(chunk)
            self.assertEqual("".join(chunks), "hello")


class McpProbeSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_hides_transport_exception_details(self):
        manager = MCPManager({})

        @asynccontextmanager
        async def unavailable(_server_name):
            raise RuntimeError("internal-hostname and secret-like-detail")
            yield None

        with patch.object(manager, "connect", unavailable):
            result = await manager._probe_server("local_tools", "http://internal/mcp")

        self.assertEqual(result["status"], "offline")
        self.assertEqual(result["error"], "服务探测失败，请检查地址、网络或鉴权配置。")
        self.assertNotIn("internal-hostname", result["error"])

    async def test_streamable_http_cleanup_does_not_wait_for_delete_termination(self):
        manager = MCPManager({"tools": "http://127.0.0.1:8050/mcp"})
        captured = {}

        @asynccontextmanager
        async def fake_transport(url, **kwargs):
            captured.update({"url": url, **kwargs})
            yield "read", "write", lambda: None

        with patch("core.mcp_manager.streamable_http_client", fake_transport):
            async with manager._open_transport("http://127.0.0.1:8050/mcp") as streams:
                self.assertEqual(streams, ("read", "write"))

        self.assertFalse(captured["terminate_on_close"])

    async def test_server_listing_redacts_embedded_credentials_and_query(self):
        manager = MCPManager(
            {"private": "https://user:secret@example.com/mcp?token=sensitive"}
        )
        result = await manager.list_servers()
        self.assertEqual(result[0]["url"], "https://example.com/mcp")
        self.assertNotIn("secret", result[0]["url"])


class McpConfigurationTests(unittest.TestCase):
    def test_explicit_empty_server_mapping_does_not_fall_back_to_settings(self):
        self.assertEqual(MCPManager({}).servers, {})

    def test_stable_server_names_and_urls_are_normalized(self):
        configured = Settings(
            _env_file=None,
            mcp_servers_json=(
                '{"local_tools":"http://127.0.0.1:9000",'
                '"legacy_sse":"https://example.com/sse"}'
            ),
        )
        self.assertEqual(
            configured.mcp_servers,
            {
                "local_tools": "http://127.0.0.1:9000/mcp",
                "legacy_sse": "https://example.com/sse",
            },
        )

    def test_hostname_with_explicit_port_is_not_given_a_second_port(self):
        configured = Settings(
            _env_file=None,
            mcp_servers_json="",
            mcp_hostnames_csv="localhost:9000",
        )
        self.assertEqual(
            configured.mcp_servers,
            {"localhost:9000": "http://localhost:9000/mcp"},
        )

    def test_invalid_server_name_and_scheme_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "服务名"):
            Settings(
                _env_file=None,
                mcp_servers_json='{"bad name":"http://localhost:8050/mcp"}',
            ).mcp_servers
        with self.assertRaisesRegex(ValueError, "HTTP"):
            Settings(
                _env_file=None,
                mcp_servers_json='{"bad":"ftp://example.com/tools"}',
            ).mcp_servers


class ToolAvailabilityTests(unittest.TestCase):
    @staticmethod
    def _tool(name):
        return StructuredTool.from_function(
            func=lambda: name,
            name=name,
            description=f"{name} test tool",
        )

    def test_workspace_tools_are_filtered_without_disabling_web_tools(self):
        engine = AgentEngine(
            model_hub=object(),
            mcp_manager=object(),
            skill_manager=object(),
            auth_manager=AuthManager(),
        )
        tools = [self._tool("read_file"), self._tool("fetch_url")]
        with patch.object(settings, "enable_local_mcp_tools", False):
            filtered = engine.filter_available_tools(
                "developer", tools, workspace_id="workspace-a"
            )
        self.assertEqual([tool.name for tool in filtered], ["fetch_url"])

        with patch.object(settings, "enable_local_mcp_tools", True):
            enabled = engine.filter_available_tools(
                "developer", tools, workspace_id="workspace-a"
            )
        self.assertEqual([tool.name for tool in enabled], ["read_file", "fetch_url"])

    def test_workspace_tools_fail_closed_without_server_derived_scope(self):
        engine = AgentEngine(
            model_hub=object(),
            mcp_manager=object(),
            skill_manager=object(),
            auth_manager=AuthManager(),
        )
        tools = [self._tool("write_file"), self._tool("fetch_url")]
        with patch.object(settings, "enable_local_mcp_tools", True):
            filtered = engine.filter_available_tools("developer", tools)
        self.assertEqual([tool.name for tool in filtered], ["fetch_url"])

    def test_python_never_enters_shared_multi_tenant_agent(self):
        engine = AgentEngine(
            model_hub=object(),
            mcp_manager=object(),
            skill_manager=object(),
            auth_manager=AuthManager(),
        )
        tools = [self._tool("run_python"), self._tool("read_file")]
        with patch.object(settings, "enable_local_mcp_tools", True):
            filtered = engine.filter_available_tools(
                "developer", tools, workspace_id="workspace-a"
            )
        self.assertEqual([tool.name for tool in filtered], ["read_file"])


class WorkspaceScopeClaimTests(unittest.TestCase):
    def test_scope_header_is_signed_and_missing_scope_has_no_claim(self):
        with patch.object(settings, "mcp_workspace_signing_key", "unit-test-key"):
            headers = MCPManager.workspace_scope_headers("workspace-a")
        self.assertEqual(headers["X-FutureAgent-Workspace"], "workspace-a")
        expected = hmac.new(
            b"unit-test-key", b"workspace-a", hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            headers["X-FutureAgent-Workspace-Signature"], expected
        )
        self.assertIsNone(MCPManager.workspace_scope_headers(None))


if __name__ == "__main__":
    unittest.main()
