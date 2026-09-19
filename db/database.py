"""数据库连接、会话和开发环境引导数据。"""
import logging
import re
from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy import inspect, text

from config import settings
from db.knowledge_models import (  # 知识库模型（导入同时完成 metadata 注册）
    KnowledgeBase,
    KnowledgeChunk,
)
from db.models import Membership, User, Workspace, now_utc

LEGACY_BOOTSTRAP_ADMIN_EMAIL = "admin@futureagent.local"
DEVELOPMENT_BOOTSTRAP_ADMIN_EMAIL = "admin@futureagent.dev"


engine_options: dict = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(settings.database_url, **engine_options)


# 知识库（RAG）表由 20260726_04 与 20260902_14 引入，是当前仍在用的特性表。
# 判定"20260726_04 之前的老库"时要把它们从期望表里排除，否则每个历史分支的
# _matches_schema 都会因为缺这两张表而落空。
KNOWLEDGE_TABLES = {
    KnowledgeBase.__tablename__,
    KnowledgeChunk.__tablename__,
}

# 汇报/经营智能体与自动化调度的表。产品收敛到单一智能体后由迁移
# 20260919_25 删除，模型层已不存在这些表；无版本旧库里若还留着它们，
# 说明该库在删除迁移之前就已是完整结构，需要让它真的跑一遍删除迁移。
DROPPED_FEATURE_TABLES = {
    "business_assistants",
    "business_data_sources",
    "business_records",
    "business_alert_rules",
    "business_alerts",
    "business_daily_reports",
    "business_boss_tasks",
    "business_assistant_messages",
    "report_assistants",
    "report_data_sources",
    "report_records",
    "report_alert_rules",
    "report_alerts",
    "report_daily_reports",
    "report_weekly_reports",
    "report_monthly_reports",
    "report_assistant_messages",
    "scheduled_jobs",
}

# 删除迁移的前一版。无版本库里"结构已是当前模型、但还带着已删除表"时
# 从这里起跑，只补跑删除迁移，而不是整条链或直接 stamp head。
DROP_FEATURE_TABLES_BASE_REVISION = "20260915_24"

# 通知中心、交付物与近期的增量表。旧库识别时忽略它们：缺少这些表只说明
# 版本停在迁移链早期，升级链会以增量表把它们补齐。
# 近期版本（06-18）由 ADDITIVE_STEPS 阶梯精确判定；更旧的库走 legacy 分支。
NEWEST_FEATURE_TABLES = {
    "notifications",
    "notification_targets",
    "deliverables",
    "task_comments",
    "knowledge_chunks",
    "agent_run_batches",
    "usage_records",
    # 创造模式的自建智能体表。必须登记在这里：否则它会被算进"老库应该有的表"，
    # 每个历史分支的 _matches_schema 都不匹配，最后一个分支也落空 —— 结果是从头
    # 重跑整条迁移链，在已存在的表上再 batch_alter 一次。
    "custom_agents",
}

# Revision 20260725_03 added the audit visibility columns (its operating-agent
# tables were dropped again later). A real 20260725_02 installation has every
# prior table but naturally lacks those two columns, so bootstrap detection must
# ignore only them while deciding where to stamp an unversioned legacy database.
PRE_BUSINESS_MISSING_COLUMNS = {
    "audit_events": {"visibility", "owner_user_id"},
    "agent_runs": {"mcp_servers_json", "tool_trace_json"},
}

# Unversioned development SQLite databases exist at both recent revisions.
# Check the newest shape first: a revision-05 database already has the MCP
# selection column and only lacks the new tool trace column.  Older revision-04
# databases lack both columns and must run both additive migrations.
PRE_AGENT_RUN_TRACE_MISSING_COLUMNS = {
    "agent_runs": {"tool_trace_json"},
}

PRE_AGENT_RUN_MCP_MISSING_COLUMNS = {
    "agent_runs": {"mcp_servers_json", "tool_trace_json"},
}

# 滚动摘要是 conversations 的最新增量列；旧库识别时统一忽略。
PRE_SUMMARY_MISSING_COLUMNS = {"conversations": {"summary"}}

# 批次标识是 agent_runs 的最新增量列；旧库识别时统一忽略。
PRE_BATCH_MISSING_COLUMNS = {"agent_runs": {"batch_id"}}

