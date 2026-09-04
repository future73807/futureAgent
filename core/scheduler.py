"""基于 APScheduler 的工作区自动化任务调度。

- 数据库中的 ``ScheduledJob`` 是唯一事实来源；进程内 BackgroundScheduler
  只是把 enabled 的任务映射成 cron 触发器。
- 任务执行在 APScheduler 工作线程里开自己的 Session，与请求生命周期解耦。
- cron 解析失败在写入/API 层就被拒绝；执行层的异常全部记录到
  ``last_status/last_message``，绝不让调度线程死亡。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from api.notifications import dispatch_to_targets, push_notification
import db.database as database
from db.models import (
    BusinessAlert,
    ScheduledJob,
    Workspace,
    now_utc,
)
from db.report_models import ReportAlert

logger = logging.getLogger(__name__)

JOB_TYPES: dict[str, str] = {
    "business_daily_report": "经营日报（按公司已授权数据）",
    "report_daily": "汇报日报",
    "report_weekly": "汇报周报",
    "report_monthly": "汇报月报",
    "alert_scan": "预警扫描（未闭环预警推送通知）",
}

_scheduler: BackgroundScheduler | None = None


def validate_cron(expression: str) -> bool:
    try:
        CronTrigger.from_crontab(expression)
    except (ValueError, TypeError):
        return False
    return True


def _job_key(job_id: str) -> str:
    return f"scheduled_job:{job_id}"


def upsert_job_trigger(job: ScheduledJob) -> None:
    """把一行任务同步到进程内调度器；禁用或非法 cron 时移除旧触发器。"""
    if _scheduler is None:
        return
    key = _job_key(job.id)
    if _scheduler.get_job(key):
        _scheduler.remove_job(key)
    if not job.enabled or not validate_cron(job.cron):
        return
    _scheduler.add_job(
        execute_job_by_id,
        CronTrigger.from_crontab(job.cron),
        id=key,
        args=[job.id],
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )


def remove_job_trigger(job_id: str) -> None:
    if _scheduler is None:
        return
    key = _job_key(job_id)
    if _scheduler.get_job(key):
        _scheduler.remove_job(key)


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.start()
    with Session(database.engine) as session:
        for job in session.exec(select(ScheduledJob).where(ScheduledJob.enabled.is_(True))).all():
            try:
                upsert_job_trigger(job)
            except (ValueError, TypeError):
                logger.warning("scheduler: 任务 %s 的 cron 无效，已跳过", job.id)
    logger.info("scheduler: 已启动并同步工作区自动化任务")
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def execute_job_by_id(job_id: str) -> None:
    """APScheduler 线程入口：独立 Session 执行并回写运行状态。"""
    with Session(database.engine) as session:
        job = session.get(ScheduledJob, job_id)
        if job is None or not job.enabled:
            return
        status, message = execute_job(session, job)
        job.last_run_at = now_utc()
        job.last_status = status
        job.last_message = message[:500]
        job.updated_at = now_utc()
        session.add(job)
        session.commit()


def execute_job(session: Session, job: ScheduledJob) -> tuple[str, str]:
    """执行一次任务，返回 (status, message)。供调度线程与“立即执行”共用。"""
    try:
        if job.job_type == "business_daily_report":
            from api.business_routes import _generate_daily_report

            report = _generate_daily_report(
                session, workspace_id=job.workspace_id, report_date=date.today(), generated_by=job.created_by
            )
            session.commit()
            return "ok", f"经营日报已生成（{report.report_date}）"
        if job.job_type == "report_daily":
            from api.report_routes import _generate_daily_report

            report = _generate_daily_report(
                session, workspace_id=job.workspace_id, report_date=date.today(), generated_by=job.created_by
            )
            session.commit()
            return "ok", f"汇报日报已生成（{report.report_date}）"
        if job.job_type == "report_weekly":
            from api.report_routes import _generate_weekly_report

            week_start = date.today() - timedelta(days=date.today().weekday())
            report = _generate_weekly_report(
                session,
                workspace_id=job.workspace_id,
                week_start_date=week_start,
                week_end_date=week_start + timedelta(days=6),
                title=f"周报 {week_start.isoformat()}",
                generated_by=job.created_by,
            )
            session.commit()
            return "ok", f"汇报周报已生成（{report.week_start} ~ {report.week_end}）"
        if job.job_type == "report_monthly":
            from api.report_routes import _generate_monthly_report

            today = date.today()
            report = _generate_monthly_report(
                session,
                workspace_id=job.workspace_id,
                period_year=today.year,
                period_month=today.month,
                generated_by=job.created_by,
            )
            session.commit()
            return "ok", f"汇报月报已生成（{report.period_year}-{report.period_month:02d}）"
        if job.job_type == "alert_scan":
            return execute_alert_scan(session, job)
        return "failed", f"未知任务类型：{job.job_type}"
    except Exception as exc:  # noqa: BLE001 - 执行失败写回任务状态即可
        logger.warning("scheduler: 任务 %s 执行失败", job.id, exc_info=True)
        session.rollback()
        return "failed", f"执行失败：{exc}"


def execute_alert_scan(session: Session, job: ScheduledJob) -> tuple[str, str]:
    workspace = session.get(Workspace, job.workspace_id)
    if workspace is None:
        return "failed", "工作区不存在"
    since = job.last_run_at or now_utc() - timedelta(hours=24)
    open_alerts: list[Any] = [
        alert
        for alert in session.exec(
            select(BusinessAlert)
            .where(
                BusinessAlert.workspace_id == job.workspace_id,
                BusinessAlert.status == "open",
                BusinessAlert.created_at > since,
            )
        ).all()
    ]
    open_alerts.extend(
        session.exec(
            select(ReportAlert)
            .where(
                ReportAlert.workspace_id == job.workspace_id,
                ReportAlert.status == "open",
                ReportAlert.created_at > since,
            )
        ).all()
    )
    for alert in open_alerts[:20]:
        push_notification(
            session,
            job.workspace_id,
            workspace.owner_id,
            "alert",
            f"未闭环预警：{alert.title}",
            body=getattr(alert, "summary", "")[:200],
            link="report",
            ref_id=alert.id,
        )
    session.commit()
    summary = f"发现 {len(open_alerts)} 条未闭环预警" if open_alerts else "暂无新增未闭环预警"
    if open_alerts:
        dispatch_to_targets(
            session,
            job.workspace_id,
            f"futureAgent 预警扫描：{summary}",
            "；".join(alert.title for alert in open_alerts[:5]),
        )
    return "ok", summary


def _job_data(job: ScheduledJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "name": job.name,
        "job_type": job.job_type,
        "cron": job.cron,
        "enabled": job.enabled,
        "last_run_at": job.last_run_at,
        "last_status": job.last_status,
        "last_message": job.last_message,
        "created_at": job.created_at,
    }

