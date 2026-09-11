import asyncio
import functools
import hashlib
import hmac
import tempfile
import time
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from auth.auth_manager import AuthManager
from core.agent_engine import AgentEngine
from core.mcp_manager import MCPManager
from core import model_hub
from core.model_hub import ModelHub
from core.skill_manager import Skill, SkillManager
from config import Settings, settings
from langchain_core.language_models.chat_models import SimpleChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
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

    def test_usage_is_counted_once_per_model_call_and_summed_across_the_tool_loop(self):
        config: dict = {"usage_by_message": {}}
        # 同一次调用的多个流式 chunk 共享 id，只应计一次（取最后一次完整值）。
        for tokens in (3, 7):
            AgentEngine._record_usage(
                config,
                AIMessageChunk(
                    content="x",
                    id="call-1",
                    usage_metadata={
                        "input_tokens": 10,
                        "output_tokens": tokens,
                        "total_tokens": 10 + tokens,
                    },
                ),
            )
        # 工具循环里的第二次模型调用使用不同 id，应累加。
        AgentEngine._record_usage(
            config,
            AIMessageChunk(
                content="y",
                id="call-2",
                usage_metadata={"input_tokens": 4, "output_tokens": 1, "total_tokens": 5},
            ),
        )
        self.assertEqual(
            AgentEngine.summarize_usage(config),
            {"input_tokens": 14, "output_tokens": 8, "total_tokens": 22, "llm_calls": 2},
        )

    def test_provider_that_never_reports_usage_is_not_recorded_as_zero_consumption(self):
        config: dict = {"usage_by_message": {}}
        AgentEngine._record_usage(config, AIMessageChunk(content="x", id="call-1"))
        summary = AgentEngine.summarize_usage(config)
        self.assertEqual(summary["llm_calls"], 0)
        self.assertEqual(summary["total_tokens"], 0)

    def test_unidentified_chunks_share_one_key_instead_of_growing_without_bound(self):
        config: dict = {"usage_by_message": {}}
        for _ in range(5):
            AgentEngine._record_usage(
                config,
                AIMessageChunk(
                    content="x",
                    usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                ),
            )
        self.assertEqual(AgentEngine.summarize_usage(config)["llm_calls"], 1)

    def test_cost_is_only_computed_for_models_with_a_registered_price(self):
        from core.pricing import PRICE_PER_MILLION_TOKENS, aggregate_cost, estimate_cost

        self.assertIsNone(estimate_cost("unpriced-model", 1_000, 1_000))
        PRICE_PER_MILLION_TOKENS["priced-model"] = (1.0, 3.0)
        try:
            self.assertEqual(estimate_cost("priced-model", 1_000_000, 1_000_000), 4.0)
            total, priced_rows = aggregate_cost(
                [{"cost": 4.0}, {"cost": None}]
            )
            self.assertEqual((total, priced_rows), (4.0, 1))
            self.assertEqual(aggregate_cost([{"cost": None}]), (None, 0))
        finally:
            PRICE_PER_MILLION_TOKENS.pop("priced-model", None)


