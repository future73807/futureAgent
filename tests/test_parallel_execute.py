"""并行编排执行测试：批次创建、SSE 事件、隔离线程与批量取消。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

import db.database as database
from config import settings
from main import app

TEST_PASSWORD = "S3ed-" + uuid4().hex[:13] + "!"


class ParallelExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_upload_dir = settings.upload_dir
        cls.original_storage_backend = settings.storage_backend
        cls.original_engine = database.engine
        settings.upload_dir = str(Path(cls.temp_dir.name) / "attachments")
        settings.storage_backend = "local"
        database.engine = create_engine(
            f"sqlite:///{Path(cls.temp_dir.name, 'parallel-test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        cls.client = TestClient(app)
        cls.client.__enter__()

        owner = cls.client.post(
            "/api/v1/auth/register",
            json={
                "email": "par-owner@example.com",
                "password": TEST_PASSWORD,
                "display_name": "Parallel Owner",
                "workspace_name": "Parallel workspace",
            },
        )
        assert owner.status_code == 201, owner.text
        cls.owner_token = owner.json()["access_token"]
        cls.workspace_id = owner.json()["workspaces"][0]["id"]

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

    def _approved_plan_with_steps(self, titles):
        project = self.client.post(
            "/api/v1/projects", json={"name": f"并行项目 {uuid4().hex[:6]}"}, headers=self.headers()
        )
        assert project.status_code == 201, project.text
        task = self.client.post(
            "/api/v1/tasks",
            json={"title": f"并行任务 {uuid4().hex[:6]}", "project_id": project.json()["project"]["id"]},
            headers=self.headers(),
        )
        assert task.status_code == 201, task.text
        task_id = task.json()["task"]["id"]
        plan = self.client.put(
            f"/api/v1/tasks/{task_id}/plan",
            json={"objective": "并行验收目标", "steps": [{"title": title, "instructions": ""} for title in titles]},
            headers=self.headers(),
        )
        assert plan.status_code == 200, plan.text
        step_ids = [step["id"] for step in plan.json()["plan"]["steps"]]
        approved = self.client.post(f"/api/v1/tasks/{task_id}/plan/approve", headers=self.headers())
        assert approved.status_code == 200, approved.text
        return task_id, step_ids

    def test_parallel_execution_requires_approved_plan(self):
        task_id, _ = self._approved_plan_with_steps(["步骤甲"])
        # 用一个未批准计划的任务：直接新建一个计划草稿不批准
        project = self.client.post(
            "/api/v1/projects", json={"name": f"草稿项目 {uuid4().hex[:6]}"}, headers=self.headers()
        )
        task2 = self.client.post(
            "/api/v1/tasks",
            json={"title": "草稿任务", "project_id": project.json()["project"]["id"]},
            headers=self.headers(),
        )
        task2_id = task2.json()["task"]["id"]
        self.client.put(
            f"/api/v1/tasks/{task2_id}/plan",
            json={"objective": "草稿目标", "steps": [{"title": "步骤乙", "instructions": ""}]},
            headers=self.headers(),
        )
        draft = self.client.post(
            f"/api/v1/tasks/{task2_id}/execute-parallel",
            json={"model_id": "gpt-4o-mini", "skill_name": "default"},
            headers=self.headers(),
        )
        self.assertEqual(draft.status_code, 409, draft.text)
        self.assertIsNotNone(task_id)

    def test_parallel_execution_runs_all_steps_isolated(self):
        task_id, step_ids = self._approved_plan_with_steps(["并行步骤一", "并行步骤二", "并行步骤三"])

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
                thread = kwargs["config"]["thread_id"]
                yield f"part1::{thread}"
                yield f"part2::{thread}"

        with (
            patch("api.routes.get_agent_engine", return_value=FakeEngine()),
            patch("api.routes._ensure_model_ready"),
        ):
            response = self.client.post(
                f"/api/v1/tasks/{task_id}/execute-parallel",
                json={"model_id": "gpt-4o-mini", "skill_name": "default", "mcp_servers": []},
                headers=self.headers(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        text = response.text
        self.assertIn("event: meta", text)
        self.assertIn("batch_id", text)
        self.assertEqual(text.count("event: step-done"), 3, text[-800:])
        self.assertIn("event: done", text)

        import json as jsonlib

        meta_line = next(line for line in text.splitlines() if line.startswith('data: {"batch_id"'))
        batch_id = jsonlib.loads(meta_line[5:])["batch_id"]

        runs = self.client.get(f"/api/v1/tasks/{task_id}/runs", headers=self.headers()).json()["runs"]
        self.assertEqual(len(runs), 3)
        self.assertTrue(all(run["status"] == "succeeded" for run in runs))
        self.assertTrue(all(run["batch_id"] == batch_id for run in runs))
        # 线程隔离：每个 run 的输出包含自己的 step thread 标识
        for run in runs:
            self.assertIn(f"governed-task-{task_id}-step-{run['step_id']}", run["output"])

    def test_parallel_execution_rejects_when_no_executable_steps(self):
        task_id, step_ids = self._approved_plan_with_steps(["已被占用的步骤"])
        with Session(database.engine) as session:
            from db.models import WorkPlanStep

            for step_id in step_ids:
                step = session.get(WorkPlanStep, step_id)
                step.status = "done"
                session.add(step)
            session.commit()
        response = self.client.post(
            f"/api/v1/tasks/{task_id}/execute-parallel",
            json={"model_id": "gpt-4o-mini", "skill_name": "default"},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_cancel_batch_endpoint(self):
        task_id, step_ids = self._approved_plan_with_steps(["取消批次步骤"])
        response = self.client.post(
            f"/api/v1/tasks/{task_id}/runs/cancel-batch",
            json={"batch_id": "nonexistent-batch"},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["cancelled"], 0)

    def test_batch_history_persisted_after_execution(self):
        from types import SimpleNamespace

        task_id, _ = self._approved_plan_with_steps(["历史步骤甲", "历史步骤乙"])

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
                yield "历史输出"

        with (
            patch("api.routes.get_agent_engine", return_value=FakeEngine()),
            patch("api.routes._ensure_model_ready"),
            # 测试环境无 Postgres：checkpointer 直接降级为 None
            patch("core.checkpointer.settings", SimpleNamespace(checkpoint_conn_str="sqlite:///memory")),
        ):
            response = self.client.post(
                f"/api/v1/tasks/{task_id}/execute-parallel",
                json={"model_id": "gpt-4o-mini", "skill_name": "default"},
                headers=self.headers(),
            )
        self.assertEqual(response.status_code, 200, response.text)

        batches = self.client.get(
            f"/api/v1/tasks/{task_id}/batches",
            headers=self.headers(),
        )
        self.assertEqual(batches.status_code, 200, batches.text)
        payload = batches.json()["batches"]
        self.assertEqual(len(payload), 1)
        batch = payload[0]
        self.assertEqual(batch["status"], "succeeded")
        self.assertEqual(batch["total_steps"], 2)
        self.assertEqual(batch["succeeded_count"], 2)
        self.assertIsNotNone(batch["finished_at"])

        detail = self.client.get(
            f"/api/v1/tasks/{task_id}/batches/{batch['id']}",
            headers=self.headers(),
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(len(detail.json()["runs"]), 2)
        self.assertTrue(all(run["status"] == "succeeded" for run in detail.json()["runs"]))

    def test_parallel_execution_with_step_ids_subset_and_done_payload(self):
        task_id, step_ids = self._approved_plan_with_steps(["子集一", "子集二"])

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
                yield "subset output"

        with patch("api.routes.get_agent_engine", return_value=FakeEngine()),                 patch("api.routes._ensure_model_ready"):
            response = self.client.post(
                f"/api/v1/tasks/{task_id}/execute-parallel",
                json={"model_id": "gpt-4o-mini", "skill_name": "default", "step_ids": step_ids[:1]},
                headers=self.headers(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('failed_step_ids', response.text)
        runs = self.client.get(f"/api/v1/tasks/{task_id}/runs", headers=self.headers()).json()["runs"]
        self.assertEqual(len(runs), 1)
        # 未选中的步骤保持 pending，可后续单独执行
        plan = self.client.get(f"/api/v1/tasks/{task_id}/plan", headers=self.headers()).json()["plan"]
        untouched = next(step for step in plan["steps"] if step["id"] == step_ids[1])
        self.assertEqual(untouched["status"], "pending")


if __name__ == "__main__":
    unittest.main()
