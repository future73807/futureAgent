"""把"定时执行智能体任务"做成智能体自己的能力。

用户在对话里说"每天早上九点把昨天的执行结果总结一下"，模型调用这里的工具把任务
落到工作区；到点由 ``core.scheduler`` 触发，执行结果落成一次真实对话并推送通知。
产品里没有单独的"定时任务管理页"：创建、查看、取消都在对话里完成。

设计边界：
- 任务永远属于**发起它的工作区与发起人**：workspace_id / created_by 来自执行上下文
  （引擎 config），不作为工具参数暴露，模型无法指定别人的工作区。
- 只读成员的工具集里不会出现这些工具（引擎按 Casbin RBAC 过滤，见
  ``auth/rbac_policy.csv`` 的 ``tool:*`` 只在 developer 上）。
- cron 按**服务器本地时区**解析；工具描述里带上当前时间，模型才能把"明天早上""每周
  一"这类相对说法换算成 cron。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from langchain_core.tools import StructuredTool
from sqlmodel import Session, select

import db.database as database
from core.scheduler import next_run_at, remove_job_trigger, upsert_job_trigger, validate_cron
from db.models import CustomAgent, ScheduledJob

logger = logging.getLogger(__name__)

SCHEDULING_TOOL_NAMES = frozenset(
    {"schedule_task", "list_scheduled_tasks", "cancel_scheduled_task"}
)

# 定时执行只允许这三种模式：goal/loop 需要目标或停止条件，无人值守下无法终止。
ALLOWED_MODES = ("chat", "agent", "plan")
# 单个工作区的定时任务上限：防止模型在对话里批量创建把调度器塞满。
MAX_JOBS_PER_WORKSPACE = 20
# 提示词上限与 ScheduledJob.prompt 的列长度一致。
PROMPT_MAX_CHARS = 4000


def _session() -> Session:
    return Session(database.engine)


def _write_audit(*args: Any, **kwargs: Any) -> None:
    """走与请求路径同一套审计写入（延迟导入避免 core → api 的导入期依赖）。"""
    from api.dependencies import write_audit

    write_audit(*args, **kwargs)


def _workspace_jobs(session: Session, workspace_id: str) -> list[ScheduledJob]:
    return list(
        session.exec(
            select(ScheduledJob)
            .where(ScheduledJob.workspace_id == workspace_id)
            .order_by(ScheduledJob.created_at.desc())
        ).all()
    )


def _describe(job: ScheduledJob) -> str:
    """一行人类可读的任务描述，同时把 id 给出去供取消使用。"""
    state = "启用" if job.enabled else "已停用"
    upcoming = next_run_at(job.id)
    next_text = (
        upcoming.astimezone().strftime("%Y-%m-%d %H:%M")
        if isinstance(upcoming, datetime)
        else "（未排期）"
    )
    last_text = f"，上次：{job.last_status or '未执行'}" + (
        f"（{job.last_message}）" if job.last_message else ""
    )
    return f"- {job.name}｜{job.cron}｜{state}｜下次：{next_text}{last_text}｜id={job.id}"


def create_scheduled_task(
    *,
    workspace_id: str,
    created_by: str,
    name: str,
    cron: str,
    prompt: str,
    mode: str = "agent",
    skill_name: str = "chatbot",
    model_id: str = "",
    agent_id: str | None = None,
) -> str:
    """创建一条定时任务；返回给模型复述的说明文本。"""
    if not workspace_id or not created_by:
        return "无法创建定时任务：当前执行缺少工作区或发起人身份。"
    title = (name or "").strip()[:120] or (prompt or "").strip()[:24] or "定时任务"
    expression = (cron or "").strip()
    if not validate_cron(expression):
        return (
            f"cron 表达式「{cron}」无效。需要标准 5 段格式（分 时 日 月 周），"
            "例如 0 9 * * * 表示每天 09:00，0 18 * * 1-5 表示工作日 18:00。"
        )
    body = (prompt or "").strip()
    if not body:
        return "无法创建定时任务：提示词为空，请先说明到点要执行什么。"
    if len(body) > PROMPT_MAX_CHARS:
        return f"提示词过长（{len(body)} 字符），上限 {PROMPT_MAX_CHARS} 字符。"
    resolved_mode = (mode or "agent").strip()
    if resolved_mode not in ALLOWED_MODES:
        return f"不支持的模式「{mode}」，只能是 chat / agent / plan 之一。"

    with _session() as session:
        if agent_id:
            preset = session.get(CustomAgent, agent_id)
            if preset is None or preset.workspace_id != workspace_id:
                return "指定的自建智能体不存在。"
            if not preset.enabled:
                return f"自建智能体「{preset.name}」已停用。"
        existing = _workspace_jobs(session, workspace_id)
        if len(existing) >= MAX_JOBS_PER_WORKSPACE:
            return (
                f"当前工作区的定时任务已达上限（{MAX_JOBS_PER_WORKSPACE} 条），"
                "请先取消不再需要的任务。"
            )
        duplicate = next(
            (job for job in existing if job.name == title and job.cron == expression and job.enabled),
            None,
        )
        if duplicate is not None:
            return f"已存在同名的启用任务「{title}」（{expression}），未重复创建。"
        job = ScheduledJob(
            workspace_id=workspace_id,
            name=title,
            job_type="agent_task",
            cron=expression,
            enabled=True,
            prompt=body,
            model_id=(model_id or "").strip()[:120],
            skill_name=(skill_name or "chatbot").strip()[:120] or "chatbot",
            mode=resolved_mode,
            agent_id=(agent_id or None),
            created_by=created_by,
        )
        session.add(job)
        session.flush()
        _write_audit(
            session,
            actor_id=created_by,
            workspace_id=workspace_id,
            action="automation_job.created",
            target_type="scheduled_job",
            target_id=job.id,
            metadata={"cron": job.cron, "mode": job.mode, "skill_name": job.skill_name},
        )
        session.commit()
        upsert_job_trigger(job)
        upcoming = next_run_at(job.id)
    when = upcoming.astimezone().strftime("%Y-%m-%d %H:%M") if isinstance(upcoming, datetime) else "按 cron 排期"
    return (
        f"已创建定时任务「{title}」（id={job.id}）：cron {expression}，模式 {resolved_mode}，"
        f"下次运行 {when}。到点会以一个新的对话产出结果并推送通知。"
    )


def list_scheduled_tasks(*, workspace_id: str) -> str:
    with _session() as session:
        jobs = _workspace_jobs(session, workspace_id)
    if not jobs:
        return "当前工作区还没有定时任务。"
    return "当前工作区的定时任务：\n" + "\n".join(_describe(job) for job in jobs)


def cancel_scheduled_task(*, workspace_id: str, task: str, delete: bool = False) -> str:
    """停用（默认）或删除一条定时任务；``task`` 可以是 id 或名称片段。"""
    keyword = (task or "").strip()
    if not keyword:
        return "请提供要取消的任务 id 或名称。"
    with _session() as session:
        jobs = _workspace_jobs(session, workspace_id)
        matched = [job for job in jobs if job.id == keyword]
        if not matched:
            lowered = keyword.lower()
            matched = [job for job in jobs if lowered in job.name.lower()]
        if not matched:
            return f"没有找到匹配「{task}」的定时任务。"
        if len(matched) > 1:
            listing = "；".join(f"{job.name}(id={job.id})" for job in matched)
            return f"「{task}」匹配到多条任务：{listing}。请用 id 指定要取消的那一条。"
        job = matched[0]
        if delete:
            session.delete(job)
            action, done = "automation_job.deleted", f"已删除定时任务「{job.name}」"
        else:
            job.enabled = False
            session.add(job)
            action, done = "automation_job.updated", f"已停用定时任务「{job.name}」（可再次要求恢复）"
        _write_audit(
            session,
            actor_id=None,
            workspace_id=workspace_id,
            action=action,
            target_type="scheduled_job",
            target_id=job.id,
        )
        session.commit()
        if delete or not job.enabled:
            remove_job_trigger(job.id)
    return done


def scheduling_tools(*, workspace_id: str, created_by: str) -> list[StructuredTool]:
    """引擎本地注入的定时任务工具集（与 dispatch_subagent 同机制）。

    workspace_id 与 created_by 在这里就被闭包绑死，**不会出现在工具签名里**：
    模型无法通过参数把任务塞进别的工作区，也无法伪造发起人。
    """

    def schedule_task(
        name: str,
        cron: str,
        prompt: str,
        mode: str = "agent",
        skill_name: str = "chatbot",
        model_id: str = "",
        agent_id: str | None = None,
    ) -> str:
        return create_scheduled_task(
            workspace_id=workspace_id,
            created_by=created_by,
            name=name,
            cron=cron,
            prompt=prompt,
            mode=mode,
            skill_name=skill_name,
            model_id=model_id,
            agent_id=agent_id,
        )

    def list_tasks() -> str:
        return list_scheduled_tasks(workspace_id=workspace_id)

    def cancel_task(task: str, delete: bool = False) -> str:
        return cancel_scheduled_task(workspace_id=workspace_id, task=task, delete=delete)

    now = datetime.now().astimezone()
    time_hint = now.strftime("%Y-%m-%d %H:%M")
    zone_hint = now.strftime("%Z") or "本地时区"
    return [
        StructuredTool.from_function(
            func=schedule_task,
            name="schedule_task",
            description=(
                "为用户创建一个定时任务：到点自动执行给定的提示词，结果落成一次对话并推送通知。"
                f"当前服务器时间是 {time_hint}（{zone_hint}），cron 按同一时区解析。"
                "cron 用标准 5 段格式：0 9 * * * 表示每天 09:00，0 18 * * 1-5 表示工作日 18:00，"
                "30 8 1 * * 表示每月 1 日 08:30。"
                "提示词必须是自包含的完整指令——到点执行时没有当前对话的上下文，"
                "所以要把「看情况总结一下」写成具体做什么、按什么口径、输出成什么样子。"
                "mode 默认 agent（可调用工具与联网检索），只要文本产出用 chat。"
                "创建前先与用户确认时间与内容；创建后把下次运行时间复述给用户。"
            ),
        ),
        StructuredTool.from_function(
            func=list_tasks,
            name="list_scheduled_tasks",
            description="列出当前工作区的定时任务：名称、cron、启用状态、下次运行时间与任务 id。",
        ),
        StructuredTool.from_function(
            func=cancel_task,
            name="cancel_scheduled_task",
            description=(
                "停用或删除一条定时任务。task 传任务 id 或名称片段；默认只停用（可恢复），"
                "只有用户明确说要删除时才传 delete=true。"
            ),
        ),
    ]
