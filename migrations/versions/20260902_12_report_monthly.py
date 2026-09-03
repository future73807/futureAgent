"""Monthly report table.

Revision ID: 20260902_12
Revises: 20260902_11
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_12"
down_revision = "20260902_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_monthly_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False, index=True),
        sa.Column("period_year", sa.Integer(), nullable=False, index=True),
        sa.Column("period_month", sa.Integer(), nullable=False, index=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.String(length=12000), nullable=False),
        sa.Column("metrics_json", sa.String(length=12000), nullable=False),
        sa.Column("generated_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "period_year", "period_month", name="uq_report_monthly_reports_workspace_period"),
    )


def downgrade() -> None:
    op.drop_table("report_monthly_reports")
