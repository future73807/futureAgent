"""基于 APScheduler 的工作区定时任务调度。

- 数据库中的 ``ScheduledJob`` 是唯一事实来源；进程内 BackgroundScheduler 只是把
  enabled 的任务映射成 cron 触发器，重启后由 ``start_scheduler`` 重新装载。
- 任务执行在 APScheduler 工作线程里开自己的 Session，与请求生命周期解耦。
- cron 解析失败在写入/API 层就被拒绝；执行层的异常全部记录到
  ``last_status/last_message``，绝不让调度线程死亡。

任务类型只有一种：``agent_task`` —— 到点让智能体跑一次提示词，结果落成一次对话。
cron 按**服务器本地时区**解析（Docker 里通常是 UTC），界面会把下次运行时间直接
显示出来，不让人靠猜时区。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

import db.database as database
from db.models import ScheduledJob, now_utc

logger = logging.getLogger(__name__)

JOB_TYPES: dict[str, str] = {
    "agent_task": "定时执行智能体任务",
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


def next_run_at(job_id: str):
    """该任务的下次触发时间；未启用、cron 非法或调度器未启动时返回 None。"""
    if _scheduler is None:
        return None
    scheduled = _scheduler.get_job(_job_key(job_id))
    return getattr(scheduled, "next_run_time", None) if scheduled else None


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler()
    _scheduler.start()
    with Session(database.engine) as session:
        for job in session.exec(select(ScheduledJob).where(ScheduledJob.enabled.is_(True))).all():
            try:
                upsert_job_trigger(job)
            except (ValueError, TypeError):
                logger.warning("scheduler: 任务 %s 的 cron 无效，已跳过", job.id)
    logger.info("scheduler: 已启动并同步工作区定时任务")
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
    """执行一次任务，返回 (status, message)。供调度线程与"立即执行"共用。"""
    try:
        if job.job_type == "agent_task":
            from api.scheduled_runs import run_scheduled_agent_job

            return run_scheduled_agent_job(session, job)
        return "failed", f"未知任务类型：{job.job_type}"
    except Exception as exc:  # noqa: BLE001 - 执行失败写回任务状态即可
        logger.warning("scheduler: 任务 %s 执行失败", job.id, exc_info=True)
        session.rollback()
        return "failed", f"执行失败：{exc}"
