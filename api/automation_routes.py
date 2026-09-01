"""工作区自动化任务（定时调度）API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from api.dependencies import WorkspaceContext, get_workspace_context, require_workspace_role, write_audit
from core.scheduler import JOB_TYPES, execute_job, remove_job_trigger, upsert_job_trigger, validate_cron
from db.database import get_session
from db.models import ScheduledJob, now_utc

router = APIRouter()


class ScheduledJobRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    job_type: str = Field(max_length=32)
    cron: str = Field(min_length=9, max_length=64)
    enabled: bool = True


class ScheduledJobPatchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    cron: str | None = Field(default=None, min_length=9, max_length=64)
    enabled: bool | None = None


def _require_manager(context: WorkspaceContext) -> None:
    require_workspace_role(context, "owner", "admin")


def _job_or_404(session: Session, context: WorkspaceContext, job_id: str) -> ScheduledJob:
    job = session.get(ScheduledJob, job_id)
    if job is None or job.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="自动化任务不存在")
    return job


@router.get("/v1/automation/job-types")
def list_job_types() -> dict[str, Any]:
    return {"job_types": [{"value": key, "label": label} for key, label in JOB_TYPES.items()]}


@router.get("/v1/automation/jobs")
def list_scheduled_jobs(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_manager(context)
    jobs = session.exec(
        select(ScheduledJob)
        .where(ScheduledJob.workspace_id == context.workspace.id)
        .order_by(ScheduledJob.created_at.desc())
    ).all()
    return {"jobs": [{**_job_payload(job)} for job in jobs]}


def _job_payload(job: ScheduledJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "name": job.name,
        "job_type": job.job_type,
        "job_type_label": JOB_TYPES.get(job.job_type, job.job_type),
        "cron": job.cron,
        "enabled": job.enabled,
        "last_run_at": job.last_run_at,
        "last_status": job.last_status,
        "last_message": job.last_message,
        "created_at": job.created_at,
    }


@router.post("/v1/automation/jobs", status_code=status.HTTP_201_CREATED)
def create_scheduled_job(
    request: ScheduledJobRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_manager(context)
    if request.job_type not in JOB_TYPES:
        raise HTTPException(status_code=422, detail="不支持的任务类型")
    if not validate_cron(request.cron):
        raise HTTPException(status_code=422, detail="cron 表达式无效，需要标准 5 段格式")
    job = ScheduledJob(
        workspace_id=context.workspace.id,
        name=request.name,
        job_type=request.job_type,
        cron=request.cron,
        enabled=request.enabled,
        created_by=context.user.id,
    )
    session.add(job)
    session.flush()
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="automation_job.created",
        target_type="scheduled_job",
        target_id=job.id,
        metadata={"job_type": job.job_type, "cron": job.cron},
    )
    session.commit()
    upsert_job_trigger(job)
    return {"job": _job_payload(job)}


@router.patch("/v1/automation/jobs/{job_id}")
def update_scheduled_job(
    job_id: str,
    request: ScheduledJobPatchRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_manager(context)
    job = _job_or_404(session, context, job_id)
    if request.name is not None:
        job.name = request.name
    if request.cron is not None:
        if not validate_cron(request.cron):
            raise HTTPException(status_code=422, detail="cron 表达式无效，需要标准 5 段格式")
        job.cron = request.cron
    if request.enabled is not None:
        job.enabled = request.enabled
    job.updated_at = now_utc()
    session.add(job)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="automation_job.updated",
        target_type="scheduled_job",
        target_id=job.id,
        metadata={"enabled": job.enabled, "cron": job.cron},
    )
    session.commit()
    upsert_job_trigger(job)
    return {"job": _job_payload(job)}


@router.delete("/v1/automation/jobs/{job_id}")
def delete_scheduled_job(
    job_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_manager(context)
    job = _job_or_404(session, context, job_id)
    session.delete(job)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="automation_job.deleted",
        target_type="scheduled_job",
        target_id=job_id,
    )
    session.commit()
    remove_job_trigger(job_id)
    return {"deleted": job_id}


@router.post("/v1/automation/jobs/{job_id}/run")
def run_scheduled_job_now(
    job_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_manager(context)
    job = _job_or_404(session, context, job_id)
    job_status, message = execute_job(session, job)
    job.last_run_at = now_utc()
    job.last_status = job_status
    job.last_message = message[:500]
    job.updated_at = now_utc()
    session.add(job)
    write_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="automation_job.executed",
        target_type="scheduled_job",
        target_id=job.id,
        metadata={"status": job_status, "message": message[:200]},
    )
    session.commit()
    return {"status": job_status, "message": message, "job": _job_payload(job)}
