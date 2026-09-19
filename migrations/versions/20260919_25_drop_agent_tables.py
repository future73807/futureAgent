"""Drop the reporting/business agent and automation tables.

产品收敛为单一智能体：汇报智能体（数据源 / 记录 / 预警 / 日报周报月报 /
汇报助手消息）与经营智能体（三类助手 / 老板任务 / 经营数据）整体移除，
自动化调度也一并去掉——它当时的全部任务类型都是"生成这些报告"或"扫描这些
预警"，没有这两块功能就再没有可执行的任务类型。

知识库表（knowledge_bases / knowledge_chunks）**保留**：检索能力(RAG)
继续作为智能体的知识来源，只是不再依附于被删掉的汇报模块。

Revision ID: 20260919_25
Revises: 20260915_24
Create Date: 2026-09-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260919_25"
down_revision = "20260915_24"
branch_labels = None
depends_on = None

# 子表在前、父表在后：有外键的库（Postgres）会拒绝先删被引用的表。
LEGACY_TABLES = (
    "business_assistant_messages",
    "business_boss_tasks",
    "business_records",
    "business_alerts",
    "business_alert_rules",
    "business_data_sources",
    "business_assistants",
    "business_daily_reports",
    "report_assistant_messages",
    "report_records",
    "report_alerts",
    "report_alert_rules",
    "report_data_sources",
    "report_assistants",
    "report_daily_reports",
    "report_weekly_reports",
    "report_monthly_reports",
    "scheduled_jobs",
)


def upgrade() -> None:
    # 逐表存在性判断而不是无条件 DROP：无版本旧库可能被判定在链中间某版，
    # 自愈式升级（_upgrade_stepwise）不会容忍 "no such table"。
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in LEGACY_TABLES:
        if table in existing:
            op.execute(sa.text(f'DROP TABLE "{table}"'))


def downgrade() -> None:
    """不回建：这些表属于已从产品中移除的功能，且其中的数据只服务于它们。

    需要回到旧版行为时，从版本历史取出当时的代码与迁移链，用重建的数据库
    运行——在现有库上原地恢复表结构而没有会写这些表的代码，只会留下一堆
    无人维护的孤儿表。
    """
    raise NotImplementedError(
        "已删除的汇报/经营智能体表不再重建；请从版本历史恢复代码后重建数据库"
    )
