"""定时任务：智能体侧的工具集、角色门控，以及到点执行体。

这里覆盖三件最容易被改坏的事：
1. 工具签名里**不能**出现 workspace_id / created_by（模型不得指定别人的工作区或
   伪造发起人）；
2. 定时任务工具只对非只读角色可见，并且必须在技能白名单里；
3. 到点执行要么真的产出一个对话 + 通知，要么带着可读原因失败——不能静默。
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlmodel import SQLModel, Session, create_engine, select

import db.database as database
from core.agent_engine import AgentEngine
from core.model_hub import ModelHub
from core.scheduler import execute_job, next_run_at, start_scheduler, shutdown_scheduler, validate_cron
from core.scheduling import (
    SCHEDULING_TOOL_NAMES,
    cancel_scheduled_task,
    create_scheduled_task,
    list_scheduled_tasks,
    scheduling_tools,
)
from core.skill_manager import Skill, SkillManager
from auth.auth_manager import AuthManager
from config import settings
from db.models import ChatMessage, Conversation, Membership, Notification, ScheduledJob, User, Workspace


class _FakeSkill:
    name = "chatbot"


class _FakeSkillManager:
    def __init__(self, known: bool = True):
        self.known = known

    def get_skill(self, name: str):
        return _FakeSkill() if self.known else None


class _FakeEngine:
    """只实现执行体真正用到的两个接口。"""

    def __init__(self, reply: str = "这是定时产出的简报。", known_skill: bool = True):
        self.reply = reply
        self.skill_manager = _FakeSkillManager(known_skill)
        self.calls: list[dict] = []

    async def run(self, user_role, query, config):
        self.calls.append({"role": user_role, "query": query, "config": config})
        yield self.reply


class SchedulingToolSurfaceTests(unittest.TestCase):
    def test_tool_signature_never_exposes_workspace_or_creator(self):
        """工作区与发起人由闭包绑定：模型参数里看不到它们。"""
        tools = scheduling_tools(workspace_id="workspace-a", created_by="user-a")
        self.assertEqual({tool.name for tool in tools}, set(SCHEDULING_TOOL_NAMES))
        for tool in tools:
            fields = set((tool.args_schema or {}).model_fields)
            self.assertNotIn("workspace_id", fields)
            self.assertNotIn("created_by", fields)
        schedule = next(tool for tool in tools if tool.name == "schedule_task")
        self.assertTrue({"name", "cron", "prompt"}.issubset(set(schedule.args_schema.model_fields)))
        # cron 语义要写在描述里，模型才知道怎么把"每天早上"翻译成表达式。
        self.assertIn("0 9 * * *", schedule.description)
        self.assertIn("cron", schedule.description)

    def test_only_non_viewer_roles_may_use_the_tools(self):
        manager = AuthManager()
        self.assertTrue(manager.is_allowed("developer", "tool:schedule_task", "use"))
        self.assertTrue(manager.is_allowed("admin", "tool:schedule_task", "use"))
        # 只读成员（Casbin user）不该拿到"让智能体以后替我做"的能力。
        self.assertFalse(manager.is_allowed("user", "tool:schedule_task", "use"))
        self.assertFalse(manager.is_allowed("user", "tool:cancel_scheduled_task", "use"))

    def test_shipped_skills_whitelist_the_scheduling_tools(self):
        manager = SkillManager(str(Path(__file__).resolve().parents[1] / "skills"))
        for name in ("chatbot", "coder", "data_analyst"):
            skill = manager.get_skill(name)
            self.assertIsNotNone(skill, name)
            allowed = set(skill.allowed_tool_names or [])
            self.assertTrue(
                {"schedule_task", "list_scheduled_tasks", "cancel_scheduled_task"}.issubset(allowed),
                f"{name} 白名单缺少定时任务工具：{sorted(allowed)}",
            )


class SchedulingToolBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_engine = database.engine
        database.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name, 'scheduling.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        with Session(database.engine) as session:
            session.add(User(id="u1", email="s@example.com", display_name="S", password_hash="x"))
            session.add(Workspace(id="w1", name="调度", slug="w1", owner_id="u1"))
            session.add(Workspace(id="w2", name="别家", slug="w2", owner_id="u1"))
            session.commit()

    def tearDown(self):
        shutdown_scheduler()
        database.engine.dispose()
        database.engine = self.original_engine
        self.temp_dir.cleanup()

    def _jobs(self, workspace_id="w1"):
        with Session(database.engine) as session:
            return session.exec(
                select(ScheduledJob).where(ScheduledJob.workspace_id == workspace_id)
            ).all()

    def test_cron_validation_matches_the_scheduler(self):
        self.assertTrue(validate_cron("0 9 * * *"))
        self.assertFalse(validate_cron("每天九点"))
        result = create_scheduled_task(
            workspace_id="w1",
            created_by="u1",
            name="晨报",
            cron="每天九点",
            prompt="总结昨天",
        )
        self.assertIn("cron", result)
        self.assertEqual(self._jobs(), [])

    def test_create_records_workspace_creator_and_next_run(self):
        # 没有调度器时 next_run_at 是 None，但任务本身必须落库。
        result = create_scheduled_task(
            workspace_id="w1",
            created_by="u1",
            name="每日晨报",
            cron="0 9 * * *",
            prompt="总结工作区昨天新增的任务与执行结果，输出 5 条以内要点。",
            mode="agent",
        )
        self.assertIn("已创建定时任务", result)
        jobs = self._jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].workspace_id, "w1")
        self.assertEqual(jobs[0].created_by, "u1")
        self.assertEqual(jobs[0].job_type, "agent_task")
        self.assertEqual(jobs[0].mode, "agent")
        self.assertTrue(jobs[0].enabled)

    def test_duplicate_and_empty_prompt_are_rejected_without_side_effects(self):
        create_scheduled_task(
            workspace_id="w1", created_by="u1", name="晨报", cron="0 9 * * *", prompt="总结昨天"
        )
        again = create_scheduled_task(
            workspace_id="w1", created_by="u1", name="晨报", cron="0 9 * * *", prompt="总结昨天"
        )
        self.assertIn("已存在", again)
        blank = create_scheduled_task(
            workspace_id="w1", created_by="u1", name="空白", cron="0 9 * * *", prompt="   "
        )
        self.assertIn("提示词为空", blank)
        self.assertEqual(len(self._jobs()), 1)

    def test_unsupported_mode_is_rejected(self):
        result = create_scheduled_task(
            workspace_id="w1",
            created_by="u1",
            name="循环",
            cron="0 9 * * *",
            prompt="一直改进",
            mode="loop",
        )
        self.assertIn("不支持的模式", result)
        self.assertEqual(self._jobs(), [])

    def test_workspace_cap_blocks_runaway_creation(self):
        for index in range(20):
            create_scheduled_task(
                workspace_id="w1",
                created_by="u1",
                name=f"任务 {index}",
                cron="0 9 * * *",
                prompt=f"第 {index} 件事",
            )
        blocked = create_scheduled_task(
            workspace_id="w1", created_by="u1", name="第 21 条", cron="0 9 * * *", prompt="再来一条"
        )
        self.assertIn("上限", blocked)
        self.assertEqual(len(self._jobs()), 20)

    def test_list_and_cancel_are_workspace_scoped(self):
        create_scheduled_task(
            workspace_id="w1", created_by="u1", name="工作区一的任务", cron="0 9 * * *", prompt="做一"
        )
        create_scheduled_task(
            workspace_id="w2", created_by="u1", name="工作区二的任务", cron="0 9 * * *", prompt="做二"
        )
        listing = list_scheduled_tasks(workspace_id="w1")
        self.assertIn("工作区一的任务", listing)
        self.assertNotIn("工作区二的任务", listing)

        # 默认只停用，不删；只有明确要求才删。
        cancelled = cancel_scheduled_task(workspace_id="w1", task="工作区一的任务")
        self.assertIn("已停用", cancelled)
        self.assertFalse(self._jobs("w1")[0].enabled)
        deleted = cancel_scheduled_task(workspace_id="w1", task="工作区一的任务", delete=True)
        self.assertIn("已删除", deleted)
        self.assertEqual(self._jobs("w1"), [])

    def test_cancel_asks_for_an_id_when_the_name_is_ambiguous(self):
        create_scheduled_task(
            workspace_id="w1", created_by="u1", name="晨报 A", cron="0 9 * * *", prompt="甲"
        )
        create_scheduled_task(
            workspace_id="w1", created_by="u1", name="晨报 B", cron="0 9 * * *", prompt="乙"
        )
        result = cancel_scheduled_task(workspace_id="w1", task="晨报")
        self.assertIn("匹配到多条", result)
        self.assertEqual(len(self._jobs("w1")), 2)

    def test_triggers_are_registered_in_the_running_scheduler(self):
        start_scheduler()
        created = create_scheduled_task(
            workspace_id="w1", created_by="u1", name="排期验证", cron="0 9 * * *", prompt="做事"
        )
        self.assertIn("已创建定时任务", created)
        job = self._jobs("w1")[0]
        upcoming = next_run_at(job.id)
        self.assertIsNotNone(upcoming, "启用中的任务必须真的排进调度器")
        cancel_scheduled_task(workspace_id="w1", task=job.id)
        self.assertIsNone(next_run_at(job.id), "停用后不该再排期")


class EngineSchedulingToolTests(unittest.TestCase):
    """引擎注入：chat 模式保留定时任务工具，其它模式叠加在工作区工具之上。"""

    def _capture(self, mode: str, role: str = "developer", user_id: str = "user-a"):
        captured: dict = {}
        # 只读角色（Casbin user）只被允许用轻量模型：用假模型会被权限层先拦下，
        # 那样测的就不是"工具集为空"而是"整轮跑不起来"了。
        model_id = "glm-5.3-flash" if role == "user" else "fake-model"
        # 只读角色的策略只放开 chatbot；给它注册一个"白名单里明确包含定时任务工具"
        # 的技能，才能证明拦住它的是 RBAC 而不是技能白名单。
        skill_name = "chatbot" if role == "user" else "default"

        class FakeModelHub:
            def get_chat_model(self, **_kwargs):
                return FakeListChatModel(responses=["ok"])

        class FakeMcpManager:
            servers: dict = {}

            @asynccontextmanager
            async def connect_many(self, _names, **_kwargs):
                yield []

            async def get_mcp_tools(self, _session):
                return []

        with tempfile.TemporaryDirectory() as directory:
            manager = SkillManager(directory)
            manager.register_skill(
                Skill(
                    name="chatbot",
                    description="通用助手",
                    system_prompt="你是助手。",
                    allowed_tool_names=sorted(SCHEDULING_TOOL_NAMES),
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
                with patch.object(AgentEngine, "_agent_factory", recorder):
                    async for _chunk in engine.run(
                        role,
                        "每天早上九点帮我总结一下",
                        {
                            "model_id": model_id,
                            "skill_name": skill_name,
                            "mcp_servers": [],
                            "workspace_id": "workspace-a",
                            "user_id": user_id,
                            "mode": mode,
                        },
                    ):
                        pass

            asyncio.run(drive())
        return captured

    def test_chat_mode_keeps_only_the_scheduling_tools(self):
        captured = self._capture("chat")
        self.assertEqual(set(captured["tools"]), set(SCHEDULING_TOOL_NAMES))

    def test_viewer_gets_no_scheduling_tools_in_any_mode(self):
        for mode in ("chat", "agent"):
            with self.subTest(mode=mode):
                captured = self._capture(mode, role="user")
                self.assertEqual(captured["tools"], [])


class ScheduledRunExecutionTests(unittest.TestCase):
    """到点执行：产出对话与通知，失败要带原因。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_engine = database.engine
        database.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name, 'scheduled-run.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        with Session(database.engine) as session:
            session.add(User(id="u1", email="r@example.com", display_name="R", password_hash="x"))
            session.add(Workspace(id="w1", name="执行", slug="run-w1", owner_id="u1"))
            session.add(Membership(workspace_id="w1", user_id="u1", role="owner"))
            session.add(
                ScheduledJob(
                    id="job1",
                    workspace_id="w1",
                    name="每日晨报",
                    job_type="agent_task",
                    cron="0 9 * * *",
                    prompt="总结工作区昨天新增的任务与执行结果。",
                    model_id="fake-model",
                    skill_name="chatbot",
                    mode="chat",
                    created_by="u1",
                )
            )
            session.commit()

    def tearDown(self):
        database.engine.dispose()
        database.engine = self.original_engine
        self.temp_dir.cleanup()

    def _run(self, engine: _FakeEngine, readiness: str | None = None) -> tuple[str, str]:
        """走调度线程真正用的入口：它负责把状态回写到任务行。

        直接调 execute_job 会跳过回写，"失败不重复通知"那条逻辑就永远看不到
        上一次的失败状态——测试必须覆盖真实入口。
        """
        from core.scheduler import execute_job_by_id

        with patch("api.routes.get_agent_engine", return_value=engine), patch.object(
            ModelHub, "readiness_error", staticmethod(lambda _model_id: readiness)
        ):
            execute_job_by_id("job1")
        with Session(database.engine) as session:
            job = session.get(ScheduledJob, "job1")
            return job.last_status, job.last_message

    def test_successful_run_produces_a_conversation_and_a_notification(self):
        engine = _FakeEngine(reply="昨天新增 3 个任务，2 条执行记录。")
        status, message = self._run(engine)
        self.assertEqual(status, "ok", message)
        self.assertIn("已生成对话", message)

        with Session(database.engine) as session:
            conversations = session.exec(select(Conversation).where(Conversation.workspace_id == "w1")).all()
            self.assertEqual(len(conversations), 1)
            messages = session.exec(
                select(ChatMessage).where(ChatMessage.conversation_id == conversations[0].id)
            ).all()
            self.assertEqual([item.role for item in messages], ["user", "assistant"])
            self.assertEqual(messages[0].content, "总结工作区昨天新增的任务与执行结果。")
            self.assertIn("3 个任务", messages[1].content)
            notifications = session.exec(select(Notification).where(Notification.workspace_id == "w1")).all()
            self.assertEqual(len(notifications), 1)
            self.assertIn("定时任务已完成", notifications[0].title)
            self.assertEqual(notifications[0].link, "chat")
            self.assertEqual(notifications[0].ref_id, conversations[0].id)
            job = session.get(ScheduledJob, "job1")
            self.assertEqual(job.last_conversation_id, conversations[0].id)
        # 定时执行永远用最严权限档，且以发起人的当前角色运行。
        self.assertEqual(engine.calls[0]["config"]["permission_mode"], "default")
        # 引擎只认 Casbin 角色：传产品角色名（owner）会被权限层 403 掉。
        self.assertEqual(engine.calls[0]["role"], "developer")
        self.assertEqual(engine.calls[0]["config"]["user_id"], "u1")

    def test_viewer_creator_runs_with_the_restricted_role(self):
        with Session(database.engine) as session:
            membership = session.exec(select(Membership)).first()
            membership.role = "viewer"
            session.add(membership)
            session.commit()
        engine = _FakeEngine()
        status, _message = self._run(engine)
        self.assertEqual(status, "ok")
        self.assertEqual(engine.calls[0]["role"], "user")

    def test_unavailable_model_fails_without_calling_it(self):
        engine = _FakeEngine()
        status, message = self._run(engine, readiness="未配置该模型")
        self.assertEqual(status, "failed")
        self.assertIn("模型不可用", message)
        self.assertEqual(engine.calls, [])
        with Session(database.engine) as session:
            self.assertEqual(session.exec(select(Conversation)).all(), [])
            notifications = session.exec(select(Notification)).all()
            self.assertEqual(len(notifications), 1)
            self.assertIn("执行失败", notifications[0].title)
            self.assertEqual(notifications[0].link, "automation")
            job = session.get(ScheduledJob, "job1")
            self.assertEqual(job.last_status, "failed")

    def test_missing_skill_fails_with_a_readable_reason(self):
        engine = _FakeEngine(known_skill=False)
        status, message = self._run(engine)
        self.assertEqual(status, "failed")
        self.assertIn("技能", message)
        self.assertEqual(engine.calls, [])

    def test_creator_leaving_the_workspace_stops_the_run(self):
        with Session(database.engine) as session:
            membership = session.exec(select(Membership)).first()
            session.delete(membership)
            session.commit()
        engine = _FakeEngine()
        status, message = self._run(engine)
        self.assertEqual(status, "failed")
        self.assertIn("已不在该工作区", message)
        self.assertEqual(engine.calls, [])

    def test_model_failure_keeps_a_readable_conversation_and_notifies_once(self):
        class ExplodingEngine(_FakeEngine):
            async def run(self, user_role, query, config):
                self.calls.append({"role": user_role, "query": query, "config": config})
                raise RuntimeError("upstream 502")
                yield  # pragma: no cover - 让函数保持异步生成器语义

        engine = ExplodingEngine()
        status, message = self._run(engine)
        self.assertEqual(status, "failed")
        self.assertIn("模型调用失败", message)
        with Session(database.engine) as session:
            conversations = session.exec(select(Conversation)).all()
            self.assertEqual(len(conversations), 1, "失败的执行也要留下这次对话")
            messages = session.exec(
                select(ChatMessage).where(ChatMessage.conversation_id == conversations[0].id)
            ).all()
            self.assertIn("本次定时执行失败", messages[-1].content)
            self.assertEqual(len(session.exec(select(Notification)).all()), 1)

        # 连续失败不再重复轰炸通知中心：状态已经坏了，第一次已经通知过。
        self._run(_FakeEngine(known_skill=False))
        with Session(database.engine) as session:
            self.assertEqual(len(session.exec(select(Notification)).all()), 1)

    def test_unknown_job_type_is_reported_instead_of_crashing(self):
        with Session(database.engine) as session:
            job = session.get(ScheduledJob, "job1")
            job.job_type = "legacy_type"
            session.add(job)
            session.commit()
        status, message = self._run(_FakeEngine())
        self.assertEqual(status, "failed")
        self.assertIn("未知任务类型", message)

    def test_usage_window_is_bounded_by_the_configured_timeout(self):
        """执行时长必须受 AGENT_RUN_TIMEOUT_SECONDS 约束，不能无限挂住调度线程。"""
        with patch.object(settings, "agent_run_timeout_seconds", 0.01):
            with Session(database.engine) as session:
                job = session.get(ScheduledJob, "job1")

                class SlowEngine(_FakeEngine):
                    async def run(self, user_role, query, config):
                        await asyncio.sleep(5)
                        yield "太晚了"

                with patch("api.routes.get_agent_engine", return_value=SlowEngine()), patch.object(
                    ModelHub, "readiness_error", staticmethod(lambda _model_id: None)
                ):
                    status, message = execute_job(session, job)
        self.assertEqual(status, "failed")
        self.assertIn("模型调用失败", message)

    def test_next_run_is_computed_in_local_time(self):
        start_scheduler()
        try:
            with Session(database.engine) as session:
                job = session.get(ScheduledJob, "job1")
                # 手工登记的库内任务不会自动排期，先同步一次触发器。
                from core.scheduler import upsert_job_trigger

                upsert_job_trigger(job)
                upcoming = next_run_at(job.id)
            self.assertIsNotNone(upcoming)
            self.assertIsNotNone(upcoming.tzinfo, "下次运行时间必须带时区，不能是裸时间")
            self.assertGreater(upcoming.astimezone(timezone.utc), datetime.now(timezone.utc) - timedelta(minutes=1))
        finally:
            shutdown_scheduler()


if __name__ == "__main__":
    unittest.main()
