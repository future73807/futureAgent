"""数据库连接、会话和开发环境引导数据。"""
from collections.abc import Generator
from datetime import timedelta

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy import inspect

from config import settings
from db.models import Membership, User, Workspace, now_utc
from db.report_models import (  # 汇报智能体模型
    ReportAssistant,
    ReportDataSource,
    ReportRecord,
    KnowledgeBase,
    ReportAlertRule,
    ReportAlert,
    ReportDailyReport,
    ReportWeeklyReport,
    ReportAssistantMessage,
)

LEGACY_BOOTSTRAP_ADMIN_EMAIL = "admin@futureagent.local"
DEVELOPMENT_BOOTSTRAP_ADMIN_EMAIL = "admin@futureagent.dev"


engine_options: dict = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(settings.database_url, **engine_options)


# These tables were introduced after the initial governed-workspace and
# AgentRun migrations.  They let a pre-20260725_03 installation without an
# Alembic version table be stamped at the last schema it actually has, rather
# than attempting to recreate its existing base tables.
BUSINESS_AGENT_TABLES = {
    "business_assistants",
    "business_data_sources",
    "business_records",
    "business_alert_rules",
    "business_alerts",
    "business_daily_reports",
    "business_boss_tasks",
    "business_assistant_messages",
}

# 汇报智能体表
REPORT_AGENT_TABLES = {
    "report_assistants",
    "report_data_sources",
    "report_records",
    "knowledge_bases",
    "report_alert_rules",
    "report_alerts",
    "report_daily_reports",
    "report_weekly_reports",
    "report_assistant_messages",
}

# Revision 20260725_03 adds both business tables and audit visibility columns.
# A real 20260725_02 installation has every prior table but naturally lacks
# those two new audit columns, so bootstrap detection must ignore only them
# while deciding where to stamp an unversioned legacy database.
PRE_BUSINESS_MISSING_COLUMNS = {
    "audit_events": {"visibility", "owner_user_id"},
}


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def init_db() -> None:
    if settings.run_migrations_on_startup:
        _upgrade_schema()
    elif settings.environment.lower() == "production":
        raise RuntimeError(
            "Production startup requires RUN_MIGRATIONS_ON_STARTUP=true; "
            "do not use metadata.create_all as a migration mechanism."
        )
    else:
        # Local development and unit tests can start from an empty schema.
        # Deployments use Alembic migrations instead (see migrations/).
        SQLModel.metadata.create_all(engine)
    _migrate_legacy_development_admin()
    _seed_development_admin()


def _upgrade_schema() -> None:
    """Apply the checked-in Alembic history before the API accepts traffic."""
    from alembic import command
    from alembic.config import Config

    from config import BASE_DIR

    alembic_config = Config(str(BASE_DIR / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", settings.database_url)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "alembic_version" not in existing_tables:
        if _matches_schema(inspector, set(SQLModel.metadata.tables)):
            # A controlled transition for installations that already include
            # every current model table. No DDL is needed; record the head.
            command.stamp(alembic_config, "head")
            return
        pre_business_tables = set(SQLModel.metadata.tables) - BUSINESS_AGENT_TABLES
        if _matches_schema(
            inspector,
            pre_business_tables,
            ignored_columns=PRE_BUSINESS_MISSING_COLUMNS,
        ):
            # The immediately preceding commercial schema has all governed
            # AgentRun columns but not the operating-agent tables.
            command.stamp(alembic_config, "20260725_02")
        else:
            legacy_tables = pre_business_tables - {"agent_runs"}
            if _matches_schema(
                inspector,
                legacy_tables,
                ignored_columns=PRE_BUSINESS_MISSING_COLUMNS,
            ):
                # The pre-Alembic product schema is known and complete. Stamp
                # that immutable baseline, then apply additive revisions.
                command.stamp(alembic_config, "20260725_00")
    command.upgrade(alembic_config, "head")


def _matches_schema(
    inspector,
    expected_tables: set[str],
    *,
    ignored_columns: dict[str, set[str]] | None = None,
) -> bool:
    existing_tables = set(inspector.get_table_names())
    if not expected_tables or not expected_tables.issubset(existing_tables):
        return False
    ignored_columns = ignored_columns or {}
    return all(
        (
            {column.name for column in SQLModel.metadata.tables[table_name].columns}
            - ignored_columns.get(table_name, set())
        ).issubset({column["name"] for column in inspector.get_columns(table_name)})
        for table_name in expected_tables
    )


def _development_bootstrap_email() -> str:
    """Return a login-compatible development administrator email.

    Older checkouts seeded ``admin@futureagent.local``.  The API deliberately
    validates login addresses using ``EmailStr``, which rejects special-use
    ``.local`` domains, so that account could never sign in through the UI.
    Keep this compatibility shim strictly in development and leave production
    account management to the deployment owner.
    """
    configured = settings.bootstrap_admin_email.lower()
    return DEVELOPMENT_BOOTSTRAP_ADMIN_EMAIL if configured == LEGACY_BOOTSTRAP_ADMIN_EMAIL else configured


def _migrate_legacy_development_admin() -> None:
    """Repair only the legacy local bootstrap account, never production data."""
    if settings.environment.lower() == "production":
        return
    with Session(engine) as session:
        legacy = session.exec(select(User).where(User.email == LEGACY_BOOTSTRAP_ADMIN_EMAIL)).first()
        target_email = _development_bootstrap_email()
        if not legacy or target_email == LEGACY_BOOTSTRAP_ADMIN_EMAIL:
            return
        if session.exec(select(User.id).where(User.email == target_email)).first():
            return
        legacy.email = target_email
        legacy.updated_at = now_utc()
        session.add(legacy)
        session.commit()


def _seed_development_admin() -> None:
    """仅在没有任何用户时创建本地开发管理员。"""
    from db.security import hash_password

    with Session(engine) as session:
        if session.exec(select(User.id).limit(1)).first():
            return
        if settings.environment.lower() == "production":
            return

        admin = User(
            email=_development_bootstrap_email(),
            display_name="平台管理员",
            password_hash=hash_password(settings.bootstrap_admin_password),
            is_platform_admin=True,
        )
        session.add(admin)
        session.flush()
        workspace = Workspace(
            name="我的工作区",
            slug="my-workspace",
            owner_id=admin.id,
        )
        session.add(workspace)
        session.flush()
        session.add(Membership(workspace_id=workspace.id, user_id=admin.id, role="owner"))
        session.commit()