class ModelReadinessTests(unittest.TestCase):
    def test_extra_model_ids_are_routed_as_openai_compatible(self):
        with (
            patch.object(settings, "extra_model_ids_csv", "glm-5.3-flash, other-model"),
            patch.object(settings, "openai_base_url", "https://relay.example.test/v1"),
            patch.object(settings, "openai_api_key", "sk-real-relay-key"),
        ):
            self.assertEqual(settings.extra_model_ids, ["glm-5.3-flash", "other-model"])
            self.assertIn("glm-5.3-flash", ModelHub.list_supported_models())
            self.assertTrue(ModelHub.is_direct_provider_configured("glm-5.3-flash"))
            # 无供应商前缀的模型必须显式加 openai/，否则 LiteLLM 认不出路由。
            self.assertEqual(
                ModelHub._litellm_model_name("glm-5.3-flash"), "openai/glm-5.3-flash"
            )
            self.assertEqual(
                ModelHub._provider_kwargs("glm-5.3-flash"),
                {
                    "api_base": "https://relay.example.test/v1",
                    "api_key": "sk-real-relay-key",
                },
            )

    def test_extra_model_without_base_url_is_not_advertised_as_configured(self):
        # 缺地址时如果仍声称已配置，请求会默认发往 api.openai.com 并带上密钥。
        with (
            patch.object(settings, "extra_model_ids_csv", "glm-5.3-flash"),
            patch.object(settings, "openai_api_key", "sk-real-relay-key"),
            patch.object(settings, "openai_base_url", ""),
        ):
            self.assertFalse(ModelHub.is_direct_provider_configured("glm-5.3-flash"))

    def test_chat_model_survives_missing_chatlitellm_on_openai_compatible_routes(self):
        """ChatLiteLLM 已从 langchain-community 0.4 移除，不得因此全面报错。

        这条链路以前没有任何测试覆盖（测试一律用 FakeModelHub），
        导致 ImportError 把整个 AI 对话能力静默打穿。
        """
        from langchain_openai import ChatOpenAI

        with (
            patch.object(settings, "litellm_proxy_url", ""),
            patch.object(settings, "extra_model_ids_csv", "glm-5.3-flash"),
            patch.object(settings, "openai_api_key", "sk-real-relay-key"),
            patch.object(settings, "openai_base_url", "https://relay.example.test/v1"),
            patch.object(ModelHub, "_litellm_chat_model_class", return_value=None),
        ):
            llm = ModelHub().get_chat_model(model_id="glm-5.3-flash")
        self.assertIsInstance(llm, ChatOpenAI)
        self.assertEqual(llm.model_name, "glm-5.3-flash")
        self.assertEqual(str(llm.openai_api_base), "https://relay.example.test/v1")

    def test_chat_model_refuses_to_guess_an_endpoint_for_other_providers(self):
        """没有 ChatLiteLLM 时，非 OpenAI 协议模型必须显式失败。

        否则会把 Anthropic/Gemini 的请求默认发往 api.openai.com，
        既失败得莫名其妙，又白送一次密钥泄露。
        """
        with (
            patch.object(settings, "litellm_proxy_url", ""),
            patch.object(settings, "openai_api_key", "sk-real-relay-key"),
            patch.object(settings, "openai_base_url", "https://relay.example.test/v1"),
            patch.object(ModelHub, "_litellm_chat_model_class", return_value=None),
        ):
            with self.assertRaisesRegex(ValueError, "OpenAI 兼容"):
                ModelHub().get_chat_model(model_id="claude-3-5-sonnet-20241022")
            with self.assertRaisesRegex(ValueError, "OpenAI 兼容"):
                ModelHub().get_chat_model(model_id="gemini/gemini-1.5-pro")

    def test_ollama_route_uses_the_openai_compatible_subpath(self):
        with patch.object(settings, "ollama_base_url", "http://localhost:11434"):
            self.assertEqual(
                ModelHub._openai_compatible_credentials("ollama/qwen2.5"),
                ("http://localhost:11434/v1", "ollama"),
            )

    def test_placeholder_provider_key_is_not_a_ready_direct_route(self):
        with (
            patch.object(settings, "litellm_proxy_url", ""),
            patch.object(settings, "openai_api_key", "sk-your-openai-key"),
            patch.object(model_hub, "LITELLM_AVAILABLE", True),
        ):
            self.assertFalse(ModelHub.is_model_configured("gpt-4o-mini"))
            self.assertEqual(ModelHub.configuration_source("gpt-4o-mini"), "missing")
            self.assertIn("尚未配置", ModelHub.readiness_error("gpt-4o-mini"))

    def test_litellm_proxy_requires_a_non_placeholder_master_key(self):
        with (
            patch.object(settings, "litellm_proxy_url", "http://proxy.example.test"),
            patch.object(settings, "litellm_master_key", ""),
            patch.object(model_hub, "LITELLM_AVAILABLE", True),
        ):
            self.assertFalse(ModelHub.is_litellm_proxy_configured())
            self.assertFalse(ModelHub.is_model_configured("gpt-4o-mini"))
            self.assertEqual(ModelHub.configuration_source("gpt-4o-mini"), "missing")
            self.assertIn("Master Key", ModelHub.readiness_error("gpt-4o-mini"))

        with (
            patch.object(settings, "litellm_proxy_url", "http://proxy.example.test"),
            patch.object(settings, "litellm_master_key", "sk-futureagent"),
        ):
            self.assertFalse(ModelHub.is_litellm_proxy_configured())

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

    def test_full_access_widens_workspace_tools_but_never_python(self):
        engine = AgentEngine(
            model_hub=object(),
            mcp_manager=object(),
            skill_manager=object(),
            auth_manager=AuthManager(),
        )
        tools = [self._tool("run_python"), self._tool("write_file")]
        # 部署开关关闭时，full_access 仍可放开工作区写工具。
        with patch.object(settings, "enable_local_mcp_tools", False):
            filtered = engine.filter_available_tools(
                "developer",
                tools,
                workspace_id="workspace-a",
                permission_mode="full_access",
            )
        # run_python 是永久底线，任何档位都不得放开。
        self.assertEqual([tool.name for tool in filtered], ["write_file"])

    def test_full_access_still_fails_closed_without_server_derived_scope(self):
        engine = AgentEngine(
            model_hub=object(),
            mcp_manager=object(),
            skill_manager=object(),
            auth_manager=AuthManager(),
        )
        tools = [self._tool("write_file"), self._tool("fetch_url")]
        with patch.object(settings, "enable_local_mcp_tools", False):
            filtered = engine.filter_available_tools(
                "developer", tools, permission_mode="full_access"
            )
        # 放宽的是审批，不是租户边界：无服务端派生工作区仍失败关闭。
        self.assertEqual([tool.name for tool in filtered], ["fetch_url"])

    def test_rbac_still_filters_tools_under_full_access(self):
        engine = AgentEngine(
            model_hub=object(),
            mcp_manager=object(),
            skill_manager=object(),
            auth_manager=AuthManager(),
        )
        # rbac_policy.csv 未给 user 角色 write_file，档位不得绕过 RBAC。
        tools = [self._tool("write_file"), self._tool("read_file")]
        with patch.object(settings, "enable_local_mcp_tools", False):
            filtered = engine.filter_available_tools(
                "user",
                tools,
                workspace_id="workspace-a",
                permission_mode="full_access",
            )
        self.assertEqual([tool.name for tool in filtered], ["read_file"])


