from __future__ import annotations

import os
import unittest
import tempfile
from argparse import Namespace
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

import db.database as database
from config import settings
from db.database import BUSINESS_AGENT_TABLES, _matches_schema

# 迁移链的当前 head；新增迁移时只需更新这一处。
CURRENT_HEAD = "20260913_23"


class _Inspector:
    def __init__(self, tables: set[str]):
        self.tables = tables

    def get_table_names(self):
        return list(self.tables)

    def get_columns(self, table_name: str):
        return [{"name": column.name} for column in SQLModel.metadata.tables[table_name].columns]


class MigrationBaselineTests(unittest.TestCase):
    def test_cli_uses_project_database_setting_instead_of_ini_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "cli-default.db"
            placeholder_path = Path(directory) / "ini-placeholder.db"
            url = f"sqlite:///{database_path.as_posix()}"

            bootstrap_config = Config("alembic.ini")
            bootstrap_config.set_main_option("sqlalchemy.url", url)
            command.upgrade(bootstrap_config, "head")

            output = StringIO()
            cli_config = Config("alembic.ini", stdout=output, cmd_opts=Namespace())
            cli_config.set_main_option(
                "sqlalchemy.url", f"sqlite:///{placeholder_path.as_posix()}"
            )
            with patch.object(settings, "database_url", url), patch.dict(os.environ):
                os.environ.pop("DATABASE_URL", None)
                command.current(cli_config)

            self.assertIn(CURRENT_HEAD, output.getvalue())
            self.assertFalse(placeholder_path.exists())

    def test_programmatic_database_url_is_not_overridden_by_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            explicit_path = Path(directory) / "explicit.db"
            environment_path = Path(directory) / "environment.db"
            explicit_url = f"sqlite:///{explicit_path.as_posix()}"
            environment_url = f"sqlite:///{environment_path.as_posix()}"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", explicit_url)

            with (
                patch.object(settings, "database_url", environment_url),
                patch.dict(os.environ, {"DATABASE_URL": environment_url}),
            ):
                command.upgrade(config, "head")

            engine = create_engine(explicit_url)
            try:
                with engine.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "select version_num from alembic_version"
                        ).scalar_one(),
                        CURRENT_HEAD,
                    )
            finally:
                engine.dispose()
            self.assertFalse(environment_path.exists())

    def test_pre_alembic_schema_is_recognised_as_a_safe_baseline(self):
        legacy_tables = set(SQLModel.metadata.tables) - BUSINESS_AGENT_TABLES - {"agent_runs"}
        self.assertTrue(_matches_schema(_Inspector(legacy_tables), legacy_tables))
        self.assertFalse(_matches_schema(_Inspector(legacy_tables), set(SQLModel.metadata.tables)))

    def test_empty_database_upgrades_to_current_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "migration-test.db"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
            command.upgrade(config, "head")
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            try:
                tables = set(inspect(engine).get_table_names())
                self.assertTrue({"agent_runs", "attachments", "alembic_version"}.issubset(tables))
                agent_run_columns = {
                    column["name"] for column in inspect(engine).get_columns("agent_runs")
                }
                self.assertIn("mcp_servers_json", agent_run_columns)
                self.assertIn("tool_trace_json", agent_run_columns)
                with engine.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql("select version_num from alembic_version").scalar_one(),
                        CURRENT_HEAD,
                    )
            finally:
                engine.dispose()

    def test_existing_20260725_02_database_upgrades_to_business_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "existing-02.db"
            url = f"sqlite:///{database_path.as_posix()}"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url)
            command.upgrade(config, "20260725_02")
            command.upgrade(config, "head")
            engine = create_engine(url)
            try:
                tables = set(inspect(engine).get_table_names())
                self.assertTrue(
                    {
                        "business_assistants",
                        "business_data_sources",
                        "business_records",
                        "business_alerts",
                        "business_daily_reports",
                        "business_boss_tasks",
                    }.issubset(tables)
                )
                with engine.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql("select version_num from alembic_version").scalar_one(),
                        CURRENT_HEAD,
                    )
            finally:
                engine.dispose()

    def test_unversioned_20260725_02_schema_is_stamped_then_only_business_revision_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "unversioned-02.db"
            url = f"sqlite:///{database_path.as_posix()}"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url)
            command.upgrade(config, "20260725_02")
            bootstrap_engine = create_engine(url)
            try:
                with bootstrap_engine.begin() as connection:
                    connection.exec_driver_sql("drop table alembic_version")
            finally:
                bootstrap_engine.dispose()

            original_engine = database.engine
            migration_engine = create_engine(url, connect_args={"check_same_thread": False})
            database.engine = migration_engine
            try:
                with patch.object(settings, "database_url", url):
                    database._upgrade_schema()
                tables = set(inspect(migration_engine).get_table_names())
                self.assertIn("business_assistants", tables)
                with migration_engine.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql("select version_num from alembic_version").scalar_one(),
                        CURRENT_HEAD,
                    )
            finally:
                database.engine = original_engine
                migration_engine.dispose()

    def test_default_development_startup_upgrades_unversioned_report_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "unversioned-report.db"
            url = f"sqlite:///{database_path.as_posix()}"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url)
            command.upgrade(config, "20260726_04")
            bootstrap_engine = create_engine(url)
            try:
                with bootstrap_engine.begin() as connection:
                    connection.exec_driver_sql(
                        "create table custom_extension_state (id integer primary key)"
                    )
                    connection.exec_driver_sql("drop table alembic_version")
            finally:
                bootstrap_engine.dispose()

            original_engine = database.engine
            migration_engine = create_engine(url, connect_args={"check_same_thread": False})
            database.engine = migration_engine
            try:
                with (
                    patch.object(settings, "database_url", url),
                    patch.object(settings, "run_migrations_on_startup", False),
                    patch.object(settings, "environment", "development"),
                ):
                    database.init_db()
                columns = {
                    column["name"]
                    for column in inspect(migration_engine).get_columns("agent_runs")
                }
                self.assertIn("mcp_servers_json", columns)
                self.assertIn("tool_trace_json", columns)
                with migration_engine.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "select version_num from alembic_version"
                        ).scalar_one(),
                            CURRENT_HEAD,
                    )
            finally:
                database.engine = original_engine
                migration_engine.dispose()

    def test_unversioned_business_revision_is_stamped_at_03_before_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "unversioned-business.db"
            url = f"sqlite:///{database_path.as_posix()}"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url)
            command.upgrade(config, "20260725_03")
            bootstrap_engine = create_engine(url)
            try:
                with bootstrap_engine.begin() as connection:
                    connection.exec_driver_sql(
                        "create table custom_business_extension (id integer primary key)"
                    )
                    connection.exec_driver_sql("drop table alembic_version")
            finally:
                bootstrap_engine.dispose()

            original_engine = database.engine
            migration_engine = create_engine(url, connect_args={"check_same_thread": False})
            database.engine = migration_engine
            try:
                with patch.object(settings, "database_url", url):
                    database._upgrade_schema()
                tables = set(inspect(migration_engine).get_table_names())
                self.assertIn("business_assistants", tables)
                self.assertIn("report_assistants", tables)
                columns = {
                    column["name"]
                    for column in inspect(migration_engine).get_columns("agent_runs")
                }
                self.assertIn("mcp_servers_json", columns)
                self.assertIn("tool_trace_json", columns)
                with migration_engine.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "select version_num from alembic_version"
                        ).scalar_one(),
                            CURRENT_HEAD,
                    )
            finally:
                database.engine = original_engine
                migration_engine.dispose()

    def test_unversioned_previous_head_database_is_stamped_and_not_replayed(self):
        """上一个 head 的无版本库必须被正确识别，而不是从零重跑迁移链。

        这正是"给已有表加一列"最容易踩的坑：新列不在旧库识别要忽略的清单里，
        每个分支都匹配失败，代码就会以为这是一套陌生 schema，从头重跑整条链，
        在已经存在的表上再做一次 batch_alter，启动直接崩。这里锁住"加列必须
        同时登记到 PRE_*_MISSING_COLUMNS"这条约束。
        """
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "unversioned-prev-head.db"
            url = f"sqlite:///{database_path.as_posix()}"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url)
            # 停在本改动之前的那一版，然后抹掉版本表，模拟"升级前的老库"。
            command.upgrade(config, "20260912_21")
            bootstrap_engine = create_engine(url)
            try:
                with bootstrap_engine.begin() as connection:
                    connection.exec_driver_sql(
                        "insert into workspaces (id, name, slug, owner_id, plan, permission_mode, created_at, updated_at)"
                        " values ('legacy-ws', '老工作区', 'legacy-ws', 'legacy-user', 'starter', 'default',"
                        " '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                    )
                    connection.exec_driver_sql("drop table alembic_version")
            finally:
                bootstrap_engine.dispose()

            original_engine = database.engine
            migration_engine = create_engine(url, connect_args={"check_same_thread": False})
            database.engine = migration_engine
            try:
                with patch.object(settings, "database_url", url):
                    database._upgrade_schema()
                columns = {
                    column["name"]
                    for column in inspect(migration_engine).get_columns("workspaces")
                }
                self.assertIn("preferences_json", columns)
                with migration_engine.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "select version_num from alembic_version"
                        ).scalar_one(),
                        CURRENT_HEAD,
                    )
                    # 回填的默认值必须让老工作区开箱可用，而不是留下一列 NULL。
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "select preferences_json from workspaces where id = 'legacy-ws'"
                        ).scalar_one(),
                        "{}",
                    )
            finally:
                database.engine = original_engine
                migration_engine.dispose()

    def test_migration_targets_the_inspected_engine_not_the_configured_url(self):
        """迁移必须写"被检查的那个库"，而不是 settings.database_url 指向的库。

        这两个值可以不一致：测试注入临时 engine、或进程拿到过期配置时都会。
        一旦不一致，`_matches_schema` 在 A 库上得出"已是最新"，Alembic 就把
        **B 库**直接 stamp 成 head；B 库此后永远认为自己已升级，缺的列再也
        补不上，而应用要等到第一次查询才以 "no such column" 崩掉。
        """
        with tempfile.TemporaryDirectory() as directory:
            inspected_path = Path(directory) / "inspected.db"
            inspected_url = f"sqlite:///{inspected_path.as_posix()}"
            # 另一个库：版本停在上一版，且缺 preferences_json，是这次要修的对象。
            other_path = Path(directory) / "configured.db"
            other_url = f"sqlite:///{other_path.as_posix()}"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", other_url)
            command.upgrade(config, "20260912_21")

            original_engine = database.engine
            migration_engine = create_engine(
                inspected_url, connect_args={"check_same_thread": False}
            )
            database.engine = migration_engine
            try:
                with patch.object(settings, "database_url", other_url):
                    database._upgrade_schema()
                # 被检查的库没有任何表：正确行为是就地建到 head。
                with migration_engine.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "select version_num from alembic_version"
                        ).scalar_one(),
                        CURRENT_HEAD,
                    )
                    self.assertIn(
                        "workspaces",
                        {row[0] for row in connection.exec_driver_sql(
                            "select name from sqlite_master where type='table'"
                        )},
                    )
            finally:
                database.engine = original_engine
                migration_engine.dispose()

            # 另一个库必须原封不动：版本停在原处，新列没有被加进去。
            # （升级到 20260912_21 本来就会建出 workspaces 表，所以这里断言的是
            #  "没有被动过"，而不是"表不存在"。）
            check = create_engine(other_url)
            try:
                with check.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "select version_num from alembic_version"
                        ).scalar_one(),
                        "20260912_21",
                    )
                other_columns = {
                    column["name"] for column in inspect(check).get_columns("workspaces")
                }
                self.assertNotIn("preferences_json", other_columns)
            finally:
                check.dispose()

    def test_leftover_batch_tables_are_removed_before_retrying(self):
        """清残留只认 _alembic_tmp_*，不碰业务表。"""
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "leftover.db"
            url = f"sqlite:///{database_path.as_posix()}"
            original_engine = database.engine
            migration_engine = create_engine(url, connect_args={"check_same_thread": False})
            database.engine = migration_engine
            try:
                with migration_engine.begin() as connection:
                    connection.exec_driver_sql(
                        "create table _alembic_tmp_workspaces (id varchar(64) primary key)"
                    )
                    connection.exec_driver_sql(
                        "create table workspaces (id varchar(64) primary key)"
                    )
                dropped = database._drop_leftover_batch_tables()
                self.assertEqual(dropped, ["_alembic_tmp_workspaces"])
                remaining = set(inspect(migration_engine).get_table_names())
                self.assertNotIn("_alembic_tmp_workspaces", remaining)
                self.assertIn("workspaces", remaining)
            finally:
                database.engine = original_engine
                migration_engine.dispose()

    def test_existing_agent_run_keeps_unknown_agent_config_as_null(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "existing-report-run.db"
            url = f"sqlite:///{database_path.as_posix()}"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url)
            command.upgrade(config, "20260726_04")
            engine = create_engine(url)
            try:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        """
                        insert into agent_runs (
                            id, workspace_id, task_id, requested_by,
                            model_id, skill_name, status, output,
                            error_message, started_at, attempt
                        ) values (
                            'legacy-run', 'legacy-workspace', 'legacy-task',
                            'legacy-user', 'glm-5.3-flash', 'default', 'failed',
                            '', 'legacy failure', '2026-08-09 00:00:00', 1
                        )
                        """
                    )
            finally:
                engine.dispose()

            command.upgrade(config, "head")
            engine = create_engine(url)
            try:
                with engine.connect() as connection:
                    self.assertIsNone(
                        connection.exec_driver_sql(
                            "select mcp_servers_json from agent_runs where id='legacy-run'"
                        ).scalar_one()
                    )
                    self.assertIsNone(
                        connection.exec_driver_sql(
                            "select tool_trace_json from agent_runs where id='legacy-run'"
                        ).scalar_one()
                    )
            finally:
                engine.dispose()

    def test_unversioned_revision_05_is_stamped_before_trace_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "unversioned-05.db"
            url = f"sqlite:///{database_path.as_posix()}"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url)
            command.upgrade(config, "20260809_05")
            bootstrap_engine = create_engine(url)
            try:
                with bootstrap_engine.begin() as connection:
                    connection.exec_driver_sql("drop table alembic_version")
            finally:
                bootstrap_engine.dispose()

            original_engine = database.engine
            migration_engine = create_engine(url, connect_args={"check_same_thread": False})
            database.engine = migration_engine
            try:
                with patch.object(settings, "database_url", url):
                    database._upgrade_schema()
                columns = {
                    column["name"]
                    for column in inspect(migration_engine).get_columns("agent_runs")
                }
                self.assertTrue({"mcp_servers_json", "tool_trace_json"}.issubset(columns))
                with migration_engine.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "select version_num from alembic_version"
                        ).scalar_one(),
                        CURRENT_HEAD,
                    )
            finally:
                database.engine = original_engine
                migration_engine.dispose()

    def test_half_applied_migration_self_heals(self):
        """复现强杀场景：表已建但 alembic_version 未写 → 启动时自动对齐。"""
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "half-migrated.db"
            url = f"sqlite:///{database_path.as_posix()}"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url)
            # 正常升到 _10（conversation summary），随后模拟强杀：手写 _11 的表但不写版本
            command.upgrade(config, "20260902_10")
            bootstrap_engine = create_engine(url)
            try:
                with bootstrap_engine.begin() as connection:
                    connection.exec_driver_sql(
                        "create table task_comments (id varchar primary key, workspace_id varchar, "
                        "task_id varchar, author_id varchar, content varchar, created_at timestamp)"
                    )
                    connection.exec_driver_sql("drop table alembic_version")
            finally:
                bootstrap_engine.dispose()

            original_engine = database.engine
            migration_engine = create_engine(url, connect_args={"check_same_thread": False})
            database.engine = migration_engine
            try:
                with patch.object(settings, "database_url", url):
                    database._upgrade_schema()
                with migration_engine.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql("select version_num from alembic_version").scalar_one(),
                        CURRENT_HEAD,
                    )
            finally:
                database.engine = original_engine
                migration_engine.dispose()


if __name__ == "__main__":
    unittest.main()