# 权限档位是 workspaces 的最新增量列；旧库识别时统一忽略。
PRE_PERMISSION_MODE_MISSING_COLUMNS = {"workspaces": {"permission_mode"}}

# 运行模式与轮次证据是 agent_runs 的最新增量列；旧库识别时统一忽略。
PRE_AGENT_MODE_MISSING_COLUMNS = {"agent_runs": {"agent_mode", "iterations_json"}}

# 消息级执行上下文是 chat_messages 的最新增量列；旧库识别时统一忽略。
PRE_CHAT_AGENT_CONTEXT_MISSING_COLUMNS = {
    "chat_messages": {"agent_mode", "usage_json", "iterations_json"}
}

# 工作区偏好是 workspaces 的最新增量列；旧库识别时统一忽略。
# 漏掉这里的后果不只是"认错版本"：缺列的旧库会一路落到最后的 legacy 分支
# 全不匹配，于是从头重跑整条迁移链，在已存在的表上再做一次 batch_alter。
PRE_WORKSPACE_PREFERENCES_MISSING_COLUMNS = {"workspaces": {"preferences_json"}}

# 增量特性表 → 引入它的迁移版本（从新到旧）。无 alembic_version 的库按
# "已拥有的最高阶梯表" 判定其实际版本，避免误判到过旧的基线重建全库。
ADDITIVE_STEPS = [
    # 无版本库若已经有 self-built agent 表，说明至少到过 20260913_23。
    ("20260913_23", {"custom_agents"}),
    ("20260911_18", {"usage_records"}),
    ("20260902_15", {"agent_run_batches"}),
    ("20260902_14", {"knowledge_chunks"}),
    ("20260902_10", {"task_comments"}),
    ("20260902_09", {"deliverables"}),
    ("20260902_07", {"notifications", "notification_targets"}),
]


def _ignored_columns(*ignored_sets: dict[str, set[str]]) -> dict[str, set[str]]:
    merged: dict[str, set[str]] = {}
    for ignored in ignored_sets:
        for table_name, columns in ignored.items():
            merged.setdefault(table_name, set()).update(columns)
    return merged


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def _read_alembic_version() -> str | None:
    """读取当前 alembic 版本；无版本表时返回 None。"""
    if "alembic_version" not in set(inspect(engine).get_table_names()):
        return None
    from sqlalchemy import text

    with engine.connect() as connection:
        row = connection.execute(text("select version_num from alembic_version")).first()
    return row[0] if row else None


def _drop_leftover_batch_tables() -> list[str]:
    """清掉 batch_alter_table 可能留下的 ``_alembic_tmp_*`` 临时表。

    SQLite 的 batch 模式在需要重建表时是"建临时表 → 拷数据 → 删原表 → 改名"；
    进程在改名那一步被杀掉就会留下临时表，之后每次重试都直接失败在
    "table _alembic_tmp_xxx already exists"。单纯 ADD COLUMN 走的是 SQLite
    原生 ALTER，不建临时表；但只要迁移里出现改类型、删列这类操作就会重建，
    所以这里统一先清一次再重试。失败不影响主流程——真正的错误由调用方抛出。
    """
    dropped: list[str] = []
    try:
        with engine.begin() as connection:
            rows = connection.execute(
                text(
                    "select name from sqlite_master where type='table' "
                    "and name like '\\_alembic\\_tmp\\_%' escape '\\'"
                )
            ).all()
            for (name,) in rows:
                if re.fullmatch(r"_alembic_tmp_[A-Za-z0-9_]+", name or ""):
                    connection.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
                    dropped.append(name)
    except Exception:  # noqa: BLE001 - 清残留失败不该比迁移本身更早抛错
        logging.getLogger(__name__).warning("failed to drop leftover batch tables", exc_info=True)
    return dropped