class _RoleAwareFakeModel(SimpleChatModel):
    """根据系统提示词区分“代理回复”与“监督判定”。

    真实的监督节点与代理节点共用同一个模型，但两者输出用途完全不同：
    前者是内部控制流，后者才是给用户看的回复。
    """

    judge_reply: str = '{"met": true, "reason": "已满足达成标准"}'
    agent_reply: str = "这是给用户看的口号"

    @property
    def _llm_type(self) -> str:
        return "role-aware-fake"

    def _call(self, messages, stop=None, run_manager=None, **kwargs):
        return self._reply_for(messages)

    def _reply_for(self, messages) -> str:
        system = "".join(
            str(getattr(item, "content", ""))
            for item in messages
            if getattr(item, "type", "") == "system"
        )
        return self.judge_reply if "执行质量监督者" in system else self.agent_reply

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        """必须真流式：AgentEngine 只消费 AIMessageChunk。

        非流式模型会产出 AIMessage，它不是 AIMessageChunk 的子类，
        会被引擎直接忽略——用错的替身会把测试变成假阳性。
        两次调用给不同 id，否则用量去重会把它们归为同一次。
        """
        text = self._reply_for(messages)
        role = "judge" if text == self.judge_reply else "agent"
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content=text,
                id=f"{role}-call",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            )
        )


