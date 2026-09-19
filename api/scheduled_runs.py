"""定时任务的执行体：把一次"到点执行"变成一次真实对话。

调度线程不经过请求生命周期，所以这里自己做四件事：
1. **先校验再花钱**：模型、技能、自建智能体、发起人身份都在调用模型之前检查，
   任何一项不成立就带着可读原因失败，不产生半次调用。
2. **以最严档运行**：无人值守的任务用 ``default`` 权限档（不自动批准、不自动
   完成步骤），需要人工决策的动作会留在工作模式里等人处理。
3. **产出可读**：用户消息=任务提示词，助手消息=模型回答，两者落进一个新对话；
   通知指回这个对话，点开就能看到这次定时执行到底做了什么。
4. **失败可解释**：失败原因写进任务状态、对话与审计；通知只在"由好变坏"时发一次，
   避免上游模型长时间不可用把通知中心刷满。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date

from sqlmodel import Session, select

from api.dependencies import write_audit
from api.notifications import push_notification
from config import settings
from core.assistant_ai import render_knowledge_context
from core.knowledge_retrieval import retrieve_knowledge_smart, workspace_has_knowledge
from core.model_hub import ModelHub
from db.models import ChatMessage, Conversation, CustomAgent, Membership, ScheduledJob, Workspace, now_utc

logger = logging.getLogger(__name__)

# 与对话页一致：注入提示词的知识库片段条数。
KNOWLEDGE_CONTEXT_LIMIT = 4
# 助手消息上限，与 ChatMessage.content 的列长度一致。
REPLY_MAX_CHARS = 16_000


class ScheduledRunError(RuntimeError):
    """能被直接展示给用户的失败原因。"""


def _serialize_tool_trace(events: list) -> str:
    """只保留稳定且有界的字段，与对话路径一致。"""
    bounded: list[dict[str, str]] = []
    for event in events[:64]:
        if not isinstance(event, dict):
            continue
        bounded.append(
            {
                "name": str(event.get("name") or "tool")[:120],
                "tool_call_id": str(event.get("tool_call_id") or "")[:200],
                "status": str(event.get("status") or "success")[:32],
                "result_preview": str(event.get("result_preview") or "")[:2_000],
            }
        )
    return json.dumps(bounded, ensure_ascii=False)


def _creator_role(session: Session, job: ScheduledJob) -> str:
    """发起人当前的工作区角色 → 引擎使用的 Casbin 角色。

    任务不继承任何"历史权限"：发起人退出工作区后，这个任务就不该再用他的名义
    去执行——否则一次离职会留下一个仍在工作区里活动的执行者。

    映射规则与请求路径 ``api/routes._effective_role`` 完全一致：只读成员用受限的
    ``user``，其余（含工作区所有者）都是 ``developer``，``admin`` 由策略继承。
    传产品角色名（owner/member）会让权限层直接 403——它只认 Casbin 角色。
    """
    membership = session.exec(
        select(Membership).where(
            Membership.workspace_id == job.workspace_id,
            Membership.user_id == job.created_by,
        )
    ).first()
    if membership is None:
        raise ScheduledRunError("任务发起人已不在该工作区，已跳过本次执行")
    return "user" if membership.role == "viewer" else "developer"


def _resolve_target(session: Session, job: ScheduledJob, engine) -> tuple[str, str, str]:
    """校验模型/技能/自建智能体，返回 (model_id, skill_name, persona)。"""
    model_id = (job.model_id or "").strip() or settings.default_model
    skill_name = (job.skill_name or "").strip() or "chatbot"
    if not (job.prompt or "").strip():
        raise ScheduledRunError("任务提示词为空")
    if not engine.skill_manager.get_skill(skill_name):
        raise ScheduledRunError(f"技能“{skill_name}”不存在")
    readiness_error = ModelHub.readiness_error(model_id)
    if readiness_error:
        raise ScheduledRunError(f"模型不可用：{readiness_error}")
    persona = ""
    if job.agent_id:
        preset = session.get(CustomAgent, job.agent_id)
        if preset is None or preset.workspace_id != job.workspace_id:
            raise ScheduledRunError("指定的自建智能体不存在")
        if not preset.enabled:
            raise ScheduledRunError(f"自建智能体“{preset.name}”已停用")
        persona = preset.persona
    return model_id, skill_name, persona


def _mcp_servers(job: ScheduledJob) -> list[str]:
    try:
        parsed = json.loads(job.mcp_servers_json or "[]")
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item)[:80] for item in parsed][:20]


async def _execute(session: Session, job: ScheduledJob, workspace: Workspace) -> tuple[str, str]:
    from api.routes import (  # 延迟导入：api.routes 是重模块，且只在真正执行时才需要
        _persist_usage,
        _stamp_message_agent_context,
        _workspace_run_context,
        get_agent_engine,
    )

    engine = get_agent_engine()
    model_id, skill_name, persona = _resolve_target(session, job, engine)
    user_role = _creator_role(session, job)

    conversation = Conversation(
        workspace_id=job.workspace_id,
        owner_id=job.created_by,
        title=f"{job.name} · {date.today().isoformat()}",
        model_id=model_id,
        skill_name=skill_name,
    )
    session.add(conversation)
    session.flush()
    user_message = ChatMessage(conversation_id=conversation.id, role="user", content=job.prompt)
    assistant_message = ChatMessage(conversation_id=conversation.id, role="assistant", content="")
    session.add(user_message)
    session.add(assistant_message)
    session.commit()

    # 与对话页同样的知识库召回：工作区没建知识库时完全跳过，不多付一次 embedding。
    knowledge_context = ""
    if workspace_has_knowledge(session, job.workspace_id):
        retrieved = await retrieve_knowledge_smart(
            session, job.workspace_id, job.prompt, limit=KNOWLEDGE_CONTEXT_LIMIT
        )
        knowledge_context = render_knowledge_context(retrieved)

    config = {
        "model_id": model_id,
        "skill_name": skill_name,
        "mcp_servers": _mcp_servers(job),
        "workspace_id": job.workspace_id,
        # 定时执行里"发起人"就是任务创建者：他若已离开工作区，前面已经拦下。
        "user_id": job.created_by,
        "thread_id": conversation.id,
        "tool_trace": [],
        "usage_by_message": {},
        # 无人值守：固定用最严档，不接受任务里配置更宽的权限。
        "permission_mode": "default",
        "agent_persona": persona,
        "knowledge_context": knowledge_context,
        "mode": job.mode or "chat",
        "goal": "",
        "success_criteria": "",
        # 定时执行不跑 goal/loop 那种多轮监督：无人值守时"多轮自我评价"既慢又难审计。
        "max_iterations": 1,
        "iterations": [],
        **_workspace_run_context(workspace),
    }
    started_at = now_utc()
    collected: list[str] = []

    def _close_failed_run(reason: str) -> None:
        """把失败写进这次执行自己开的对话，并记一次失败用量。

        对话仍然保留：点开通知或任务列表里的"最近对话"就能看到发了什么提示词、
        失败在哪里，比只剩一行状态码有用得多。
        """
        assistant_message.content = f"⚠️ 本次定时执行失败：{reason}"[:REPLY_MAX_CHARS]
        job.last_conversation_id = conversation.id
        conversation.updated_at = now_utc()
        session.add(assistant_message)
        session.add(conversation)
        _persist_usage(
            session,
            workspace_id=job.workspace_id,
            user_id=job.created_by,
            model_id=model_id,
            skill_name=skill_name,
            source="scheduled_job",
            source_id=job.id,
            agent_mode=config["mode"],
            config=config,
            status="failed",
            started_at=started_at,
        )
        session.commit()

    try:
        async with asyncio.timeout(max(1, settings.agent_run_timeout_seconds)):
            async for chunk in engine.run(user_role=user_role, query=job.prompt, config=config):
                collected.append(chunk)
    except Exception as exc:  # noqa: BLE001 - 失败要继续走落库/审计/通知
        session.rollback()
        _close_failed_run(f"模型调用失败：{exc}")
        raise ScheduledRunError(f"模型调用失败：{exc}") from exc

    reply = "".join(collected).strip()
    if not reply:
        _close_failed_run("模型没有返回任何内容")
        raise ScheduledRunError("模型没有返回任何内容")

    assistant_message.content = reply[:REPLY_MAX_CHARS]
    assistant_message.tool_trace_json = _serialize_tool_trace(config["tool_trace"])
    _stamp_message_agent_context(assistant_message, config, config["mode"])
    conversation.updated_at = now_utc()
    job.last_conversation_id = conversation.id
    session.add(assistant_message)
    session.add(conversation)
    _persist_usage(
        session,
        workspace_id=job.workspace_id,
        user_id=job.created_by,
        model_id=model_id,
        skill_name=skill_name,
        source="scheduled_job",
        source_id=job.id,
        agent_mode=config["mode"],
        config=config,
        status="succeeded",
        started_at=started_at,
    )
    write_audit(
        session,
        actor_id=None,  # 系统触发：不给任何人为这次执行背书
        workspace_id=job.workspace_id,
        action="automation_job.executed",
        target_type="scheduled_job",
        target_id=job.id,
        metadata={
            "conversation_id": conversation.id,
            "model_id": model_id,
            "skill_name": skill_name,
            "mode": config["mode"],
        },
    )
    push_notification(
        session,
        job.workspace_id,
        job.created_by,
        "run",
        f"定时任务已完成：{job.name}",
        body=reply[:200],
        link="chat",
        ref_id=conversation.id,
    )
    session.commit()
    return "ok", f"已生成对话「{conversation.title}」"


def _record_failure(session: Session, job: ScheduledJob, reason: str) -> tuple[str, str]:
    """失败落库：写状态、审计，并只在状态由好变坏时通知一次。"""
    text = reason[:500]
    if job.last_status != "failed":
        push_notification(
            session,
            job.workspace_id,
            job.created_by,
            "run",
            f"定时任务执行失败：{job.name}",
            body=text,
            link="automation",
            ref_id=job.id,
        )
    write_audit(
        session,
        actor_id=None,
        workspace_id=job.workspace_id,
        action="automation_job.executed",
        target_type="scheduled_job",
        target_id=job.id,
        metadata={"status": "failed", "reason": text[:200]},
    )
    session.commit()
    return "failed", text


def run_scheduled_agent_job(session: Session, job: ScheduledJob) -> tuple[str, str]:
    """同步入口（供调度线程与"立即执行"共用），返回 (status, message)。"""
    workspace = session.get(Workspace, job.workspace_id)
    if workspace is None:
        return "failed", "工作区不存在"
    try:
        return asyncio.run(_execute(session, job, workspace))
    except ScheduledRunError as exc:
        logger.info("scheduled job %s failed: %s", job.id, exc)
        session.rollback()
        return _record_failure(session, job, str(exc))
    except Exception as exc:  # noqa: BLE001 - 兜底：任何异常都要变成可读状态
        logger.warning("scheduled job %s crashed", job.id, exc_info=True)
        session.rollback()
        return _record_failure(session, job, f"执行失败：{exc}")
