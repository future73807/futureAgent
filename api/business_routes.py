"""Workspace-scoped operating-agent APIs.

This module deliberately does not scrape WeChat, bypass an account login, or
call an unverified upstream model.  It accepts records only through an
explicitly authorised API/webhook token or an authenticated file-import path,
then produces deterministic summaries, keyword alerts and date reports.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections import Counter
from datetime import date, datetime, time, timezone
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from api.dependencies import WorkspaceContext, get_workspace_context, write_audit
from db.database import get_session
from db.models import (
    BusinessAlert,
    BusinessAlertRule,
    BusinessAssistant,
    BusinessAssistantMessage,
    BusinessBossTask,
    BusinessDailyReport,
    BusinessDataSource,
    BusinessRecord,
    Membership,
    Workspace,
    new_id,
    now_utc,
)


router = APIRouter(tags=["经营智能体"])

ASSISTANT_TYPES = {"boss_private", "personal_private", "company_public"}
DATA_SCOPES = {"company", "boss_private", "personal_private"}
SOURCE_TYPES = {
    "api",
    "webhook",
    "file_import",
    "oa",
    "mini_program",
    "production_report",
    "enterprise_robot",
    "custom_api",
}
CONNECTION_MODE_ALIASES = {
    "api": "api",
    "webhook": "webhook",
    "file_import": "file_import",
    "export": "file_import",
    "middleware": "webhook",
    "robot": "webhook",
}
ALERT_LEVELS = {"low", "medium", "high", "critical"}
ALERT_STATUSES = {"open", "acknowledged", "resolved"}
TASK_STATUSES = {"todo", "in_progress", "blocked", "done", "cancelled"}
TASK_PRIORITIES = {"low", "medium", "high", "urgent"}


class BusinessRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class AssistantCreateRequest(BusinessRequest):
    agent_type: Literal["boss_private", "personal_private", "company_public"]
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=2000)


class AssistantUpdateRequest(BusinessRequest):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None


class AssistantChatRequest(BusinessRequest):
    # ``query`` is retained as a narrow compatibility alias for API clients;
    # the product UI sends ``message``.
    message: str | None = Field(default=None, min_length=1, max_length=16000)
    query: str | None = Field(default=None, min_length=1, max_length=16000)


class DataSourceCreateRequest(BusinessRequest):
    name: str = Field(min_length=2, max_length=160)
    source_type: str = Field(min_length=2, max_length=32)
    connection_mode: str = Field(default="api", min_length=2, max_length=32)
    # Human-readable grant/reference, such as "只读生产日报与异常字段".
    # It is not a token, password or API key.
    access_scope: str = Field(default="", max_length=240)
    authorization_reference: str = Field(default="", max_length=240)
    data_scope: Literal["company", "boss_private", "personal_private"] = "company"
    endpoint_url: str = Field(default="", max_length=1000)


class DataSourceUpdateRequest(BusinessRequest):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    access_scope: str | None = Field(default=None, max_length=240)
    authorization_reference: str | None = Field(default=None, max_length=240)
    endpoint_url: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = None


class BusinessRecordInput(BusinessRequest):
    external_id: str = Field(min_length=1, max_length=160)
    record_type: str = Field(default="general", min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=16000)
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_on: date = Field(default_factory=date.today)
    occurred_at: datetime | None = None

    @field_validator("payload")
    @classmethod
    def payload_must_fit_persistent_limit(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            serialised = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("payload 必须是可序列化的 JSON 对象") from exc
        if len(serialised) > 50000:
            raise ValueError("payload 不能超过 50000 个字符")
        return value


class BusinessRecordBatchRequest(BusinessRequest):
    records: list[BusinessRecordInput] = Field(min_length=1, max_length=100)


class AlertRuleCreateRequest(BusinessRequest):
    name: str = Field(min_length=2, max_length=160)
    record_type: str = Field(default="", max_length=64)
    keywords: list[str] = Field(min_length=1, max_length=30)
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    data_scope: Literal["company", "boss_private", "personal_private"] = "company"


class AlertRuleUpdateRequest(BusinessRequest):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    record_type: str | None = Field(default=None, max_length=64)
    keywords: list[str] | None = Field(default=None, min_length=1, max_length=30)
    severity: Literal["low", "medium", "high", "critical"] | None = None
    enabled: bool | None = None


class ManualAlertCreateRequest(BusinessRequest):
    title: str = Field(min_length=2, max_length=240)
    summary: str = Field(default="", max_length=4000)
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    source_id: str | None = Field(default=None, max_length=64)
    record_id: str | None = Field(default=None, max_length=64)
    data_scope: Literal["company", "boss_private", "personal_private"] = "company"


class DailyReportGenerateRequest(BusinessRequest):
    report_date: date = Field(default_factory=date.today)


class BossTaskCreateRequest(BusinessRequest):
    title: str = Field(min_length=2, max_length=240)
    description: str = Field(default="", max_length=8000)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    due_date: date | None = None
    assignee_id: str | None = Field(default=None, max_length=64)
    alert_id: str | None = Field(default=None, max_length=64)


class BossTaskUpdateRequest(BusinessRequest):
    title: str | None = Field(default=None, min_length=2, max_length=240)
    description: str | None = Field(default=None, max_length=8000)
    priority: Literal["low", "medium", "high", "urgent"] | None = None
    due_date: date | None = None
    assignee_id: str | None = Field(default=None, max_length=64)
    status: Literal["todo", "in_progress", "blocked", "done", "cancelled"] | None = None
    progress_note: str | None = Field(default=None, max_length=4000)


def _require_member_write(context: WorkspaceContext) -> None:
    """Require an actual workspace membership; platform-admin is not a bypass."""
    if context.membership.role == "viewer":
        raise HTTPException(status_code=403, detail="只读成员不能执行此操作")


def _require_workspace_manager(context: WorkspaceContext) -> None:
    """Managers must really be owner/admin in this workspace, not only global admins."""
    if context.membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="需要当前工作区的管理权限")


def _is_workspace_boss(context: WorkspaceContext) -> bool:
    return (
        context.membership.role == "owner"
        and context.user.id == context.workspace.owner_id
    )


def _require_workspace_boss(context: WorkspaceContext) -> None:
    if not _is_workspace_boss(context):
        raise HTTPException(status_code=403, detail="仅当前工作区所有者可以执行此操作")


def _can_read_scope(
    context: WorkspaceContext,
    data_scope: str,
    owner_user_id: str | None,
) -> bool:
    """Private business data never inherits ``is_platform_admin`` access."""
    if data_scope == "company":
        return True
    if data_scope == "boss_private":
        return _is_workspace_boss(context) and owner_user_id == context.user.id
    return data_scope == "personal_private" and owner_user_id == context.user.id


def _require_scope_manager(
    context: WorkspaceContext,
    data_scope: str,
    owner_user_id: str | None,
) -> None:
    if data_scope == "company":
        _require_workspace_manager(context)
        return
    if not _can_read_scope(context, data_scope, owner_user_id):
        raise HTTPException(status_code=403, detail="无权管理该私有数据范围")


def _scope_owner_for_create(context: WorkspaceContext, data_scope: str) -> str | None:
    if data_scope == "company":
        _require_workspace_manager(context)
        return None
    # This MVP's private assistants are intentionally a boss-only product
    # space.  Do not let an admin create a private boss channel for someone
    # else, and do not let a platform admin bypass it.
    _require_workspace_boss(context)
    return context.user.id


def _assistant_subject(agent_type: str, owner_user_id: str | None) -> str:
    if agent_type == "company_public":
        return "company"
    if not owner_user_id:
        raise HTTPException(status_code=422, detail="私有助手必须绑定创建者")
    return f"user:{owner_user_id}"


def _assistant_or_404(
    session: Session,
    context: WorkspaceContext,
    assistant_id: str,
) -> BusinessAssistant:
    assistant = session.get(BusinessAssistant, assistant_id)
    if not assistant or assistant.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="经营助手不存在")
    if assistant.agent_type not in ASSISTANT_TYPES:
        # A corrupted/legacy row must never become a permissive assistant.
        raise HTTPException(status_code=404, detail="经营助手不存在")
    if assistant.agent_type == "company_public":
        if assistant.owner_user_id is not None or assistant.scope_subject_id != "company":
            raise HTTPException(status_code=409, detail="公司助手配置不合法，请由管理员修复")
        return assistant
    if (
        assistant.owner_user_id != context.user.id
        or assistant.scope_subject_id != _assistant_subject(assistant.agent_type, context.user.id)
    ):
        raise HTTPException(status_code=404, detail="经营助手不存在")
    if assistant.agent_type in {"boss_private", "personal_private"} and not _is_workspace_boss(context):
        raise HTTPException(status_code=404, detail="经营助手不存在")
    return assistant


def _source_or_404(session: Session, workspace_id: str, source_id: str) -> BusinessDataSource:
    source = session.get(BusinessDataSource, source_id)
    if not source or source.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="业务数据源不存在")
    if source.data_scope not in DATA_SCOPES:
        raise HTTPException(status_code=409, detail="业务数据源范围配置不合法")
    return source


def _record_or_404(session: Session, workspace_id: str, record_id: str) -> BusinessRecord:
    record = session.get(BusinessRecord, record_id)
    if not record or record.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="业务记录不存在")
    source = _source_or_404(session, workspace_id, record.source_id)
    if source.data_scope != record.data_scope or source.owner_user_id != record.owner_user_id:
        raise HTTPException(status_code=409, detail="业务记录与数据源范围不一致")
    return record


def _alert_or_404(session: Session, workspace_id: str, alert_id: str) -> BusinessAlert:
    alert = session.get(BusinessAlert, alert_id)
    if not alert or alert.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="预警不存在")
    return alert


def _rule_or_404(session: Session, workspace_id: str, rule_id: str) -> BusinessAlertRule:
    rule = session.get(BusinessAlertRule, rule_id)
    if not rule or rule.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="预警规则不存在")
    return rule


def _task_or_404(session: Session, workspace_id: str, task_id: str) -> BusinessBossTask:
    task = session.get(BusinessBossTask, task_id)
    if not task or task.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="老板任务不存在")
    return task


def _member_or_422(session: Session, workspace_id: str, user_id: str | None) -> None:
    if not user_id:
        return
    member = session.exec(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user_id,
        )
    ).first()
    if not member:
        raise HTTPException(status_code=422, detail="任务负责人必须是当前工作区成员")


def _safe_endpoint_url(value: str) -> str:
    """Keep only a non-credential HTTP(S) endpoint metadata URL.

    This product never makes an outbound request to the saved URL.  Rejecting
    userinfo, query strings and fragments prevents accidental storage of a
    token in a configuration field.
    """
    value = value.strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="接口地址必须是完整的 HTTP 或 HTTPS 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(status_code=422, detail="接口地址不得包含账号、密钥、查询参数或片段")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


def _safe_authorization_reference(value: str) -> str:
    value = value.strip()
    lowered = value.lower()
    forbidden_markers = (
        "api_key",
        "apikey",
        "secret",
        "password",
        "token",
        "bearer",
        "authorization",
        "credential",
        "sk-",
        "密钥",
        "密码",
        "令牌",
        "凭据",
    )
    if any(marker in lowered for marker in forbidden_markers):
        raise HTTPException(status_code=422, detail="授权说明只能保存工单或最小权限范围，不能填写密钥")
    return value


def _normalise_source_type(value: str) -> str:
    source_type = value.strip().lower()
    if source_type not in SOURCE_TYPES:
        raise HTTPException(status_code=422, detail="不支持的数据源类型")
    return source_type


def _normalise_connection_mode(value: str) -> str:
    mode = CONNECTION_MODE_ALIASES.get(value.strip().lower())
    if not mode:
        raise HTTPException(status_code=422, detail="不支持的接入方式")
    return mode


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_ingest_token() -> str:
    return secrets.token_urlsafe(32)


def _validate_ingest_token(source: BusinessDataSource, supplied: str | None) -> None:
    if not supplied or not source.ingest_token_hash:
        raise HTTPException(status_code=401, detail="业务数据接入凭据无效")
    if not secrets.compare_digest(source.ingest_token_hash, _token_hash(supplied)):
        raise HTTPException(status_code=401, detail="业务数据接入凭据无效")


def _json_load_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []


def _json_load_dict(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _serialise_payload(payload: dict[str, Any]) -> str:
    try:
        serialised = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="业务记录 payload 必须是可序列化的 JSON 对象") from exc
    if len(serialised) > 50000:
        raise HTTPException(status_code=422, detail="业务记录 payload 不能超过 50000 个字符")
    return serialised


def _assistant_data(assistant: BusinessAssistant) -> dict[str, Any]:
    return {
        "id": assistant.id,
        "assistant_type": assistant.agent_type,
        "type": assistant.agent_type,
        "name": assistant.name,
        "description": assistant.description,
        "enabled": assistant.enabled,
        "status": "active" if assistant.enabled else "disabled",
        "created_at": assistant.created_at,
        "updated_at": assistant.updated_at,
    }


def _source_data(
    source: BusinessDataSource,
    *,
    record_count: int = 0,
    last_sync_at: datetime | None = None,
) -> dict[str, Any]:
    source_status = "disabled" if not source.enabled else ("active" if record_count else "pending")
    return {
        "id": source.id,
        "name": source.name,
        "source_type": source.source_type,
        "connection_mode": source.connection_mode,
        # Configuration metadata can contain internal hostnames or approval
        # references.  List responses deliberately expose only completion
        # state, never endpoint or authorisation text (and never token hashes).
        "endpoint_configured": bool(source.endpoint_url),
        "authorization_configured": bool(source.authorization_reference),
        "access_scope": "已登记最小权限范围" if source.authorization_reference else "待补充授权范围",
        "data_scope": source.data_scope,
        "enabled": source.enabled,
        "status": source_status,
        "record_count": record_count,
        "last_sync_at": last_sync_at,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


def _record_data(record: BusinessRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "source_id": record.source_id,
        "external_id": record.external_id,
        "record_type": record.record_type,
        "title": record.title,
        "content": record.content,
        "payload": _json_load_dict(record.payload_json),
        "occurred_on": record.occurred_on,
        "occurred_at": record.occurred_at,
        "ingest_batch_id": record.ingest_batch_id,
        "created_at": record.created_at,
    }


def _alert_data(alert: BusinessAlert) -> dict[str, Any]:
    return {
        "id": alert.id,
        "rule_id": alert.rule_id,
        "source_id": alert.source_id,
        "record_id": alert.record_id,
        "severity": alert.level,
        "level": alert.level,
        "status": alert.status,
        "title": alert.title,
        "summary": alert.summary,
        "acknowledged_at": alert.acknowledged_at,
        "resolved_at": alert.resolved_at,
        "created_at": alert.created_at,
        "updated_at": alert.updated_at,
    }


def _rule_data(rule: BusinessAlertRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "record_type": rule.record_type,
        "keywords": _json_load_list(rule.keywords_json),
        "severity": rule.severity,
        "data_scope": rule.data_scope,
        "enabled": rule.enabled,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def _report_data(report: BusinessDailyReport) -> dict[str, Any]:
    return {
        "id": report.id,
        "title": f"{report.report_date.isoformat()} 生产日报",
        "report_date": report.report_date,
        "summary": report.summary,
        "metrics": _json_load_dict(report.metrics_json),
        "status": "generated",
        "generated_by": report.generated_by,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


def _task_data(task: BusinessBossTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "assignee_id": task.assignee_id,
        "alert_id": task.alert_id,
        "progress_note": task.progress_note,
        "due_date": task.due_date,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _message_data(message: BusinessAssistantMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "citations": _json_load_dict(message.citations_json).get("items", []),
        "created_at": message.created_at,
    }


def _write_business_audit(
    session: Session,
    *,
    actor_id: str | None,
    workspace_id: str,
    action: str,
    target_type: str,
    target_id: str,
    metadata: dict[str, Any] | None = None,
    data_scope: str = "company",
    scope_owner_user_id: str | None = None,
    private_to_user_id: str | None = None,
) -> None:
    """Write an auditable event without turning private metadata public.

    A company event remains visible to workspace governance.  Private scopes
    and per-user assistant history are marked private at write time; both the
    workspace and platform audit endpoints filter them server-side.
    """
    private_owner = private_to_user_id
    if data_scope != "company":
        if not scope_owner_user_id:
            raise RuntimeError("私有经营审计事件必须绑定可见用户")
        private_owner = scope_owner_user_id
    write_audit(
        session,
        actor_id=actor_id,
        workspace_id=workspace_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
        visibility="private" if private_owner else "workspace",
        owner_user_id=private_owner,
    )


def _ensure_business_bootstrap(session: Session, workspace: Workspace) -> bool:
    """Provision transparent defaults without fabricating any business data."""
    changed = False
    defaults = (
        ("boss_private", "老板智能体", "仅老板可见的经营查询、预警与任务空间。", workspace.owner_id),
        ("personal_private", "私事员工智能体", "仅老板可见的私密事项空间，不读取公司公事数据。", workspace.owner_id),
        ("company_public", "公事员工智能体", "面向公司成员的已授权业务数据查询空间。", None),
    )
    for agent_type, name, description, owner_user_id in defaults:
        subject = _assistant_subject(agent_type, owner_user_id)
        existing = session.exec(
            select(BusinessAssistant).where(
                BusinessAssistant.workspace_id == workspace.id,
                BusinessAssistant.agent_type == agent_type,
                BusinessAssistant.scope_subject_id == subject,
            )
        ).first()
        if not existing:
            session.add(
                BusinessAssistant(
                    workspace_id=workspace.id,
                    agent_type=agent_type,
                    name=name,
                    description=description,
                    owner_user_id=owner_user_id,
                    scope_subject_id=subject,
                    created_by=workspace.owner_id,
                )
            )
            changed = True

    default_rules = (
        ("生产异常预警", ["生产异常", "停线", "不良率", "质量异常"], "high"),
        ("订单风险预警", ["订单风险", "缺料", "欠料", "取消订单"], "high"),
        ("设备故障预警", ["设备故障", "设备报警", "故障停机"], "critical"),
        ("交期风险预警", ["交期延误", "延期交付", "交期风险"], "high"),
        ("审批超时预警", ["审批超时", "审批逾期"], "medium"),
    )
    for name, keywords, severity in default_rules:
        existing_rule = session.exec(
            select(BusinessAlertRule).where(
                BusinessAlertRule.workspace_id == workspace.id,
                BusinessAlertRule.name == name,
                BusinessAlertRule.data_scope == "company",
            )
        ).first()
        if not existing_rule:
            session.add(
                BusinessAlertRule(
                    workspace_id=workspace.id,
                    name=name,
                    keywords_json=json.dumps(keywords, ensure_ascii=False),
                    severity=severity,
                    data_scope="company",
                    owner_user_id=None,
                    created_by=workspace.owner_id,
                )
            )
            changed = True

    if changed:
        write_audit(
            session,
            actor_id=None,
            workspace_id=workspace.id,
            action="business.bootstrap_provisioned",
            target_type="workspace",
            target_id=workspace.id,
            metadata={"assistants": 3, "default_rules": 5},
        )
    return changed


def _record_matches_rule(record: BusinessRecord, rule: BusinessAlertRule) -> bool:
    if not rule.enabled or rule.data_scope != record.data_scope:
        return False
    if rule.owner_user_id != record.owner_user_id:
        return False
    if rule.record_type and rule.record_type != record.record_type:
        return False
    keywords = [keyword.strip().lower() for keyword in _json_load_list(rule.keywords_json) if keyword.strip()]
    if not keywords:
        return False
    haystack = f"{record.title}\n{record.content}\n{record.payload_json}".lower()
    return any(keyword in haystack for keyword in keywords)


def _evaluate_rules_for_record(
    session: Session,
    *,
    record: BusinessRecord,
    source: BusinessDataSource,
) -> list[BusinessAlert]:
    rules = session.exec(
        select(BusinessAlertRule).where(
            BusinessAlertRule.workspace_id == record.workspace_id,
            BusinessAlertRule.enabled.is_(True),
        )
    ).all()
    alerts: list[BusinessAlert] = []
    for rule in rules:
        if not _record_matches_rule(record, rule):
            continue
        dedupe_key = f"rule:{rule.id}:record:{record.id}"
        existing = session.exec(
            select(BusinessAlert).where(
                BusinessAlert.workspace_id == record.workspace_id,
                BusinessAlert.dedupe_key == dedupe_key,
            )
        ).first()
        if existing:
            continue
        alert = BusinessAlert(
            workspace_id=record.workspace_id,
            rule_id=rule.id,
            source_id=source.id,
            record_id=record.id,
            data_scope=record.data_scope,
            owner_user_id=record.owner_user_id,
            level=rule.severity,
            title=f"{rule.name}：{record.title}",
            summary=f"已授权数据源「{source.name}」中的记录命中规则「{rule.name}」。",
            dedupe_key=dedupe_key,
        )
        try:
            # A concurrent retry can evaluate the same rule at the same time.
            # The unique key is authoritative; a savepoint keeps the outer
            # record transaction usable after the losing insert rolls back.
            with session.begin_nested():
                session.add(alert)
                session.flush()
        except IntegrityError as exc:
            already_created = session.exec(
                select(BusinessAlert).where(
                    BusinessAlert.workspace_id == record.workspace_id,
                    BusinessAlert.dedupe_key == dedupe_key,
                )
            ).first()
            if already_created:
                continue
            raise HTTPException(status_code=409, detail="预警写入发生冲突，请重试") from exc
        _write_business_audit(
            session,
            actor_id=None,
            workspace_id=record.workspace_id,
            action="business.alert.rule_triggered",
            target_type="business_alert",
            target_id=alert.id,
            metadata={
                "rule_id": rule.id,
                "record_id": record.id,
                "source_id": source.id,
                "level": rule.severity,
            },
            data_scope=record.data_scope,
            scope_owner_user_id=record.owner_user_id,
        )
        alerts.append(alert)
    return alerts


def _normalise_occurred_at(entry: BusinessRecordInput) -> datetime:
    value = entry.occurred_at
    if value is None:
        return datetime.combine(entry.occurred_on, time.min, tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ingest_record(
    session: Session,
    *,
    source: BusinessDataSource,
    entry: BusinessRecordInput,
    batch_id: str,
    actor_id: str | None,
    channel: str,
) -> tuple[BusinessRecord, bool, list[BusinessAlert]]:
    existing = session.exec(
        select(BusinessRecord).where(
            BusinessRecord.source_id == source.id,
            BusinessRecord.external_id == entry.external_id,
        )
    ).first()
    if existing:
        return existing, False, []

    record = BusinessRecord(
        workspace_id=source.workspace_id,
        source_id=source.id,
        external_id=entry.external_id,
        record_type=entry.record_type,
        title=entry.title,
        content=entry.content,
        payload_json=_serialise_payload(entry.payload),
        occurred_on=entry.occurred_on,
        occurred_at=_normalise_occurred_at(entry),
        ingest_batch_id=batch_id,
        data_scope=source.data_scope,
        owner_user_id=source.owner_user_id,
    )
    try:
        # Keep the idempotency contract correct under concurrent delivery of
        # the same external event.  The database uniqueness constraint wins;
        # the losing transaction reloads the durable row instead of returning
        # an unhandled IntegrityError/500.
        with session.begin_nested():
            session.add(record)
            session.flush()
    except IntegrityError as exc:
        existing = session.exec(
            select(BusinessRecord).where(
                BusinessRecord.source_id == source.id,
                BusinessRecord.external_id == entry.external_id,
            )
        ).first()
        if existing:
            return existing, False, []
        raise HTTPException(status_code=409, detail="业务记录写入发生冲突，请重试") from exc
    alerts = _evaluate_rules_for_record(session, record=record, source=source)
    _write_business_audit(
        session,
        actor_id=actor_id,
        workspace_id=source.workspace_id,
        action="business.record.ingested",
        target_type="business_record",
        target_id=record.id,
        metadata={
            "source_id": source.id,
            "external_id": record.external_id,
            "record_type": record.record_type,
            "ingest_batch_id": batch_id,
            "channel": channel,
            "triggered_alert_count": len(alerts),
        },
        data_scope=source.data_scope,
        scope_owner_user_id=source.owner_user_id,
    )
    return record, True, alerts


# ---------------------------------------------------------------------------
# Assistant profiles and deterministic private conversations
# ---------------------------------------------------------------------------


@router.get("/dashboard")
def business_dashboard(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if _ensure_business_bootstrap(session, context.workspace):
        session.commit()

    sources = [
        source
        for source in session.exec(
            select(BusinessDataSource).where(BusinessDataSource.workspace_id == context.workspace.id)
        ).all()
        if _can_read_scope(context, source.data_scope, source.owner_user_id)
    ]
    alerts = [
        alert
        for alert in session.exec(
            select(BusinessAlert).where(BusinessAlert.workspace_id == context.workspace.id)
        ).all()
        if _can_read_scope(context, alert.data_scope, alert.owner_user_id)
    ]
    reports = session.exec(
        select(BusinessDailyReport).where(
            BusinessDailyReport.workspace_id == context.workspace.id
        )
    ).all()
    visible_tasks = [
        task
        for task in session.exec(
            select(BusinessBossTask).where(BusinessBossTask.workspace_id == context.workspace.id)
        ).all()
        if (
            (_is_workspace_boss(context) and task.boss_user_id == context.user.id)
            or task.assignee_id == context.user.id
        )
    ]
    return {
        "source_count": len(sources),
        "data_source_count": len(sources),
        "active_alert_count": sum(alert.status == "open" for alert in alerts),
        "alert_count": len(alerts),
        "report_count": len(reports),
        "daily_report_count": len(reports),
        "open_task_count": sum(task.status not in {"done", "cancelled"} for task in visible_tasks),
        "task_count": len(visible_tasks),
        "external_connection_status": "not_probed",
        "summary_engine": "deterministic_authorized_data",
    }


@router.get("/assistants")
def list_business_assistants(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if _ensure_business_bootstrap(session, context.workspace):
        session.commit()
    assistants = session.exec(
        select(BusinessAssistant)
        .where(BusinessAssistant.workspace_id == context.workspace.id)
        .order_by(BusinessAssistant.created_at)
    ).all()
    visible: list[dict[str, Any]] = []
    for assistant in assistants:
        try:
            _assistant_or_404(session, context, assistant.id)
        except HTTPException:
            continue
        visible.append(_assistant_data(assistant))
    return {"assistants": visible, "items": visible}


@router.post("/assistants", status_code=status.HTTP_201_CREATED)
def create_business_assistant(
    payload: AssistantCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    owner_user_id = None
    if payload.agent_type == "company_public":
        _require_workspace_manager(context)
    else:
        _require_workspace_boss(context)
        owner_user_id = context.user.id
    subject = _assistant_subject(payload.agent_type, owner_user_id)
    existing = session.exec(
        select(BusinessAssistant).where(
            BusinessAssistant.workspace_id == context.workspace.id,
            BusinessAssistant.agent_type == payload.agent_type,
            BusinessAssistant.scope_subject_id == subject,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="该范围的经营助手已存在")
    assistant = BusinessAssistant(
        workspace_id=context.workspace.id,
        agent_type=payload.agent_type,
        name=payload.name,
        description=payload.description,
        owner_user_id=owner_user_id,
        scope_subject_id=subject,
        created_by=context.user.id,
    )
    session.add(assistant)
    session.flush()
    _write_business_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="business.assistant.created",
        target_type="business_assistant",
        target_id=assistant.id,
        metadata={"assistant_type": assistant.agent_type},
        data_scope="company" if assistant.agent_type == "company_public" else assistant.agent_type,
        scope_owner_user_id=assistant.owner_user_id,
    )
    session.commit()
    return {"assistant": _assistant_data(assistant)}


@router.patch("/assistants/{assistant_id}")
def update_business_assistant(
    assistant_id: str,
    payload: AssistantUpdateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assistant = _assistant_or_404(session, context, assistant_id)
    if assistant.agent_type == "company_public":
        _require_workspace_manager(context)
    else:
        _require_workspace_boss(context)
    if payload.name is not None:
        assistant.name = payload.name
    if payload.description is not None:
        assistant.description = payload.description
    if payload.enabled is not None:
        assistant.enabled = payload.enabled
    assistant.updated_at = now_utc()
    session.add(assistant)
    _write_business_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="business.assistant.updated",
        target_type="business_assistant",
        target_id=assistant.id,
        metadata={"enabled": assistant.enabled},
        data_scope="company" if assistant.agent_type == "company_public" else assistant.agent_type,
        scope_owner_user_id=assistant.owner_user_id,
    )
    session.commit()
    return {"assistant": _assistant_data(assistant)}


@router.get("/assistants/{assistant_id}/messages")
def list_business_assistant_messages(
    assistant_id: str,
    limit: int = Query(100, ge=1, le=300),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    # Company-assistant conversations remain per-user, so a colleague cannot
    # read another employee's question history through a shared public agent.
    _assistant_or_404(session, context, assistant_id)
    messages = session.exec(
        select(BusinessAssistantMessage)
        .where(
            BusinessAssistantMessage.workspace_id == context.workspace.id,
            BusinessAssistantMessage.assistant_id == assistant_id,
            BusinessAssistantMessage.owner_user_id == context.user.id,
        )
        .order_by(BusinessAssistantMessage.created_at)
        .limit(limit)
    ).all()
    return {"messages": [_message_data(message) for message in messages], "items": [_message_data(message) for message in messages]}


def _assistant_scope_records(
    session: Session,
    context: WorkspaceContext,
    assistant: BusinessAssistant,
) -> list[BusinessRecord]:
    records = session.exec(
        select(BusinessRecord)
        .where(BusinessRecord.workspace_id == context.workspace.id)
        .order_by(BusinessRecord.occurred_at.desc())
        .limit(200)
    ).all()
    if assistant.agent_type == "company_public":
        return [record for record in records if record.data_scope == "company"]
    if assistant.agent_type == "boss_private":
        return [
            record
            for record in records
            if record.data_scope == "company"
            or (
                record.data_scope == "boss_private"
                and record.owner_user_id == context.user.id
            )
        ]
    return [
        record
        for record in records
        if record.data_scope == "personal_private" and record.owner_user_id == context.user.id
    ]


def _deterministic_reply(
    session: Session,
    context: WorkspaceContext,
    assistant: BusinessAssistant,
    question: str,
) -> tuple[str, list[dict[str, Any]]]:
    records = _assistant_scope_records(session, context, assistant)
    allowed_record_ids = {record.id for record in records}
    alerts = [
        alert
        for alert in session.exec(
            select(BusinessAlert)
            .where(BusinessAlert.workspace_id == context.workspace.id)
            .order_by(BusinessAlert.created_at.desc())
            .limit(100)
        ).all()
        if (
            alert.record_id in allowed_record_ids
            or (
                alert.record_id is None
                and _can_read_scope(context, alert.data_scope, alert.owner_user_id)
            )
        )
    ]
    open_alerts = [alert for alert in alerts if alert.status == "open"]
    own_tasks = [
        task
        for task in session.exec(
            select(BusinessBossTask).where(BusinessBossTask.workspace_id == context.workspace.id)
        ).all()
        if task.assignee_id == context.user.id
        or (_is_workspace_boss(context) and task.boss_user_id == context.user.id)
    ]

    type_counts = Counter(record.record_type for record in records)
    scope_label = {
        "company_public": "公司已授权数据",
        "boss_private": "老板可访问的公司与私有数据",
        "personal_private": "老板私事数据",
    }[assistant.agent_type]
    lines = [
        f"这是基于{scope_label}生成的确定性摘要；未调用外部模型，也未连接或抓取未授权系统。",
        f"当前可查询记录 {len(records)} 条，待处理预警 {len(open_alerts)} 条，与你相关的老板任务 {sum(task.status not in {'done', 'cancelled'} for task in own_tasks)} 条。",
    ]
    if type_counts:
        lines.append("记录分类：" + "、".join(f"{kind} {count} 条" for kind, count in sorted(type_counts.items())))
    if open_alerts:
        lines.append("优先关注：" + "；".join(alert.title for alert in open_alerts[:3]))
    if records:
        lines.append("最近记录：" + "；".join(record.title for record in records[:3]))
    if not records:
        lines.append("当前没有该范围内已授权且已接收的记录。请先完成数据源授权并提交业务记录。")
    if question:
        lines.append("已记录本次查询，将仅用于当前用户在此助手中的历史记录。")

    citations: list[dict[str, Any]] = [
        {"type": "record", "id": record.id, "record_type": record.record_type}
        for record in records[:5]
    ]
    citations.extend(
        {"type": "alert", "id": alert.id, "severity": alert.level}
        for alert in open_alerts[:5]
    )
    return "\n".join(lines), citations


@router.post("/assistants/{assistant_id}/chat")
def chat_with_business_assistant(
    assistant_id: str,
    payload: AssistantChatRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_member_write(context)
    assistant = _assistant_or_404(session, context, assistant_id)
    if not assistant.enabled:
        raise HTTPException(status_code=409, detail="该经营助手已停用")
    question = (payload.message or payload.query or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="请输入要查询的内容")
    reply, citations = _deterministic_reply(session, context, assistant, question)
    user_message = BusinessAssistantMessage(
        workspace_id=context.workspace.id,
        assistant_id=assistant.id,
        owner_user_id=context.user.id,
        role="user",
        content=question,
    )
    assistant_message = BusinessAssistantMessage(
        workspace_id=context.workspace.id,
        assistant_id=assistant.id,
        owner_user_id=context.user.id,
        role="assistant",
        content=reply,
        citations_json=json.dumps({"items": citations}, ensure_ascii=False),
    )
    session.add(user_message)
    session.add(assistant_message)
    session.flush()
    _write_business_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="business.assistant.queried",
        target_type="business_assistant",
        target_id=assistant.id,
        metadata={"assistant_type": assistant.agent_type, "citation_count": len(citations)},
        private_to_user_id=context.user.id,
    )
    session.commit()
    return {
        "reply": reply,
        "message": _message_data(user_message),
        "assistant_message": _message_data(assistant_message),
        "engine": "deterministic_authorized_data",
        "external_model_called": False,
    }


# ---------------------------------------------------------------------------
# Authorised source configuration and inbound business records
# ---------------------------------------------------------------------------


@router.get("/data-sources")
def list_business_data_sources(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    sources = session.exec(
        select(BusinessDataSource)
        .where(BusinessDataSource.workspace_id == context.workspace.id)
        .order_by(BusinessDataSource.created_at.desc())
    ).all()
    records = session.exec(
        select(BusinessRecord).where(BusinessRecord.workspace_id == context.workspace.id)
    ).all()
    counts = Counter(record.source_id for record in records)
    latest: dict[str, datetime] = {}
    for record in records:
        if record.source_id not in latest or record.created_at > latest[record.source_id]:
            latest[record.source_id] = record.created_at
    visible = [
        _source_data(source, record_count=counts.get(source.id, 0), last_sync_at=latest.get(source.id))
        for source in sources
        if _can_read_scope(context, source.data_scope, source.owner_user_id)
    ]
    return {"data_sources": visible, "sources": visible, "items": visible}


def _ingest_url(request: Request, source_id: str) -> str:
    return str(request.base_url).rstrip("/") + f"/api/v1/business/ingest/{source_id}"


@router.post("/data-sources", status_code=status.HTTP_201_CREATED)
def create_business_data_source(
    payload: DataSourceCreateRequest,
    request: Request,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source_type = _normalise_source_type(payload.source_type)
    connection_mode = _normalise_connection_mode(payload.connection_mode)
    owner_user_id = _scope_owner_for_create(context, payload.data_scope)
    endpoint_url = _safe_endpoint_url(payload.endpoint_url)
    access_scope = _safe_authorization_reference(payload.access_scope)
    authorization_reference = _safe_authorization_reference(payload.authorization_reference)
    reference = authorization_reference or access_scope
    ingest_token = _new_ingest_token() if connection_mode in {"api", "webhook"} else None
    source = BusinessDataSource(
        workspace_id=context.workspace.id,
        name=payload.name,
        source_type=source_type,
        connection_mode=connection_mode,
        endpoint_url=endpoint_url,
        authorization_reference=reference,
        data_scope=payload.data_scope,
        owner_user_id=owner_user_id,
        ingest_token_hash=_token_hash(ingest_token) if ingest_token else "",
        ingest_token_last_rotated_at=now_utc() if ingest_token else None,
        created_by=context.user.id,
    )
    session.add(source)
    session.flush()
    _write_business_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="business.data_source.created",
        target_type="business_data_source",
        target_id=source.id,
        metadata={
            "source_type": source.source_type,
            "connection_mode": source.connection_mode,
            "data_scope": source.data_scope,
            "ingest_token_issued": bool(ingest_token),
        },
        data_scope=source.data_scope,
        scope_owner_user_id=source.owner_user_id,
    )
    session.commit()
    response: dict[str, Any] = {"data_source": _source_data(source)}
    if ingest_token:
        # This is intentionally the only response that contains plaintext.
        # The database and audit trail contain only a one-way digest/boolean.
        response.update({"ingest_url": _ingest_url(request, source.id), "ingest_token": ingest_token})
    return response


@router.patch("/data-sources/{source_id}")
def update_business_data_source(
    source_id: str,
    payload: DataSourceUpdateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = _source_or_404(session, context.workspace.id, source_id)
    _require_scope_manager(context, source.data_scope, source.owner_user_id)
    if payload.name is not None:
        source.name = payload.name
    if payload.endpoint_url is not None:
        source.endpoint_url = _safe_endpoint_url(payload.endpoint_url)
    reference = payload.authorization_reference
    if reference is None:
        reference = payload.access_scope
    if reference is not None:
        source.authorization_reference = _safe_authorization_reference(reference)
    if payload.enabled is not None:
        source.enabled = payload.enabled
    source.updated_at = now_utc()
    session.add(source)
    _write_business_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="business.data_source.updated",
        target_type="business_data_source",
        target_id=source.id,
        metadata={"enabled": source.enabled},
        data_scope=source.data_scope,
        scope_owner_user_id=source.owner_user_id,
    )
    session.commit()
    return {"data_source": _source_data(source)}


@router.post("/data-sources/{source_id}/rotate-ingest-token")
def rotate_business_ingest_token(
    source_id: str,
    request: Request,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = _source_or_404(session, context.workspace.id, source_id)
    _require_scope_manager(context, source.data_scope, source.owner_user_id)
    if source.connection_mode not in {"api", "webhook"}:
        raise HTTPException(status_code=409, detail="文件导入数据源不使用入站令牌")
    ingest_token = _new_ingest_token()
    source.ingest_token_hash = _token_hash(ingest_token)
    source.ingest_token_last_rotated_at = now_utc()
    source.updated_at = now_utc()
    session.add(source)
    _write_business_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="business.data_source.ingest_token_rotated",
        target_type="business_data_source",
        target_id=source.id,
        metadata={"connection_mode": source.connection_mode},
        data_scope=source.data_scope,
        scope_owner_user_id=source.owner_user_id,
    )
    session.commit()
    return {
        "ingest_url": _ingest_url(request, source.id),
        "ingest_token": ingest_token,
        "data_source": _source_data(source),
    }


def _ingest_entries(
    session: Session,
    *,
    source: BusinessDataSource,
    entries: list[BusinessRecordInput],
    actor_id: str | None,
    channel: str,
) -> tuple[list[BusinessRecord], list[bool], int, list[BusinessAlert], str]:
    if not source.enabled:
        raise HTTPException(status_code=409, detail="该业务数据源已停用")
    workspace = session.get(Workspace, source.workspace_id)
    if not workspace:
        raise HTTPException(status_code=409, detail="业务数据源所属工作区不存在")
    _ensure_business_bootstrap(session, workspace)
    batch_id = new_id()
    records: list[BusinessRecord] = []
    created_flags: list[bool] = []
    alerts: list[BusinessAlert] = []
    created_count = 0
    for entry in entries:
        record, created, generated_alerts = _ingest_record(
            session,
            source=source,
            entry=entry,
            batch_id=batch_id,
            actor_id=actor_id,
            channel=channel,
        )
        records.append(record)
        created_flags.append(created)
        created_count += int(created)
        alerts.extend(generated_alerts)
    return records, created_flags, created_count, alerts, batch_id


@router.post("/data-sources/{source_id}/records", status_code=status.HTTP_201_CREATED)
def submit_authenticated_business_record(
    source_id: str,
    payload: BusinessRecordInput,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = _source_or_404(session, context.workspace.id, source_id)
    _require_scope_manager(context, source.data_scope, source.owner_user_id)
    records, created_flags, created_count, alerts, batch_id = _ingest_entries(
        session,
        source=source,
        entries=[payload],
        actor_id=context.user.id,
        channel="authenticated_submission",
    )
    session.commit()
    return {
        "record": _record_data(records[0]),
        "created": created_flags[0],
        "alerts": [_alert_data(alert) for alert in alerts],
        "ingest_batch_id": batch_id,
    }


@router.post("/data-sources/{source_id}/records/batch", status_code=status.HTTP_201_CREATED)
def submit_authenticated_business_record_batch(
    source_id: str,
    payload: BusinessRecordBatchRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = _source_or_404(session, context.workspace.id, source_id)
    _require_scope_manager(context, source.data_scope, source.owner_user_id)
    records, _created_flags, created_count, alerts, batch_id = _ingest_entries(
        session,
        source=source,
        entries=payload.records,
        actor_id=context.user.id,
        channel="authenticated_batch_submission",
    )
    session.commit()
    return {
        "records": [_record_data(record) for record in records],
        "created_count": created_count,
        "alerts": [_alert_data(alert) for alert in alerts],
        "ingest_batch_id": batch_id,
    }


@router.post("/ingest/{source_id}", status_code=status.HTTP_201_CREATED, name="business_ingest_record")
def ingest_authorised_business_record(
    source_id: str,
    payload: BusinessRecordInput,
    ingest_token: str | None = Header(default=None, alias="X-Business-Ingest-Token"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = session.get(BusinessDataSource, source_id)
    if not source:
        # Do not reveal whether an arbitrary source identifier exists.
        raise HTTPException(status_code=401, detail="业务数据接入凭据无效")
    if source.connection_mode not in {"api", "webhook"}:
        raise HTTPException(status_code=409, detail="该数据源不接受接口推送")
    _validate_ingest_token(source, ingest_token)
    records, created_flags, created_count, alerts, batch_id = _ingest_entries(
        session,
        source=source,
        entries=[payload],
        actor_id=None,
        channel="authorised_ingest",
    )
    session.commit()
    if not created_flags[0]:
        # An integration credential authorises delivery, not read access.  Do
        # not reveal the pre-existing record's title, content, payload, ID or
        # source metadata when a retried external_id is already present.
        return {
            "receipt": {"external_id": payload.external_id, "created": False},
            "created": False,
            "ingest_batch_id": batch_id,
        }
    return {
        "record": _record_data(records[0]),
        "created": True,
        "alerts": [_alert_data(alert) for alert in alerts],
        "ingest_batch_id": batch_id,
    }


@router.post("/ingest/{source_id}/batch", status_code=status.HTTP_201_CREATED)
def ingest_authorised_business_record_batch(
    source_id: str,
    payload: BusinessRecordBatchRequest,
    ingest_token: str | None = Header(default=None, alias="X-Business-Ingest-Token"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = session.get(BusinessDataSource, source_id)
    if not source:
        raise HTTPException(status_code=401, detail="业务数据接入凭据无效")
    if source.connection_mode not in {"api", "webhook"}:
        raise HTTPException(status_code=409, detail="该数据源不接受接口推送")
    _validate_ingest_token(source, ingest_token)
    records, created_flags, created_count, alerts, batch_id = _ingest_entries(
        session,
        source=source,
        entries=payload.records,
        actor_id=None,
        channel="authorised_ingest_batch",
    )
    session.commit()
    # Batch integrations receive only idempotency receipts.  In particular, a
    # guessed/retried external_id can never turn a write token into a record
    # read API.  Newly triggered alerts are intentionally omitted here too.
    return {
        "receipts": [
            {"external_id": entry.external_id, "created": created}
            for entry, created in zip(payload.records, created_flags, strict=True)
        ],
        "created_count": created_count,
        "ingest_batch_id": batch_id,
    }


@router.get("/records")
def list_business_records(
    limit: int = Query(100, ge=1, le=500),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    records = session.exec(
        select(BusinessRecord)
        .where(BusinessRecord.workspace_id == context.workspace.id)
        .order_by(BusinessRecord.occurred_at.desc())
        .limit(limit)
    ).all()
    # Raw payload is only a management view for company data. Private source
    # owners can view their own data, never another user's private records.
    visible = []
    for record in records:
        if record.data_scope == "company":
            if context.membership.role not in {"owner", "admin"}:
                continue
        elif not _can_read_scope(context, record.data_scope, record.owner_user_id):
            continue
        visible.append(_record_data(record))
    return {"records": visible, "items": visible}


# ---------------------------------------------------------------------------
# Rules, alerts and deterministic production daily reports
# ---------------------------------------------------------------------------


@router.get("/alert-rules")
def list_business_alert_rules(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if _ensure_business_bootstrap(session, context.workspace):
        session.commit()
    rules = session.exec(
        select(BusinessAlertRule)
        .where(BusinessAlertRule.workspace_id == context.workspace.id)
        .order_by(BusinessAlertRule.created_at)
    ).all()
    visible = [
        _rule_data(rule)
        for rule in rules
        if _can_read_scope(context, rule.data_scope, rule.owner_user_id)
    ]
    return {"alert_rules": visible, "items": visible}


@router.post("/alert-rules", status_code=status.HTTP_201_CREATED)
def create_business_alert_rule(
    payload: AlertRuleCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    owner_user_id = _scope_owner_for_create(context, payload.data_scope)
    keywords = [keyword.strip() for keyword in payload.keywords if keyword.strip()]
    if not keywords:
        raise HTTPException(status_code=422, detail="预警规则至少需要一个有效关键字")
    rule = BusinessAlertRule(
        workspace_id=context.workspace.id,
        name=payload.name,
        record_type=payload.record_type,
        keywords_json=json.dumps(keywords, ensure_ascii=False),
        severity=payload.severity,
        data_scope=payload.data_scope,
        owner_user_id=owner_user_id,
        created_by=context.user.id,
    )
    session.add(rule)
    session.flush()
    _write_business_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="business.alert_rule.created",
        target_type="business_alert_rule",
        target_id=rule.id,
        metadata={"data_scope": rule.data_scope, "severity": rule.severity},
        data_scope=rule.data_scope,
        scope_owner_user_id=rule.owner_user_id,
    )
    session.commit()
    return {"alert_rule": _rule_data(rule)}


@router.patch("/alert-rules/{rule_id}")
def update_business_alert_rule(
    rule_id: str,
    payload: AlertRuleUpdateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    rule = _rule_or_404(session, context.workspace.id, rule_id)
    _require_scope_manager(context, rule.data_scope, rule.owner_user_id)
    if payload.name is not None:
        rule.name = payload.name
    if payload.record_type is not None:
        rule.record_type = payload.record_type
    if payload.keywords is not None:
        keywords = [keyword.strip() for keyword in payload.keywords if keyword.strip()]
        if not keywords:
            raise HTTPException(status_code=422, detail="预警规则至少需要一个有效关键字")
        rule.keywords_json = json.dumps(keywords, ensure_ascii=False)
    if payload.severity is not None:
        rule.severity = payload.severity
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    rule.updated_at = now_utc()
    session.add(rule)
    _write_business_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="business.alert_rule.updated",
        target_type="business_alert_rule",
        target_id=rule.id,
        metadata={"enabled": rule.enabled, "severity": rule.severity},
        data_scope=rule.data_scope,
        scope_owner_user_id=rule.owner_user_id,
    )
    session.commit()
    return {"alert_rule": _rule_data(rule)}


@router.get("/alerts")
def list_business_alerts(
    include_resolved: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    statement = (
        select(BusinessAlert)
        .where(BusinessAlert.workspace_id == context.workspace.id)
        .order_by(BusinessAlert.created_at.desc())
        .limit(limit)
    )
    alerts = session.exec(statement).all()
    visible = [
        _alert_data(alert)
        for alert in alerts
        if (include_resolved or alert.status != "resolved")
        and _can_read_scope(context, alert.data_scope, alert.owner_user_id)
    ]
    return {"alerts": visible, "items": visible}


@router.post("/alerts", status_code=status.HTTP_201_CREATED)
def create_manual_business_alert(
    payload: ManualAlertCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source: BusinessDataSource | None = None
    record: BusinessRecord | None = None
    if payload.source_id:
        source = _source_or_404(session, context.workspace.id, payload.source_id)
    if payload.record_id:
        record = _record_or_404(session, context.workspace.id, payload.record_id)
        if source and record.source_id != source.id:
            raise HTTPException(status_code=422, detail="业务记录不属于指定的数据源")
        source = _source_or_404(session, context.workspace.id, record.source_id)

    data_scope = record.data_scope if record else (source.data_scope if source else payload.data_scope)
    owner_user_id = record.owner_user_id if record else (source.owner_user_id if source else None)
    if payload.data_scope != data_scope and (source or record):
        raise HTTPException(status_code=422, detail="预警范围必须与关联数据源或记录一致")
    if source and source.owner_user_id != owner_user_id:
        raise HTTPException(status_code=409, detail="预警关联数据范围不一致")
    _require_scope_manager(context, data_scope, owner_user_id)
    alert = BusinessAlert(
        workspace_id=context.workspace.id,
        source_id=source.id if source else None,
        record_id=record.id if record else None,
        data_scope=data_scope,
        owner_user_id=owner_user_id,
        level=payload.severity,
        title=payload.title,
        summary=payload.summary,
        dedupe_key=f"manual:{new_id()}",
    )
    session.add(alert)
    session.flush()
    _write_business_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="business.alert.created",
        target_type="business_alert",
        target_id=alert.id,
        metadata={"source_id": alert.source_id, "record_id": alert.record_id, "level": alert.level},
        data_scope=alert.data_scope,
        scope_owner_user_id=alert.owner_user_id,
    )
    session.commit()
    return {"alert": _alert_data(alert)}


def _require_alert_actor(context: WorkspaceContext, alert: BusinessAlert) -> None:
    if alert.data_scope == "company":
        _require_member_write(context)
        return
    if not _can_read_scope(context, alert.data_scope, alert.owner_user_id):
        raise HTTPException(status_code=404, detail="预警不存在")


def _require_alert_resolver(context: WorkspaceContext, alert: BusinessAlert) -> None:
    """Acknowledgement can be collaborative; resolution is a manager action."""
    if alert.data_scope == "company":
        _require_workspace_manager(context)
        return
    _require_scope_manager(context, alert.data_scope, alert.owner_user_id)


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_business_alert(
    alert_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    alert = _alert_or_404(session, context.workspace.id, alert_id)
    _require_alert_actor(context, alert)
    if alert.status == "resolved":
        raise HTTPException(status_code=409, detail="已解决的预警不能重复确认")
    if alert.status == "open":
        alert.status = "acknowledged"
        alert.acknowledged_by = context.user.id
        alert.acknowledged_at = now_utc()
        alert.updated_at = now_utc()
        session.add(alert)
        _write_business_audit(
            session,
            actor_id=context.user.id,
            workspace_id=context.workspace.id,
            action="business.alert.acknowledged",
            target_type="business_alert",
            target_id=alert.id,
            data_scope=alert.data_scope,
            scope_owner_user_id=alert.owner_user_id,
        )
        session.commit()
    return {"alert": _alert_data(alert)}


@router.post("/alerts/{alert_id}/resolve")
def resolve_business_alert(
    alert_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    alert = _alert_or_404(session, context.workspace.id, alert_id)
    _require_alert_resolver(context, alert)
    if alert.status != "resolved":
        alert.status = "resolved"
        alert.resolved_by = context.user.id
        alert.resolved_at = now_utc()
        alert.updated_at = now_utc()
        session.add(alert)
        _write_business_audit(
            session,
            actor_id=context.user.id,
            workspace_id=context.workspace.id,
            action="business.alert.resolved",
            target_type="business_alert",
            target_id=alert.id,
            data_scope=alert.data_scope,
            scope_owner_user_id=alert.owner_user_id,
        )
        session.commit()
    return {"alert": _alert_data(alert)}


def _generate_daily_report(
    session: Session,
    *,
    workspace_id: str,
    report_date: date,
    generated_by: str,
) -> BusinessDailyReport:
    # Private records, private alerts and their message histories are not in
    # this aggregation.  This makes a public production report safe to list to
    # all workspace members.
    records = session.exec(
        select(BusinessRecord).where(
            BusinessRecord.workspace_id == workspace_id,
            BusinessRecord.data_scope == "company",
            BusinessRecord.occurred_on == report_date,
        )
    ).all()
    alerts = session.exec(
        select(BusinessAlert).where(
            BusinessAlert.workspace_id == workspace_id,
            BusinessAlert.data_scope == "company",
        )
    ).all()
    open_alerts = [alert for alert in alerts if alert.status == "open"]
    record_types = Counter(record.record_type for record in records)
    alert_levels = Counter(alert.level for alert in open_alerts)
    metrics = {
        "record_count": len(records),
        "record_types": dict(sorted(record_types.items())),
        "open_alert_count": len(open_alerts),
        "open_alert_levels": dict(sorted(alert_levels.items())),
        "filters": {
            "data_scope": "company",
            "occurred_on": report_date.isoformat(),
            "private_records_excluded": True,
        },
    }
    type_summary = "、".join(f"{name} {count} 条" for name, count in sorted(record_types.items())) or "无"
    alert_summary = "、".join(f"{name} {count} 条" for name, count in sorted(alert_levels.items())) or "无"
    summary = (
        f"{report_date.isoformat()} 生产日报：仅汇总公司范围内已授权且可追溯的数据。"
        f"当日记录 {len(records)} 条（{type_summary}）；当前未闭环预警 {len(open_alerts)} 条（{alert_summary}）。"
        "该日报由规则引擎生成，发布前需人工复核。"
    )
    report = session.exec(
        select(BusinessDailyReport).where(
            BusinessDailyReport.workspace_id == workspace_id,
            BusinessDailyReport.report_date == report_date,
        )
    ).first()
    if not report:
        report = BusinessDailyReport(
            workspace_id=workspace_id,
            report_date=report_date,
            summary=summary,
            metrics_json=json.dumps(metrics, ensure_ascii=False),
            generated_by=generated_by,
        )
    else:
        report.summary = summary
        report.metrics_json = json.dumps(metrics, ensure_ascii=False)
        report.generated_by = generated_by
        report.updated_at = now_utc()
    session.add(report)
    session.flush()
    return report


@router.get("/daily-reports")
def list_business_daily_reports(
    limit: int = Query(90, ge=1, le=365),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    reports = session.exec(
        select(BusinessDailyReport)
        .where(BusinessDailyReport.workspace_id == context.workspace.id)
        .order_by(BusinessDailyReport.report_date.desc())
        .limit(limit)
    ).all()
    result = [_report_data(report) for report in reports]
    return {"daily_reports": result, "reports": result, "items": result}


@router.post("/daily-reports/generate")
@router.post("/daily-reports")
def generate_business_daily_report(
    payload: DailyReportGenerateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_workspace_manager(context)
    report = _generate_daily_report(
        session,
        workspace_id=context.workspace.id,
        report_date=payload.report_date,
        generated_by=context.user.id,
    )
    _write_business_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="business.daily_report.generated",
        target_type="business_daily_report",
        target_id=report.id,
        metadata={"report_date": report.report_date.isoformat(), "data_scope": "company"},
    )
    session.commit()
    return {"daily_report": _report_data(report)}


# ---------------------------------------------------------------------------
# Boss-issued, assignee-visible tasks
# ---------------------------------------------------------------------------


def _can_view_boss_task(context: WorkspaceContext, task: BusinessBossTask) -> bool:
    # The task keeps the issuing boss ID.  A later owner transfer therefore
    # cannot expose an earlier boss's private task history to a new owner.
    return (
        (_is_workspace_boss(context) and task.boss_user_id == context.user.id)
        or task.assignee_id == context.user.id
    )


@router.get("/tasks")
def list_business_boss_tasks(
    include_closed: bool = Query(True),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    tasks = session.exec(
        select(BusinessBossTask)
        .where(BusinessBossTask.workspace_id == context.workspace.id)
        .order_by(BusinessBossTask.updated_at.desc())
    ).all()
    visible = [
        _task_data(task)
        for task in tasks
        if _can_view_boss_task(context, task)
        and (include_closed or task.status not in {"done", "cancelled"})
    ]
    return {"tasks": visible, "items": visible}


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_business_boss_task(
    payload: BossTaskCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_workspace_boss(context)
    _member_or_422(session, context.workspace.id, payload.assignee_id)
    if payload.alert_id:
        alert = _alert_or_404(session, context.workspace.id, payload.alert_id)
        if not _can_read_scope(context, alert.data_scope, alert.owner_user_id):
            # Do not let a boss task link to another user's private alert.
            raise HTTPException(status_code=404, detail="预警不存在")
    task = BusinessBossTask(
        workspace_id=context.workspace.id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        boss_user_id=context.user.id,
        assignee_id=payload.assignee_id,
        alert_id=payload.alert_id,
        created_by=context.user.id,
        due_date=payload.due_date,
    )
    session.add(task)
    session.flush()
    _write_business_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="business.boss_task.created",
        target_type="business_boss_task",
        target_id=task.id,
        metadata={"assignee_id": task.assignee_id, "alert_id": task.alert_id, "priority": task.priority},
        private_to_user_id=task.boss_user_id,
    )
    session.commit()
    return {"task": _task_data(task)}


@router.patch("/tasks/{task_id}")
def update_business_boss_task(
    task_id: str,
    payload: BossTaskUpdateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    task = _task_or_404(session, context.workspace.id, task_id)
    if not _can_view_boss_task(context, task):
        raise HTTPException(status_code=404, detail="老板任务不存在")
    boss_controls_task = _is_workspace_boss(context) and task.boss_user_id == context.user.id
    assignee_controls_progress = task.assignee_id == context.user.id
    if not boss_controls_task and not assignee_controls_progress:
        raise HTTPException(status_code=404, detail="老板任务不存在")

    non_assignee_fields = {
        "title": payload.title,
        "description": payload.description,
        "priority": payload.priority,
        "due_date": payload.due_date,
        "assignee_id": payload.assignee_id,
    }
    if not boss_controls_task and any(value is not None for value in non_assignee_fields.values()):
        raise HTTPException(status_code=403, detail="任务负责人只能更新状态和进度说明")
    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.due_date is not None:
        task.due_date = payload.due_date
    if payload.assignee_id is not None:
        _member_or_422(session, context.workspace.id, payload.assignee_id)
        task.assignee_id = payload.assignee_id
    if payload.status is not None:
        task.status = payload.status
    if payload.progress_note is not None:
        task.progress_note = payload.progress_note
    task.updated_at = now_utc()
    session.add(task)
    _write_business_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="business.boss_task.updated",
        target_type="business_boss_task",
        target_id=task.id,
        metadata={"status": task.status, "assignee_id": task.assignee_id},
        private_to_user_id=task.boss_user_id,
    )
    session.commit()
    return {"task": _task_data(task)}
