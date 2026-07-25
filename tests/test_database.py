from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

import db.database as database
from config import settings
from db.database import BUSINESS_AGENT_TABLES, _matches_schema


class _Inspector:
    def __init__(self, tables: set[str]):
        self.tables = tables

    def get_table_names(self):
        return list(self.tables)

    def get_columns(self, table_name: str):
        return [{"name": column.name} for column in SQLModel.metadata.tables[table_name].columns]


class MigrationBaselineTests(unittest.TestCase):
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
                with engine.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql("select version_num from alembic_version").scalar_one(),
                        "20260725_03",
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
                        "20260725_03",
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
                        "20260725_03",
                    )
            finally:
                database.engine = original_engine
                migration_engine.dispose()


if __name__ == "__main__":
    unittest.main()
