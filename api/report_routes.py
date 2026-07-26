"""汇报智能体 API 路由。

本模块不抓取微信、不绕过登录、不调用未经验证的外部模型。
仅通过显式授权的 API/Webhook 令牌或认证的文件导入路径接收记录，
然后生成确定性摘要、关键字预警和日期报告。
支持知识库、文件和接口的输入和对接。
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections import Counter
from datetime import date, datetime, time, timezone
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query, Request, status, UploadFile, File
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from api.dependencies import WorkspaceContext, get_workspace_context, write_audit
from db.database import get_session
from db.report_models import (
    KnowledgeBase,
    ReportAlert,
    ReportAlertRule,
    ReportAssistant,
    ReportAssistantMessage,
    ReportDailyReport,
    ReportDataSource,
    ReportRecord,
    ReportWeeklyReport,
    new_id,
    now_utc,
)


router = APIRouter(tags=["汇报智能体"])

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
REPORT_TYPES = {"daily", "weekly", "monthly"}


class ReportRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class DataSourceCreateRequest(ReportRequest):
    name: str = Field(min_length=2, max_length=160)
    source_type: str = Field(min_length=2, max_length=32)
    connection_mode: str = Field(default="api", min_length=2, max_length=32)
    access_scope: str = Field(default="", max_length=240)
    authorization_reference: str = Field(default="", max_length=240)
    endpoint_url: str = Field(default="", max_length=1000)


class DataSourceUpdateRequest(ReportRequest):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    access_scope: str | None = Field(default=None, max_length=240)
    authorization_reference: str | None = Field(default=None, max_length=240)
    endpoint_url: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = None


class ReportRecordInput(ReportRequest):
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


class ReportRecordBatchRequest(ReportRequest):
    records: list[ReportRecordInput] = Field(min_length=1, max_length=100)


class AlertRuleCreateRequest(ReportRequest):
    name: str = Field(min_length=2, max_length=160)
    record_type: str = Field(default="", max_length=64)
    keywords: list[str] = Field(min_length=1, max_length=30)
    severity: Literal["low", "medium", "high", "critical"] = "medium"


class AlertRuleUpdateRequest(ReportRequest):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    record_type: str | None = Field(default=None, max_length=64)
    keywords: list[str] | None = Field(default=None, min_length=1, max_length=30)
    severity: Literal["low", "medium", "high", "critical"] | None = None
    enabled: bool | None = None


class ManualAlertCreateRequest(ReportRequest):
    title: str = Field(min_length=2, max_length=240)
    summary: str = Field(default="", max_length=4000)
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    source_id: str | None = Field(default=None, max_length=64)
    record_id: str | None = Field(default=None, max_length=64)


class DailyReportGenerateRequest(ReportRequest):
    report_date: date = Field(default_factory=date.today)


class WeeklyReportGenerateRequest(ReportRequest):
    week_start_date: date
    week_end_date: date
    title: str = Field(default="", max_length=240)


class KnowledgeBaseCreateRequest(ReportRequest):
    title: str = Field(min_length=2, max_length=240)
    description: str = Field(default="", max_length=2000)
    content: str = Field(default="", max_length=100_000)


class KnowledgeBaseUpdateRequest(ReportRequest):
    title: str | None = Field(default=None, min_length=2, max_length=240)
    description: str | None = Field(default=None, max_length=2000)
    content: str | None = Field(default=None, max_length=100_000)


class ChatRequest(ReportRequest):
    message: str | None = Field(default=None, min_length=1, max_length=16000)
    query: str | None = Field(default=None, min_length=1, max_length=16000)


def _require_member_write(context: WorkspaceContext) -> None:
    """需要实际的工作区成员身份；平台管理员不是绕过方式。"""
    if context.membership.role == "viewer":
        raise HTTPException(status_code=403, detail="只读成员不能执行此操作")


def _require_workspace_manager(context: WorkspaceContext) -> None:
    """管理员必须是当前工作区的 owner/admin。"""
    if context.membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="需要当前工作区的管理权限")


def _source_or_404(session: Session, workspace_id: str, source_id: str) -> ReportDataSource:
    source = session.get(ReportDataSource, source_id)
    if not source or source.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="业务数据源不存在")
    return source


def _record_or_404(session: Session, workspace_id: str, record_id: str) -> ReportRecord:
    record = session.get(ReportRecord, record_id)
    if not record or record.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="业务记录不存在")
    return record


def _alert_or_404(session: Session, workspace_id: str, alert_id: str) -> ReportAlert:
    alert = session.get(ReportAlert, alert_id)
    if not alert or alert.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="预警不存在")
    return alert


def _rule_or_404(session: Session, workspace_id: str, rule_id: str) -> ReportAlertRule:
    rule = session.get(ReportAlertRule, rule_id)
    if not rule or rule.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="预警规则不存在")
    return rule


def _knowledge_base_or_404(session: Session, workspace_id: str, kb_id: str) -> KnowledgeBase:
    kb = session.get(KnowledgeBase, kb_id)
    if not kb or kb.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="知识库文档不存在")
    return kb


def _safe_endpoint_url(value: str) -> str:
    """仅保存非凭证的 HTTP(S) 端点元数据 URL。

    本产品永远不会对保存的 URL 发出出站请求。拒绝 userinfo、查询字符串和片段
    可以防止意外地将令牌存储在配置字段中。
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