class AgentModeTests(unittest.TestCase):
    """五档运行模式的工具面、提示词与监督循环。"""

    class _ScriptedJudge:
        """按脚本回应监督判定，避免与 agent 共用一个假模型而互相干扰。"""

        def __init__(self, replies):
            self.replies = list(replies)
            self.calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            content = self.replies.pop(0) if self.replies else '{"met": true, "reason": "done"}'
            return SimpleNamespace(content=content)

    @staticmethod
    def _tool(name):
        return StructuredTool.from_function(func=lambda: name, name=name, description=f"{name} tool")

    def _supervisor(self, judge, *, mode="goal", max_iterations=3, iteration=0):
        with tempfile.TemporaryDirectory() as directory:
            engine = AgentEngine(
                model_hub=object(),
                mcp_manager=MCPManager({}),
                skill_manager=SkillManager(directory),
                auth_manager=AuthManager(),
            )
        config: dict = {"iterations": []}
        node = engine._supervisor_node_factory(judge, mode, config)
        state = {
            "messages": [],
            "mode": mode,
            "goal": "把报告写完",
            "success_criteria": "包含三个章节",
            "iteration": iteration,
            "max_iterations": max_iterations,
            "verdict": "",
        }
        return engine, config, node, state

    def test_parse_judgement_accepts_only_the_documented_contract(self):
        parse = AgentEngine._parse_judgement
        self.assertEqual(parse('{"met": true, "reason": "已完成"}'), (True, "已完成"))
        self.assertEqual(parse('前置说明 {"met": false, "reason": "缺少数据"} 后缀'), (False, "缺少数据"))
        self.assertEqual(parse('{"met": false}')[1], "（监督者未说明原因）")
        # 不合约定一律返回 None，由调用方终止而不是猜一个结果。
        self.assertIsNone(parse("已完成"))
        self.assertIsNone(parse('{"done": true}'))
        self.assertIsNone(parse("{broken"))

    def test_supervisor_loops_only_on_an_explicit_not_met(self):
        judge = self._ScriptedJudge(['{"met": false, "reason": "再补一章"}'])
        engine, config, node, state = self._supervisor(judge)
        result = asyncio.run(node(state))
        self.assertEqual(result["verdict"], "not_met")
        self.assertEqual(result["iteration"], 1)
        # 监督者的下一步指令必须回注为人类消息，否则下一轮无从推进。
        self.assertEqual(result["messages"][0].content, "再补一章")
        self.assertEqual(config["iterations"][0]["verdict"], "not_met")

    def test_supervisor_stops_when_the_goal_is_met(self):
        judge = self._ScriptedJudge(['{"met": true, "reason": "已满足"}'])
        _engine, config, node, state = self._supervisor(judge)
        result = asyncio.run(node(state))
        self.assertEqual(result["verdict"], "met")
        self.assertNotIn("messages", result)
        self.assertEqual(config["iterations"][0]["verdict"], "met")

    def test_supervisor_exhausts_the_budget_without_calling_the_judge(self):
        judge = self._ScriptedJudge([])
        _engine, config, node, state = self._supervisor(judge, max_iterations=2, iteration=2)
        result = asyncio.run(node(state))
        self.assertEqual(result["verdict"], "budget_exhausted")
        self.assertEqual(judge.calls, 0)
        self.assertIn("最大迭代轮次", config["iterations"][0]["reason"])

    def test_unparseable_judgement_stops_instead_of_burning_the_budget(self):
        judge = self._ScriptedJudge(["我觉得差不多了"])
        _engine, config, node, state = self._supervisor(judge)
        result = asyncio.run(node(state))
        # 判定不可用时必须终止；继续循环只会白耗 token。
        self.assertEqual(result["verdict"], "judge_unavailable")
        self.assertNotIn("messages", result)
        self.assertEqual(config["iterations"][0]["verdict"], "judge_unavailable")

    def test_loop_mode_judges_against_the_stop_condition(self):
        captured: dict = {}

        class RecordingJudge:
            async def ainvoke(self, messages):
                captured["messages"] = messages
                return SimpleNamespace(content='{"met": true, "reason": "ok"}')

        _engine, _config, node, state = self._supervisor(RecordingJudge(), mode="loop")
        asyncio.run(node(state))
        self.assertIn("执行质量监督者", captured["messages"][0].content)
        prompt = captured["messages"][1].content
        # loop 只看停止条件；把目标也堆上去会稀释判据。
        self.assertIn("停止条件：包含三个章节", prompt)
        self.assertNotIn("目标：", prompt)

    def test_goal_mode_judges_against_goal_and_criteria(self):
        captured: dict = {}

        class RecordingJudge:
            async def ainvoke(self, messages):
                captured["messages"] = messages
                return SimpleNamespace(content='{"met": true, "reason": "ok"}')

        _engine, _config, node, state = self._supervisor(RecordingJudge(), mode="goal")
        asyncio.run(node(state))
        prompt = captured["messages"][1].content
        self.assertIn("目标：把报告写完", prompt)
        self.assertIn("达成标准：包含三个章节", prompt)

    def test_mode_prompt_layers_constraints_on_top_of_the_skill(self):
        prompt = AgentEngine._mode_prompt
        self.assertEqual(prompt("基础", "chat", {}), "基础")
        self.assertEqual(prompt("基础", "agent", {}), "基础")
        self.assertIn("仅输出一段 JSON", prompt("基础", "plan", {}))
        goal = prompt("基础", "goal", {"goal": "完成报告", "success_criteria": "三章节"})
        self.assertIn("基础", goal)
        self.assertIn("完成报告", goal)
        self.assertIn("三章节", goal)
        loop = prompt("基础", "loop", {"success_criteria": "无错别字"})
        self.assertIn("循环迭代", loop)
        self.assertIn("无错别字", loop)

    def test_only_supervised_modes_attach_a_supervisor_node(self):
        async def worker(_state):
            return {"messages": []}

        async def supervisor(_state):
            return {}

        with tempfile.TemporaryDirectory() as directory:
            engine = AgentEngine(
                model_hub=object(),
                mcp_manager=MCPManager({}),
                skill_manager=SkillManager(directory),
                auth_manager=AuthManager(),
            )
        plain = engine._graph_factory(worker, [])
        self.assertNotIn("supervisor", set(plain.nodes))
        supervised = engine._graph_factory(worker, [], supervisor_node=supervisor)
        self.assertIn("supervisor", set(supervised.nodes))
        with_tools = engine._graph_factory(
            worker, [self._tool("read_file")], supervisor_node=supervisor
        )
        self.assertTrue(
            {"agent_node", "tools", "supervisor"}.issubset(set(with_tools.nodes))
        )

    def test_chat_mode_binds_no_tools_and_plan_mode_is_read_only(self):
        tools = [
            self._tool("read_file"),
            self._tool("write_file"),
            self._tool("web_search"),
        ]
        for mode, expected in (
            ("chat", []),
            ("plan", ["read_file", "web_search"]),
            ("agent", ["read_file", "write_file", "web_search"]),
        ):
            with self.subTest(mode=mode):
                captured = self._run_capturing_agent_factory(tools, mode)
                self.assertEqual(captured["tools"], expected)

    def _run_capturing_agent_factory(self, tools, mode):
        """跑一次 run()，侧录实际绑定给模型的工具与提示词。

        FakeListChatModel 不支持 bind_tools，因此记录后用空工具列表
        走真实的不绑定分支，图形态与提示词仍由真实代码路径产生。
        """
        captured: dict = {}

        class FakeModelHub:
            def get_chat_model(self, **_kwargs):
                return FakeListChatModel(responses=["ok"])

        class FakeMcpManager:
            servers = {"local_tools": "http://mcp.invalid/mcp"}

            @asynccontextmanager
            async def connect_many(self, _names, **_kwargs):
                yield [object()]

            async def get_mcp_tools(self, _session):
                return list(tools)

        with tempfile.TemporaryDirectory() as directory:
            engine = AgentEngine(
                model_hub=FakeModelHub(),
                mcp_manager=FakeMcpManager(),
                skill_manager=SkillManager(directory),
                auth_manager=AuthManager(),
            )
            original = AgentEngine._agent_factory

            def recorder(instance, llm, bound_tools, system_prompt):
                captured["tools"] = [tool.name for tool in bound_tools]
                captured["prompt"] = system_prompt
                return original(instance, llm, [], system_prompt)

            async def drive():
                with patch.object(settings, "enable_local_mcp_tools", True):
                    with patch.object(AgentEngine, "_agent_factory", recorder):
                        async for _chunk in engine.run(
                            "developer",
                            "hi",
                            {
                                "model_id": "fake-model",
                                "skill_name": "default",
                                "mcp_servers": ["local_tools"],
                                "workspace_id": "workspace-a",
                                "mode": mode,
                                "iterations": [],
                            },
                        ):
                            pass

            asyncio.run(drive())
        return captured

    def test_supervisor_judgement_never_leaks_into_the_user_visible_stream(self):
        """监督节点的判定 JSON 是内部控制流，不得当成助手回复流给用户。

        ``stream_mode=messages`` 会把图内所有 LLM 调用都流出来，不按节点
        过滤就会把原始 JSON 直接显示在对话里。
        """

        class JudgeModelHub:
            def get_chat_model(self, **_kwargs):
                return _RoleAwareFakeModel()

        with tempfile.TemporaryDirectory() as directory:
            engine = AgentEngine(
                model_hub=JudgeModelHub(),
                mcp_manager=MCPManager({}),
                skill_manager=SkillManager(directory),
                auth_manager=AuthManager(),
            )
            config = {
                "model_id": "fake-model",
                "skill_name": "default",
                "mcp_servers": [],
                "mode": "goal",
                "goal": "产出一句口号",
                "success_criteria": "包含关键字",
                "max_iterations": 2,
                "tool_trace": [],
                "usage_by_message": {},
                "iterations": [],
            }

            async def drive():
                chunks = []
                async for chunk in engine.run("developer", "写一句口号", config):
                    chunks.append(chunk)
                return "".join(chunks)

            text = asyncio.run(drive())

        self.assertIn("这是给用户看的口号", text)
        # 判定原文与它的 JSON 字段都不得出现在用户可见输出里。
        self.assertNotIn("met", text)
        self.assertNotIn("{", text)
        self.assertNotIn("已满足达成标准", text)
        # 但判定本身必须被记录到侧信道，且它的 token 仍要计量。
        self.assertEqual(config["iterations"][0]["verdict"], "met")
        self.assertEqual(config["iterations"][0]["reason"], "已满足达成标准")
        self.assertEqual(AgentEngine.summarize_usage(config)["llm_calls"], 2)

    def test_unknown_mode_is_rejected_rather_than_silently_downgraded(self):
        class FakeModelHub:
            def get_chat_model(self, **_kwargs):
                return FakeListChatModel(responses=["ok"])

        with tempfile.TemporaryDirectory() as directory:
            engine = AgentEngine(
                model_hub=FakeModelHub(),
                mcp_manager=MCPManager({}),
                skill_manager=SkillManager(directory),
                auth_manager=AuthManager(),
            )

            async def drive():
                with self.assertRaisesRegex(ValueError, "不支持的运行模式"):
                    async for _chunk in engine.run(
                        "developer",
                        "hi",
                        {"model_id": "fake", "skill_name": "default", "mcp_servers": [], "mode": "turbo"},
                    ):
                        pass

            asyncio.run(drive())