def _upgrade_stepwise(alembic_config, start_after: str | None) -> None:
    """从 start_after 之后的版本逐个升级。

    单版失败且错误为对象已存在（半迁移：效果已落库但版本未写）时，
    记录该版本为已应用并继续，从而自愈强杀进程留下的中间状态。
    """
    from alembic import command
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_config)
    chain = []
    revision = script.get_revision("head")
    while revision is not None:
        chain.append(revision.revision)
        revision = script.get_revision(revision.down_revision) if revision.down_revision else None
    chain.reverse()
    if start_after in chain:
        chain = chain[chain.index(start_after) + 1 :]
    for rev in chain:
        for attempt in range(2):
            try:
                command.upgrade(alembic_config, rev)
                break
            except Exception as exc:  # noqa: BLE001
                message = str(exc).lower()
                # 残留临时表导致的 "already exists" 不是半迁移证据，先清后重试。
                if attempt == 0 and _drop_leftover_batch_tables():
                    continue
                if "already exists" in message or "duplicate column" in message:
                    # 半迁移自愈：该版本的效果已在库中，记录版本继续
                    command.stamp(alembic_config, rev)
                    break
                raise


def init_db() -> None:
    if settings.run_migrations_on_startup:
        _upgrade_schema()
    elif settings.environment.lower() == "production":
        raise RuntimeError(
            "Production startup requires RUN_MIGRATIONS_ON_STARTUP=true; "
            "do not use metadata.create_all as a migration mechanism."
        )
    else:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        if not existing_tables:
            SQLModel.metadata.create_all(engine)
        elif not _matches_schema(inspector, set(SQLModel.metadata.tables)):
            _upgrade_schema()
    _migrate_legacy_development_admin()
    _seed_development_admin()


