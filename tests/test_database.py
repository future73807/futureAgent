from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

from db.database import _matches_schema


class _Inspector:
    def __init__(self, tables: set[str]):
        self.tables = tables

    def get_table_names(self):
        return list(self.tables)

    def get_columns(self, table_name: str):
        return [{"name": column.name} for column in SQLModel.metadata.tables[table_name].columns]


class MigrationBaselineTests(unittest.TestCase):
    def test_pre_alembic_schema_is_recognised_as_a_safe_baseline(self):
        legacy_tables = set(SQLModel.metadata.tables) - {"agent_runs"}
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
                        "20260725_02",
                    )
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