def _validate_ingest_token(source: ReportDataSource, supplied: str | None) -> None:
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


def _source_data(
    source: ReportDataSource,
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
        "endpoint_configured": bool(source.endpoint_url),
        "authorization_configured": bool(source.authorization_reference),
        "access_scope": "已登记最小权限范围" if source.authorization_reference else "待补充授权范围",
        "enabled": source.enabled,
        "status": source_status,
        "record_count": record_count,
        "last_sync_at": last_sync_at,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


def _record_data(record: ReportRecord) -> dict[str, Any]:
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


def _alert_data(alert: ReportAlert) -> dict[str, Any]:
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


def _rule_data(rule: ReportAlertRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "record_type": rule.record_type,
        "keywords": _json_load_list(rule.keywords_json),
        "severity": rule.severity,
        "enabled": rule.enabled,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def _report_data(report: ReportDailyReport) -> dict[str, Any]:
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


def _weekly_report_data(report: ReportWeeklyReport) -> dict[str, Any]:
    return {
        "id": report.id,
        "title": report.title or f"{report.week_start_date.isoformat()} 周报",
        "week_start_date": report.week_start_date,
        "week_end_date": report.week_end_date,
        "summary": report.summary,
        "metrics": _json_load_dict(report.metrics_json),
        "status": "generated",
        "generated_by": report.generated_by,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


def _knowledge_base_data(kb: KnowledgeBase) -> dict[str, Any]:
    return {
        "id": kb.id,
        "title": kb.title,
        "description": kb.description,
        "content": kb.content,
        "file_name": kb.file_name,
        "file_type": kb.file_type,
        "file_size": kb.file_size,
        "created_by": kb.created_by,
        "created_at": kb.created_at,
        "updated_at": kb.updated_at,
    }


def _message_data(message: ReportAssistantMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "citations": _json_load_dict(message.citations_json).get("items", []),
        "created_at": message.created_at,
    }


def _write_report_audit(
    session: Session,
    *,
    actor_id: str | None,
    workspace_id: str,
    action: str,
    target_type: str,
    target_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    write_audit(
        session,
        actor_id=actor_id,
        workspace_id=workspace_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
        visibility="workspace",
        owner_user_id=None,
    )


def _ensure_report_bootstrap(session: Session, workspace_id: str, owner_user_id: str) -> bool:
    """供应透明默认值，不伪造任何业务数据。"""
    changed = False
    existing = session.exec(
        select(ReportAssistant).where(ReportAssistant.workspace_id == workspace_id)
    ).first()
    if not existing:
        session.add(
            ReportAssistant(
                workspace_id=workspace_id,
                name="汇报智能体",
                description="汇总已授权数据，生成日报、总结和风险预警。",
                created_by=owner_user_id,
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
            select(ReportAlertRule).where(
                ReportAlertRule.workspace_id == workspace_id,
                ReportAlertRule.name == name,
            )
        ).first()
        if not existing_rule:
            session.add(
                ReportAlertRule(
                    workspace_id=workspace_id,
                    name=name,
                    keywords_json=json.dumps(keywords, ensure_ascii=False),
                    severity=severity,
                    created_by=owner_user_id,
                )
            )
            changed = True

    if changed:
        _write_report_audit(
            session,
            actor_id=None,
            workspace_id=workspace_id,
            action="report.bootstrap_provisioned",
            target_type="workspace",
            target_id=workspace_id,
            metadata={"default_rules": 5},
        )
    return changed


def _record_matches_rule(record: ReportRecord, rule: ReportAlertRule) -> bool:
    if not rule.enabled:
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
    record: ReportRecord,
    source: ReportDataSource,
) -> list[ReportAlert]:
    rules = session.exec(
        select(ReportAlertRule).where(
            ReportAlertRule.workspace_id == record.workspace_id,
            ReportAlertRule.enabled.is_(True),
        )
    ).all()
    alerts: list[ReportAlert] = []
    for rule in rules:
        if not _record_matches_rule(record, rule):
            continue
        dedupe_key = f"rule:{rule.id}:record:{record.id}"
        existing = session.exec(
            select(ReportAlert).where(
                ReportAlert.workspace_id == record.workspace_id,
                ReportAlert.dedupe_key == dedupe_key,
            )
        ).first()
        if existing:
            continue
        alert = ReportAlert(
            workspace_id=record.workspace_id,
            rule_id=rule.id,
            source_id=source.id,
            record_id=record.id,
            level=rule.severity,
            title=f"{rule.name}：{record.title}",
            summary=f"已授权数据源「{source.name}」中的记录命中规则「{rule.name}」。",
            dedupe_key=dedupe_key,
        )
        try:
            with session.begin_nested():
                session.add(alert)
                session.flush()
        except IntegrityError as exc:
            already_created = session.exec(
                select(ReportAlert).where(
                    ReportAlert.workspace_id == record.workspace_id,
                    ReportAlert.dedupe_key == dedupe_key,
                )
            ).first()
            if already_created:
                continue
            raise HTTPException(status_code=409, detail="预警写入发生冲突，请重试") from exc
        _write_report_audit(
            session,
            actor_id=None,
            workspace_id=record.workspace_id,
            action="report.alert.rule_triggered",
            target_type="report_alert",
            target_id=alert.id,
            metadata={
                "rule_id": rule.id,
                "record_id": record.id,
                "source_id": source.id,
                "level": rule.severity,
            },
        )
        alerts.append(alert)
    return alerts


def _normalise_occurred_at(entry: ReportRecordInput) -> datetime:
    value = entry.occurred_at
    if value is None:
        return datetime.combine(entry.occurred_on, time.min, tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ingest_record(
    session: Session,
    *,
    source: ReportDataSource,
    entry: ReportRecordInput,
    batch_id: str,
    actor_id: str | None,
    channel: str,
) -> tuple[ReportRecord, bool, list[ReportAlert]]:
    existing = session.exec(
        select(ReportRecord).where(
            ReportRecord.source_id == source.id,
            ReportRecord.external_id == entry.external_id,
        )
    ).first()
    if existing:
        return existing, False, []

    record = ReportRecord(
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
    )
    try:
        with session.begin_nested():
            session.add(record)
            session.flush()
    except IntegrityError as exc:
        existing = session.exec(
            select(ReportRecord).where(
                ReportRecord.source_id == source.id,
                ReportRecord.external_id == entry.external_id,
            )
        ).first()
        if existing:
            return existing, False, []
        raise HTTPException(status_code=409, detail="业务记录写入发生冲突，请重试") from exc
    alerts = _evaluate_rules_for_record(session, record=record, source=source)
    _write_report_audit(
        session,
        actor_id=actor_id,
        workspace_id=source.workspace_id,
        action="report.record.ingested",
        target_type="report_record",
        target_id=record.id,
        metadata={
            "source_id": source.id,
            "external_id": record.external_id,
            "record_type": record.record_type,
            "ingest_batch_id": batch_id,
            "channel": channel,
            "triggered_alert_count": len(alerts),
        },
    )
    return record, True, alerts


# ---------------------------------------------------------------------------
# 仪表盘
# ---------------------------------------------------------------------------


@router.get("/dashboard")
def report_dashboard(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    workspace_id = context.workspace.id
    if _ensure_report_bootstrap(session, workspace_id, context.user.id):
        session.commit()

    sources = session.exec(
        select(ReportDataSource).where(ReportDataSource.workspace_id == workspace_id)
    ).all()
    alerts = session.exec(
        select(ReportAlert).where(ReportAlert.workspace_id == workspace_id)
    ).all()
    reports = session.exec(
        select(ReportDailyReport).where(ReportDailyReport.workspace_id == workspace_id)
    ).all()
    weekly_reports = session.exec(
        select(ReportWeeklyReport).where(ReportWeeklyReport.workspace_id == workspace_id)
    ).all()
    knowledge_bases = session.exec(
        select(KnowledgeBase).where(KnowledgeBase.workspace_id == workspace_id)
    ).all()
    return {
        "source_count": len(sources),
        "data_source_count": len(sources),
        "active_alert_count": sum(alert.status == "open" for alert in alerts),
        "alert_count": len(alerts),
        "report_count": len(reports),
        "daily_report_count": len(reports),
        "weekly_report_count": len(weekly_reports),
        "knowledge_base_count": len(knowledge_bases),
        "external_connection_status": "not_probed",
        "summary_engine": "deterministic_authorized_data",
    }


# ---------------------------------------------------------------------------
# 数据源配置和入站业务记录
# ---------------------------------------------------------------------------


def _ingest_url(request: Request, source_id: str) -> str:
    return str(request.base_url).rstrip("/") + f"/api/v1/report/ingest/{source_id}"


@router.get("/data-sources")
def list_report_data_sources(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    sources = session.exec(
        select(ReportDataSource)
        .where(ReportDataSource.workspace_id == context.workspace.id)
        .order_by(ReportDataSource.created_at.desc())
    ).all()
    records = session.exec(
        select(ReportRecord).where(ReportRecord.workspace_id == context.workspace.id)
    ).all()
    counts = Counter(record.source_id for record in records)
    latest: dict[str, datetime] = {}
    for record in records:
        if record.source_id not in latest or record.created_at > latest[record.source_id]:
            latest[record.source_id] = record.created_at
    visible = [
        _source_data(source, record_count=counts.get(source.id, 0), last_sync_at=latest.get(source.id))
        for source in sources
    ]
    return {"data_sources": visible, "sources": visible, "items": visible}


@router.post("/data-sources", status_code=status.HTTP_201_CREATED)
def create_report_data_source(
    payload: DataSourceCreateRequest,
    request: Request,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_workspace_manager(context)
    source_type = _normalise_source_type(payload.source_type)
    connection_mode = _normalise_connection_mode(payload.connection_mode)
    endpoint_url = _safe_endpoint_url(payload.endpoint_url)
    access_scope = _safe_authorization_reference(payload.access_scope)
    authorization_reference = _safe_authorization_reference(payload.authorization_reference)
    reference = authorization_reference or access_scope
    ingest_token = _new_ingest_token() if connection_mode in {"api", "webhook"} else None
    source = ReportDataSource(
        workspace_id=context.workspace.id,
        name=payload.name,
        source_type=source_type,
        connection_mode=connection_mode,
        endpoint_url=endpoint_url,
        authorization_reference=reference,
        ingest_token_hash=_token_hash(ingest_token) if ingest_token else "",
        ingest_token_last_rotated_at=now_utc() if ingest_token else None,
        created_by=context.user.id,
    )
    session.add(source)
    session.flush()
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.data_source.created",
        target_type="report_data_source",
        target_id=source.id,
        metadata={
            "source_type": source.source_type,
            "connection_mode": source.connection_mode,
            "ingest_token_issued": bool(ingest_token),
        },
    )
    session.commit()
    response: dict[str, Any] = {"data_source": _source_data(source)}
    if ingest_token:
        response.update({"ingest_url": _ingest_url(request, source.id), "ingest_token": ingest_token})
    return response


@router.patch("/data-sources/{source_id}")
def update_report_data_source(
    source_id: str,
    payload: DataSourceUpdateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = _source_or_404(session, context.workspace.id, source_id)
    _require_workspace_manager(context)
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
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.data_source.updated",
        target_type="report_data_source",
        target_id=source.id,
        metadata={"enabled": source.enabled},
    )
    session.commit()
    return {"data_source": _source_data(source)}


@router.post("/data-sources/{source_id}/rotate-ingest-token")
def rotate_report_ingest_token(
    source_id: str,
    request: Request,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = _source_or_404(session, context.workspace.id, source_id)
    _require_workspace_manager(context)
    if source.connection_mode not in {"api", "webhook"}:
        raise HTTPException(status_code=409, detail="文件导入数据源不使用入站令牌")
    ingest_token = _new_ingest_token()
    source.ingest_token_hash = _token_hash(ingest_token)
    source.ingest_token_last_rotated_at = now_utc()
    source.updated_at = now_utc()
    session.add(source)
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.data_source.ingest_token_rotated",
        target_type="report_data_source",
        target_id=source.id,
        metadata={"connection_mode": source.connection_mode},
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
    source: ReportDataSource,
    entries: list[ReportRecordInput],
    actor_id: str | None,
    channel: str,
) -> tuple[list[ReportRecord], list[bool], int, list[ReportAlert], str]:
    if not source.enabled:
        raise HTTPException(status_code=409, detail="该业务数据源已停用")
    batch_id = new_id()
    records: list[ReportRecord] = []
    created_flags: list[bool] = []
    alerts: list[ReportAlert] = []
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
def submit_authenticated_report_record(
    source_id: str,
    payload: ReportRecordInput,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = _source_or_404(session, context.workspace.id, source_id)
    _require_workspace_manager(context)
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
def submit_authenticated_report_record_batch(
    source_id: str,
    payload: ReportRecordBatchRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = _source_or_404(session, context.workspace.id, source_id)
    _require_workspace_manager(context)
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


@router.post("/ingest/{source_id}", status_code=status.HTTP_201_CREATED, name="report_ingest_record")
def ingest_authorised_report_record(
    source_id: str,
    payload: ReportRecordInput,
    ingest_token: str | None = Header(default=None, alias="X-Report-Ingest-Token"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = session.get(ReportDataSource, source_id)
    if not source:
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
def ingest_authorised_report_record_batch(
    source_id: str,
    payload: ReportRecordBatchRequest,
    ingest_token: str | None = Header(default=None, alias="X-Report-Ingest-Token"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = session.get(ReportDataSource, source_id)
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
    return {
        "receipts": [
            {"external_id": entry.external_id, "created": created}
            for entry, created in zip(payload.records, created_flags, strict=True)
        ],
        "created_count": created_count,
        "ingest_batch_id": batch_id,
    }


@router.get("/records")
def list_report_records(
    limit: int = Query(100, ge=1, le=500),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    records = session.exec(
        select(ReportRecord)
        .where(ReportRecord.workspace_id == context.workspace.id)
        .order_by(ReportRecord.occurred_at.desc())
        .limit(limit)
    ).all()
    visible = [_record_data(record) for record in records]
    return {"records": visible, "items": visible}


# ---------------------------------------------------------------------------
# 知识库管理
# ---------------------------------------------------------------------------


@router.get("/knowledge-bases")
def list_knowledge_bases(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    knowledge_bases = session.exec(
        select(KnowledgeBase)
        .where(KnowledgeBase.workspace_id == context.workspace.id)
        .order_by(KnowledgeBase.created_at.desc())
    ).all()
    return {"knowledge_bases": [_knowledge_base_data(kb) for kb in knowledge_bases], "items": [_knowledge_base_data(kb) for kb in knowledge_bases]}


@router.post("/knowledge-bases", status_code=status.HTTP_201_CREATED)
def create_knowledge_base(
    payload: KnowledgeBaseCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_member_write(context)
    kb = KnowledgeBase(
        workspace_id=context.workspace.id,
        title=payload.title,
        description=payload.description,
        content=payload.content,
        created_by=context.user.id,
    )
    session.add(kb)
    session.flush()
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.knowledge_base.created",
        target_type="knowledge_base",
        target_id=kb.id,
    )
    session.commit()
    return {"knowledge_base": _knowledge_base_data(kb)}


@router.post("/knowledge-bases/upload", status_code=status.HTTP_201_CREATED)
async def upload_knowledge_base_file(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    description: str = Form(default=""),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_member_write(context)
    content = await file.read()
    text_content = content.decode("utf-8", errors="ignore") if file.content_type and file.content_type.startswith("text/") else ""
    kb = KnowledgeBase(
        workspace_id=context.workspace.id,
        title=title or file.filename,
        description=description,
        content=text_content,
        file_name=file.filename,
        file_type=file.content_type or "application/octet-stream",
        file_size=len(content),
        created_by=context.user.id,
    )
    session.add(kb)
    session.flush()
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.knowledge_base.uploaded",
        target_type="knowledge_base",
        target_id=kb.id,
        metadata={"file_name": file.filename, "file_type": file.content_type, "file_size": len(content)},
    )
    session.commit()
    return {"knowledge_base": _knowledge_base_data(kb)}


@router.patch("/knowledge-bases/{kb_id}")
def update_knowledge_base(
    kb_id: str,
    payload: KnowledgeBaseUpdateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    kb = _knowledge_base_or_404(session, context.workspace.id, kb_id)
    _require_member_write(context)
    if payload.title is not None:
        kb.title = payload.title
    if payload.description is not None:
        kb.description = payload.description
    if payload.content is not None:
        kb.content = payload.content
    kb.updated_at = now_utc()
    session.add(kb)
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.knowledge_base.updated",
        target_type="knowledge_base",
        target_id=kb.id,
    )
    session.commit()
    return {"knowledge_base": _knowledge_base_data(kb)}


@router.delete("/knowledge-bases/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge_base(
    kb_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> None:
    kb = _knowledge_base_or_404(session, context.workspace.id, kb_id)
    _require_workspace_manager(context)
    session.delete(kb)
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.knowledge_base.deleted",
        target_type="knowledge_base",
        target_id=kb.id,
    )
    session.commit()


# ---------------------------------------------------------------------------
# 规则、预警和确定性生产日报
# ---------------------------------------------------------------------------


@router.get("/alert-rules")
def list_report_alert_rules(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if _ensure_report_bootstrap(session, context.workspace.id, context.user.id):
        session.commit()
    rules = session.exec(
        select(ReportAlertRule)
        .where(ReportAlertRule.workspace_id == context.workspace.id)
        .order_by(ReportAlertRule.created_at)
    ).all()
    visible = [_rule_data(rule) for rule in rules]
    return {"alert_rules": visible, "items": visible}


@router.post("/alert-rules", status_code=status.HTTP_201_CREATED)
def create_report_alert_rule(
    payload: AlertRuleCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_workspace_manager(context)
    keywords = [keyword.strip() for keyword in payload.keywords if keyword.strip()]
    if not keywords:
        raise HTTPException(status_code=422, detail="预警规则至少需要一个有效关键字")
    rule = ReportAlertRule(
        workspace_id=context.workspace.id,
        name=payload.name,
        record_type=payload.record_type,
        keywords_json=json.dumps(keywords, ensure_ascii=False),
        severity=payload.severity,
        created_by=context.user.id,
    )
    session.add(rule)
    session.flush()
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.alert_rule.created",
        target_type="report_alert_rule",
        target_id=rule.id,
        metadata={"severity": rule.severity},
    )
    session.commit()
    return {"alert_rule": _rule_data(rule)}


@router.patch("/alert-rules/{rule_id}")
def update_report_alert_rule(
    rule_id: str,
    payload: AlertRuleUpdateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    rule = _rule_or_404(session, context.workspace.id, rule_id)
    _require_workspace_manager(context)
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
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.alert_rule.updated",
        target_type="report_alert_rule",
        target_id=rule.id,
        metadata={"enabled": rule.enabled, "severity": rule.severity},
    )
    session.commit()
    return {"alert_rule": _rule_data(rule)}


@router.get("/alerts")
def list_report_alerts(
    include_resolved: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    statement = (
        select(ReportAlert)
        .where(ReportAlert.workspace_id == context.workspace.id)
        .order_by(ReportAlert.created_at.desc())
        .limit(limit)
    )
    alerts = session.exec(statement).all()
    visible = [
        _alert_data(alert)
        for alert in alerts
        if include_resolved or alert.status != "resolved"
    ]
    return {"alerts": visible, "items": visible}


@router.post("/alerts", status_code=status.HTTP_201_CREATED)
def create_manual_report_alert(
    payload: ManualAlertCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_workspace_manager(context)
    source: ReportDataSource | None = None
    record: ReportRecord | None = None
    if payload.source_id:
        source = _source_or_404(session, context.workspace.id, payload.source_id)
    if payload.record_id:
        record = _record_or_404(session, context.workspace.id, payload.record_id)
        if source and record.source_id != source.id:
            raise HTTPException(status_code=422, detail="业务记录不属于指定的数据源")
        source = _source_or_404(session, context.workspace.id, record.source_id)
    alert = ReportAlert(
        workspace_id=context.workspace.id,
        source_id=source.id if source else None,
        record_id=record.id if record else None,
        level=payload.severity,
        title=payload.title,
        summary=payload.summary,
        dedupe_key=f"manual:{new_id()}",
    )
    session.add(alert)
    session.flush()
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.alert.created",
        target_type="report_alert",
        target_id=alert.id,
        metadata={"source_id": alert.source_id, "record_id": alert.record_id, "level": alert.level},
    )
    session.commit()
    return {"alert": _alert_data(alert)}


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_report_alert(
    alert_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    alert = _alert_or_404(session, context.workspace.id, alert_id)
    _require_member_write(context)
    if alert.status == "resolved":
        raise HTTPException(status_code=409, detail="已解决的预警不能重复确认")
    if alert.status == "open":
        alert.status = "acknowledged"
        alert.acknowledged_by = context.user.id
        alert.acknowledged_at = now_utc()
        alert.updated_at = now_utc()
        session.add(alert)
        _write_report_audit(
            session,
            actor_id=context.user.id,
            workspace_id=context.workspace.id,
            action="report.alert.acknowledged",
            target_type="report_alert",
            target_id=alert.id,
        )
        session.commit()
    return {"alert": _alert_data(alert)}


@router.post("/alerts/{alert_id}/resolve")
def resolve_report_alert(
    alert_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    alert = _alert_or_404(session, context.workspace.id, alert_id)
    _require_workspace_manager(context)
    if alert.status != "resolved":
        alert.status = "resolved"
        alert.resolved_by = context.user.id
        alert.resolved_at = now_utc()
        alert.updated_at = now_utc()
        session.add(alert)
        _write_report_audit(
            session,
            actor_id=context.user.id,
            workspace_id=context.workspace.id,
            action="report.alert.resolved",
            target_type="report_alert",
            target_id=alert.id,
        )
        session.commit()
    return {"alert": _alert_data(alert)}


def _generate_daily_report(
    session: Session,
    *,
    workspace_id: str,
    report_date: date,
    generated_by: str,
) -> ReportDailyReport:
    records = session.exec(
        select(ReportRecord).where(
            ReportRecord.workspace_id == workspace_id,
            ReportRecord.occurred_on == report_date,
        )
    ).all()
    alerts = session.exec(
        select(ReportAlert).where(
            ReportAlert.workspace_id == workspace_id,
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
            "occurred_on": report_date.isoformat(),
        },
    }
    type_summary = "、".join(f"{name} {count} 条" for name, count in sorted(record_types.items())) or "无"
    alert_summary = "、".join(f"{name} {count} 条" for name, count in sorted(alert_levels.items())) or "无"
    summary = (
        f"{report_date.isoformat()} 生产日报：仅汇总已授权且可追溯的数据。"
        f"当日记录 {len(records)} 条（{type_summary}）；当前未闭环预警 {len(open_alerts)} 条（{alert_summary}）。"
        "该日报由规则引擎生成，发布前需人工复核。"
    )
    report = session.exec(
        select(ReportDailyReport).where(
            ReportDailyReport.workspace_id == workspace_id,
            ReportDailyReport.report_date == report_date,
        )
    ).first()
    if not report:
        report = ReportDailyReport(
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


def _generate_weekly_report(
    session: Session,
    *,
    workspace_id: str,
    week_start_date: date,
    week_end_date: date,
    title: str,
    generated_by: str,
) -> ReportWeeklyReport:
    records = session.exec(
        select(ReportRecord).where(
            ReportRecord.workspace_id == workspace_id,
            ReportRecord.occurred_on >= week_start_date,
            ReportRecord.occurred_on <= week_end_date,
        )
    ).all()
    alerts = session.exec(
        select(ReportAlert).where(
            ReportAlert.workspace_id == workspace_id,
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
            "week_start_date": week_start_date.isoformat(),
            "week_end_date": week_end_date.isoformat(),
        },
    }
    type_summary = "、".join(f"{name} {count} 条" for name, count in sorted(record_types.items())) or "无"
    alert_summary = "、".join(f"{name} {count} 条" for name, count in sorted(alert_levels.items())) or "无"
    summary = (
        f"{week_start_date.isoformat()} 至 {week_end_date.isoformat()} 周报：仅汇总已授权且可追溯的数据。"
        f"本周记录 {len(records)} 条（{type_summary}）；当前未闭环预警 {len(open_alerts)} 条（{alert_summary}）。"
        "该周报由规则引擎生成，发布前需人工复核。"
    )
    report = session.exec(
        select(ReportWeeklyReport).where(
            ReportWeeklyReport.workspace_id == workspace_id,
            ReportWeeklyReport.week_start_date == week_start_date,
        )
    ).first()
    if not report:
        report = ReportWeeklyReport(
            workspace_id=workspace_id,
            week_start_date=week_start_date,
            week_end_date=week_end_date,
            title=title or f"{week_start_date.isoformat()} 周报",
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
def list_report_daily_reports(
    limit: int = Query(90, ge=1, le=365),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    reports = session.exec(
        select(ReportDailyReport)
        .where(ReportDailyReport.workspace_id == context.workspace.id)
        .order_by(ReportDailyReport.report_date.desc())
        .limit(limit)
    ).all()
    result = [_report_data(report) for report in reports]
    return {"daily_reports": result, "reports": result, "items": result}


@router.post("/daily-reports/generate")
@router.post("/daily-reports")
def generate_report_daily_report(
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
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.daily_report.generated",
        target_type="report_daily_report",
        target_id=report.id,
        metadata={"report_date": report.report_date.isoformat()},
    )
    session.commit()
    return {"daily_report": _report_data(report)}


@router.get("/weekly-reports")
def list_report_weekly_reports(
    limit: int = Query(52, ge=1, le=104),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    reports = session.exec(
        select(ReportWeeklyReport)
        .where(ReportWeeklyReport.workspace_id == context.workspace.id)
        .order_by(ReportWeeklyReport.week_start_date.desc())
        .limit(limit)
    ).all()
    result = [_weekly_report_data(report) for report in reports]
    return {"weekly_reports": result, "reports": result, "items": result}


@router.post("/weekly-reports/generate")
@router.post("/weekly-reports")
def generate_report_weekly_report(
    payload: WeeklyReportGenerateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_workspace_manager(context)
    report = _generate_weekly_report(
        session,
        workspace_id=context.workspace.id,
        week_start_date=payload.week_start_date,
        week_end_date=payload.week_end_date,
        title=payload.title,
        generated_by=context.user.id,
    )
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.weekly_report.generated",
        target_type="report_weekly_report",
        target_id=report.id,
        metadata={"week_start_date": report.week_start_date.isoformat(), "week_end_date": report.week_end_date.isoformat()},
    )
    session.commit()
    return {"weekly_report": _weekly_report_data(report)}


# ---------------------------------------------------------------------------
# 汇报智能体对话
# ---------------------------------------------------------------------------


def _deterministic_reply(
    session: Session,
    context: WorkspaceContext,
    question: str,
) -> tuple[str, list[dict[str, Any]]]:
    records = session.exec(
        select(ReportRecord)
        .where(ReportRecord.workspace_id == context.workspace.id)
        .order_by(ReportRecord.occurred_at.desc())
        .limit(200)
    ).all()
    alerts = session.exec(
        select(ReportAlert)
        .where(ReportAlert.workspace_id == context.workspace.id)
        .order_by(ReportAlert.created_at.desc())
        .limit(100)
    ).all()
    open_alerts = [alert for alert in alerts if alert.status == "open"]
    knowledge_bases = session.exec(
        select(KnowledgeBase)
        .where(KnowledgeBase.workspace_id == context.workspace.id)
        .order_by(KnowledgeBase.created_at.desc())
        .limit(50)
    ).all()

    type_counts = Counter(record.record_type for record in records)
    lines = [
        "这是基于已授权数据生成的确定性摘要；未调用外部模型，也未连接或抓取未授权系统。",
        f"当前可查询记录 {len(records)} 条，待处理预警 {len(open_alerts)} 条，知识库文档 {len(knowledge_bases)} 篇。",
    ]
    if type_counts:
        lines.append("记录分类：" + "、".join(f"{kind} {count} 条" for kind, count in sorted(type_counts.items())))
    if open_alerts:
        lines.append("优先关注：" + "；".join(alert.title for alert in open_alerts[:3]))
    if records:
        lines.append("最近记录：" + "；".join(record.title for record in records[:3]))
    if knowledge_bases:
        lines.append("知识库文档：" + "；".join(kb.title for kb in knowledge_bases[:3]))
    if not records and not knowledge_bases:
        lines.append("当前没有已授权且已接收的记录或知识库文档。请先完成数据源授权并提交业务记录，或上传知识库文档。")
    if question:
        lines.append("已记录本次查询，将仅用于当前用户的历史记录。")

    citations: list[dict[str, Any]] = [
        {"type": "record", "id": record.id, "record_type": record.record_type}
        for record in records[:5]
    ]
    citations.extend(
        {"type": "alert", "id": alert.id, "severity": alert.level}
        for alert in open_alerts[:5]
    )
    citations.extend(
        {"type": "knowledge_base", "id": kb.id, "title": kb.title}
        for kb in knowledge_bases[:3]
    )
    return "\n".join(lines), citations


@router.get("/messages")
def list_report_messages(
    limit: int = Query(100, ge=1, le=300),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    messages = session.exec(
        select(ReportAssistantMessage)
        .where(
            ReportAssistantMessage.workspace_id == context.workspace.id,
            ReportAssistantMessage.user_id == context.user.id,
        )
        .order_by(ReportAssistantMessage.created_at)
        .limit(limit)
    ).all()
    return {"messages": [_message_data(message) for message in messages], "items": [_message_data(message) for message in messages]}


@router.post("/chat")
def chat_with_report_assistant(
    payload: ChatRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_member_write(context)
    question = (payload.message or payload.query or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="请输入要查询的内容")
    reply, citations = _deterministic_reply(session, context, question)
    user_message = ReportAssistantMessage(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        role="user",
        content=question,
    )
    assistant_message = ReportAssistantMessage(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        role="assistant",
        content=reply,
        citations_json=json.dumps({"items": citations}, ensure_ascii=False),
    )
    session.add(user_message)
    session.add(assistant_message)
    session.flush()
    _write_report_audit(
        session,
        actor_id=context.user.id,
        workspace_id=context.workspace.id,
        action="report.assistant.queried",
        target_type="report_assistant",
        target_id="",
        metadata={"citation_count": len(citations)},
    )
    session.commit()
    return {
        "reply": reply,
        "message": _message_data(user_message),
        "assistant_message": _message_data(assistant_message),
        "engine": "deterministic_authorized_data",
        "external_model_called": False,
    }