def _upgrade_schema() -> None:
    """Apply the checked-in Alembic history before the API accepts traffic."""
    from alembic import command
    from alembic.config import Config

    from config import BASE_DIR

    alembic_config = Config(str(BASE_DIR / "alembic.ini"))
    # 必须用被检查的那个 engine 自己的 URL，而不是 settings.database_url。
    # 两者不一致时（测试注入临时 engine、或多进程拿到不同配置），下面
    # `_matches_schema` 判定的是 A 库，Alembic 却去写 B 库：A 库"已是最新"
    # 的结论会变成对 B 库的一次 `stamp head`，B 库从此以为自己已升级，
    # 而缺的列永远补不上。render_as_string 保留密码，Alembic 需要它连库。
    alembic_config.set_main_option(
        "sqlalchemy.url", engine.url.render_as_string(hide_password=False)
    )
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "alembic_version" not in existing_tables:
        # Exclude the knowledge tables and the newest feature tables when
        # detecting legacy schemas: their absence only means the install
        # predates those revisions, and the additive chain recreates them.
        current_tables = set(SQLModel.metadata.tables)
        core_current = current_tables - NEWEST_FEATURE_TABLES
        pre_knowledge_tables = current_tables - KNOWLEDGE_TABLES - NEWEST_FEATURE_TABLES
        if _matches_schema(inspector, current_tables):
            # A controlled transition for installations that already include
            # every current model table.
            if existing_tables & DROPPED_FEATURE_TABLES:
                # 表结构已经对齐，但库里还留着已删除智能体的表：停在前一版并
                # 立刻补跑删除迁移。直接 stamp head 会让这些表永远留在库里。
                command.stamp(alembic_config, DROP_FEATURE_TABLES_BASE_REVISION)
                _upgrade_stepwise(alembic_config, DROP_FEATURE_TABLES_BASE_REVISION)
                _warn_on_schema_gap()
            else:
                # No DDL is needed; record the head.
                command.stamp(alembic_config, "head")
            return
        # 无版本表的近期安装：按已拥有的最高增量表判定版本（新→旧）。
        legacy_ignored = _ignored_columns(
            PRE_AGENT_RUN_TRACE_MISSING_COLUMNS,
            PRE_SUMMARY_MISSING_COLUMNS,
            PRE_BATCH_MISSING_COLUMNS,
            PRE_PERMISSION_MODE_MISSING_COLUMNS,
            PRE_AGENT_MODE_MISSING_COLUMNS,
            PRE_CHAT_AGENT_CONTEXT_MISSING_COLUMNS,
            PRE_WORKSPACE_PREFERENCES_MISSING_COLUMNS,
        )
        for revision, marker_tables in ADDITIVE_STEPS:
            if _matches_schema(inspector, set(marker_tables), ignored_columns=legacy_ignored):
                command.stamp(alembic_config, revision)
                break
        else:
            if _matches_schema(
                inspector,
                core_current,
                ignored_columns=legacy_ignored,
            ):
                command.stamp(alembic_config, "20260809_05")
            elif _matches_schema(
                inspector,
                core_current,
                ignored_columns=_ignored_columns(
                    PRE_AGENT_RUN_MCP_MISSING_COLUMNS,
                    PRE_SUMMARY_MISSING_COLUMNS,
                    PRE_BATCH_MISSING_COLUMNS,
                    PRE_PERMISSION_MODE_MISSING_COLUMNS,
                    PRE_AGENT_MODE_MISSING_COLUMNS,
                    PRE_CHAT_AGENT_CONTEXT_MISSING_COLUMNS,
                    PRE_WORKSPACE_PREFERENCES_MISSING_COLUMNS,
                ),
            ):
                command.stamp(alembic_config, "20260726_04")
            elif not (existing_tables & KNOWLEDGE_TABLES) and _matches_schema(
                inspector,
                pre_knowledge_tables,
                ignored_columns=_ignored_columns(
                    PRE_AGENT_RUN_MCP_MISSING_COLUMNS,
                    PRE_SUMMARY_MISSING_COLUMNS,
                    PRE_BATCH_MISSING_COLUMNS,
                    PRE_PERMISSION_MODE_MISSING_COLUMNS,
                    PRE_AGENT_MODE_MISSING_COLUMNS,
                    PRE_CHAT_AGENT_CONTEXT_MISSING_COLUMNS,
                    PRE_WORKSPACE_PREFERENCES_MISSING_COLUMNS,
                ),
            ):
                command.stamp(alembic_config, "20260725_03")
            elif _matches_schema(
                inspector,
                pre_knowledge_tables,
                ignored_columns=_ignored_columns(
                    PRE_BUSINESS_MISSING_COLUMNS,
                    PRE_SUMMARY_MISSING_COLUMNS,
                    PRE_BATCH_MISSING_COLUMNS,
                    PRE_PERMISSION_MODE_MISSING_COLUMNS,
                    PRE_AGENT_MODE_MISSING_COLUMNS,
                    PRE_CHAT_AGENT_CONTEXT_MISSING_COLUMNS,
                    PRE_WORKSPACE_PREFERENCES_MISSING_COLUMNS,
                ),
            ):
                # The immediately preceding commercial schema has all governed
                # AgentRun columns but not the audit visibility columns.
                command.stamp(alembic_config, "20260725_02")
            else:
                legacy_tables = pre_knowledge_tables - {"agent_runs"}
                if _matches_schema(
                    inspector,
                    legacy_tables,
                    ignored_columns=_ignored_columns(
                        PRE_BUSINESS_MISSING_COLUMNS,
                        PRE_SUMMARY_MISSING_COLUMNS,
                        PRE_BATCH_MISSING_COLUMNS,
                        PRE_PERMISSION_MODE_MISSING_COLUMNS,
                        PRE_AGENT_MODE_MISSING_COLUMNS,
                        PRE_CHAT_AGENT_CONTEXT_MISSING_COLUMNS,
                        PRE_WORKSPACE_PREFERENCES_MISSING_COLUMNS,
                    ),
                ):
                    # The pre-Alembic product schema is known and complete. Stamp
                    # that immutable baseline, then apply additive revisions.
                    command.stamp(alembic_config, "20260725_00")
    # 半迁移感知的逐版升级：单版对象已存在时记录版本并继续
    start_after = _read_alembic_version()
    _upgrade_stepwise(alembic_config, start_after)
    _warn_on_schema_gap()


def _warn_on_schema_gap() -> None:
    """迁移跑完后核对一次模型列是否都在库里。

    版本号走到 head 不等于结构真的到位：自愈分支可能把某个版本记成已应用而
    实际没落库。缺列时应用能启动、但之后每个请求都 500 在一个毫无提示的
    "no such column" 上，所以这里把缺口直接点到列名。
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    missing: list[str] = []
    for table_name, table in SQLModel.metadata.tables.items():
        if table_name not in existing_tables:
            missing.append(f"{table_name}（整表缺失）")
            continue
        actual = {column["name"] for column in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name not in actual:
                missing.append(f"{table_name}.{column.name}")
    if missing:
        logging.getLogger(__name__).error(
            "数据库结构落后于模型，缺失对象：%s。版本号已到 head，请检查是否有迁移被"
            "跳过（残留 _alembic_tmp_* 临时表会让 batch_alter_table 误判为已应用）。",
            ", ".join(missing[:20]),
        )


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
