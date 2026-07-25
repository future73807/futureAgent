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
from config import settings
from langchain_core.language_models.fake_chat_models import FakeListChatModel
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


if __name__ == "__main__":
    unittest.main()