class SubagentTests(unittest.TestCase):
    """dispatch_subagent 的深度、权限、预算与用量归因。"""

    @staticmethod
    def _tool(name):
        return StructuredTool.from_function(func=lambda: name, name=name, description=f"{name} tool")

    def _engine(self, directory, responses=("子代理完成",)):
        class FakeModelHub:
            def get_chat_model(self, **_kwargs):
                return FakeListChatModel(responses=list(responses))

        manager = SkillManager(directory)
        # 子代理是按技能显式开启的：白名单为空（如内置 default）不会获得。
        manager.register_skill(
            Skill(
                name="orchestrator",
                description="编排技能",
                system_prompt="你是编排者。",
                allowed_tool_names=["read_file", "dispatch_subagent"],
            )
        )
        return AgentEngine(
            model_hub=FakeModelHub(),
            mcp_manager=MCPManager({}),
            skill_manager=manager,
            auth_manager=AuthManager(),
        )

    def _dispatch(self, engine, *, role="developer", depth=0, tools=None, deadline=None, max_depth=2):
        config = {"deadline": deadline if deadline is not None else time.monotonic() + 30}
        with patch.object(settings, "subagent_max_depth", max_depth):
            tool = engine._subagent_tool(
                user_role=role,
                tools=list(tools if tools is not None else [self._tool("read_file")]),
                model_id="fake-model",
                config=config,
                workspace_id="workspace-a",
                permission_mode="default",
                depth=depth,
            )
        return tool, config

    def test_child_keeps_the_parent_tool_subset_and_nests_only_below_the_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = self._engine(directory)
            captured: list = []

            async def fake_run_child(_self, _parent, child_config, tools, _model, _skill, _task):
                captured.append((child_config["subagent_depth"], [tool.name for tool in tools]))
                return "ok"

            with patch.object(AgentEngine, "_run_child", fake_run_child):
                # depth=0 → 子代理处于 depth 1，1 < 2 且技能已开启，可再派生一层。
                tool, _ = self._dispatch(engine, depth=0)
                asyncio.run(tool.coroutine(skill_name="orchestrator", task="子任务"))
                # depth=1 → 子代理处于 depth 2，已达上限，不得再派生。
                tool, _ = self._dispatch(engine, depth=1)
                asyncio.run(tool.coroutine(skill_name="orchestrator", task="子任务"))

        self.assertEqual(captured[0][0], 1)
        self.assertIn("dispatch_subagent", captured[0][1])
        self.assertIn("read_file", captured[0][1])
        self.assertEqual(captured[1][0], 2)
        self.assertNotIn("dispatch_subagent", captured[1][1])
        # 子代理工具集始终是父代理的子集，不会出现父代理没有的工具。
        self.assertTrue(set(captured[1][1]).issubset({"read_file", "dispatch_subagent"}))

    def test_exhausted_shared_budget_stops_the_subagent_before_it_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = self._engine(directory)
            calls: list = []

            async def fake_run_child(*_args):
                calls.append(1)
                return "should not run"

            with patch.object(AgentEngine, "_run_child", fake_run_child):
                tool, config = self._dispatch(engine, deadline=time.monotonic() - 1)
                result = asyncio.run(tool.coroutine(skill_name="default", task="子任务"))

        self.assertIn("时间预算已用尽", result)
        self.assertEqual(calls, [])
        # 未启动的子代理也要留痕，否则使用者无法区分“没派生”与“派生了但没预算”。
        self.assertEqual(config["subagent_usage"][0]["status"], "skipped")

    def test_subagent_usage_is_recorded_separately_from_the_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = self._engine(directory)
            # max_depth=1 且 tools=[]：子代理不再嵌套也不挂工具，避开
            # FakeListChatModel 不支持 bind_tools 的限制；本用例验证的是
            # 用量归因而非工具循环。
            tool, config = self._dispatch(engine, tools=[], max_depth=1)
            result = asyncio.run(tool.coroutine(skill_name="orchestrator", task="子任务"))

        self.assertEqual(result, "子代理完成")
        records = config["subagent_usage"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "succeeded")
        self.assertEqual(records[0]["depth"], 1)
        self.assertTrue(records[0]["duration_ms"] >= 0)
        # 子代理有独立计量桶，不会写进父代理的 usage_by_message。
        self.assertFalse(config.get("usage_by_message"))

    def test_unknown_skill_and_empty_task_are_refused_without_running_a_child(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = self._engine(directory)
            tool, config = self._dispatch(engine)
            missing = asyncio.run(tool.coroutine(skill_name="no-such-skill", task="x"))
            empty = asyncio.run(tool.coroutine(skill_name="orchestrator", task="   "))
        self.assertIn("不存在", missing)
        self.assertIn("不能为空", empty)
        self.assertEqual([item["status"] for item in config.get("subagent_usage", [])], [])

    def test_model_override_cannot_bypass_model_level_rbac(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SkillManager(directory)
            manager.register_skill(
                Skill(
                    name="privileged",
                    description="试图提权的技能",
                    system_prompt="你是助手。",
                    model_override="restricted-model",
                )
            )
            engine = self._engine(directory)
            engine.skill_manager = manager
            tool, _config = self._dispatch(engine, role="user")
            result = asyncio.run(tool.coroutine(skill_name="privileged", task="子任务"))
        # user 角色只有 model:gpt-3.5-turbo 权限，model_override 不得绕过。
        self.assertIn("无权使用", result)

    def test_dispatch_tool_is_gated_by_rbac_and_depth_at_injection_time(self):
        tools = [self._tool("read_file")]
        for role, depth, max_depth, expected in (
            # developer + 已开启的技能，在深度上限内获得子代理工具。
            ("developer", 0, 2, True),
            # 达到嵌套上限后不再注入，子代理自然无法再派生。
            ("developer", 2, 2, False),
            # 部署方将上限设为 0 即完全禁用子代理。
            ("developer", 0, 0, False),
            # user 角色未授予 tool:dispatch_subagent，即使深度允许也不注入。
            ("user", 0, 2, False),
        ):
            with self.subTest(role=role, depth=depth, max_depth=max_depth):
                injected = self._injected_tools(role, tools, depth, max_depth)
                self.assertEqual("dispatch_subagent" in injected, expected)

    def test_skills_that_do_not_opt_in_never_receive_the_dispatch_tool(self):
        # 内置 default 技能的白名单为空（意为放开全部 MCP 工具），
        # 但这不等于可以派生子代理；否则存量技能会静默改变行为。
        injected = self._injected_tools("developer", [self._tool("read_file")], 0, 2, skill_name="default")
        self.assertNotIn("dispatch_subagent", injected)
        self.assertIn("read_file", injected)

    def _injected_tools(self, role, tools, depth, max_depth, skill_name="orchestrator"):
        captured: dict = {}

        class FakeModelHub:
            def get_chat_model(self, **_kwargs):
                return FakeListChatModel(responses=["ok"])

        class FakeMcpManager:
            servers = {"local_tools": "http://mcp.invalid/mcp"}

            @asynccontextmanager
            async def connect_many(self, _names, **_kwargs):
                yield [object()]

            async def get_mcp_tools(self, _session):
                return list(tools)

        with tempfile.TemporaryDirectory() as directory:
            manager = SkillManager(directory)
            manager.register_skill(
                Skill(
                    name="orchestrator",
                    description="编排技能",
                    system_prompt="你是编排者。",
                    allowed_tool_names=["read_file", "dispatch_subagent"],
                )
            )
            engine = AgentEngine(
                model_hub=FakeModelHub(),
                mcp_manager=FakeMcpManager(),
                skill_manager=manager,
                auth_manager=AuthManager(),
            )
            original = AgentEngine._agent_factory

            def recorder(instance, llm, bound_tools, system_prompt):
                captured["tools"] = [tool.name for tool in bound_tools]
                return original(instance, llm, [], system_prompt)

            async def drive():
                with (
                    patch.object(settings, "enable_local_mcp_tools", True),
                    patch.object(settings, "subagent_max_depth", max_depth),
                    patch.object(AgentEngine, "_agent_factory", recorder),
                    # 本用例只验证工具注入判定；资源级校验（如 user 角色
                    # 无 skill:default）由其他用例覆盖，在此隔离掉。
                    patch.object(AgentEngine, "validate_permissions", lambda *_a, **_k: None),
                ):
                    async for _chunk in engine.run(
                        role,
                        "hi",
                        {
                            "model_id": "gpt-3.5-turbo" if role == "user" else "fake-model",
                            "skill_name": skill_name,
                            "mcp_servers": ["local_tools"],
                            "workspace_id": "workspace-a",
                            "mode": "agent",
                            "subagent_depth": depth,
                        },
                    ):
                        pass

            asyncio.run(drive())
        return captured.get("tools", [])


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
