"""工作区内轻量知识检索（RAG 的召回层）。

当前实现是与数据库无关的关键词召回：对查询提取 ASCII 词与中文单字/二元
组合，在知识库文档、业务/汇报记录与附件提取文本里按命中打分排序。它不依
赖任何外部服务，可在 SQLite 与 PostgreSQL 上运行。

升级路径：compose 环境已内置 pgvector 镜像；接入 embedding 供应商后，可
以在本模块内替换为向量召回（分块入库 + 余弦检索），返回结构保持不变，上
层 prompt 组装无需改动。
"""
from __future__ import annotations

import re
from typing import Any

from sqlmodel import Session, select

from db.models import Attachment, BusinessRecord
from db.report_models import KnowledgeBase, ReportRecord

_TOKEN_LIMIT = 24
_SCAN_LIMIT = 200
_SNIPPET_WINDOW = 90


def keyword_tokens(query: str) -> list[str]:
    """查询分词：ASCII 词（长度≥2）+ 中文字符与相邻二元组合。"""
    cleaned = (query or "").strip()
    if not cleaned:
        return []
    ordered: list[str] = []
    seen: set[str] = set()

    def push(token: str) -> None:
        if token and token not in seen:
            seen.add(token)
            ordered.append(token)

    for word in re.findall(r"[a-zA-Z0-9_]+", cleaned):
        if len(word) >= 2:
            push(word.lower())
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", cleaned))
    for char in cjk:
        push(char)
    for pair in zip(cjk, cjk[1:]):
        push("".join(pair))
    return ordered[:_TOKEN_LIMIT]


def _score_text(text: str, tokens: list[str]) -> int:
    if not text:
        return 0
    lowered = text.lower()
    score = 0
    for token in tokens:
        if token in lowered:
            score += 2 if len(token) >= 2 else 1
    return score


def _snippet(text: str, tokens: list[str]) -> str:
    cleaned = (text or "").replace("\n", " ").strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    anchor = -1
    for token in tokens:
        anchor = lowered.find(token)
        if anchor >= 0:
            break
    if anchor < 0:
        return cleaned[:_SNIPPET_WINDOW]
    start = max(0, anchor - 30)
    return ("…" if start else "") + cleaned[start : start + _SNIPPET_WINDOW]


def _collect_candidates(session: Session, workspace_id: str) -> list[tuple[str, str, str, str, Any]]:
    """返回 (source_type, id, title, content, model_obj) 候选集合。"""
    candidates: list[tuple[str, str, str, str, Any]] = []
    for kb in (
        session.exec(
            select(KnowledgeBase)
            .where(KnowledgeBase.workspace_id == workspace_id)
            .order_by(KnowledgeBase.created_at.desc())
            .limit(_SCAN_LIMIT)
        ).all()
    ):
        candidates.append(("knowledge_base", kb.id, kb.title, f"{kb.title}\n{kb.content}", kb))
    for record in (
        session.exec(
            select(BusinessRecord)
            .where(BusinessRecord.workspace_id == workspace_id)
            .order_by(BusinessRecord.occurred_at.desc())
            .limit(_SCAN_LIMIT)
        ).all()
    ):
        candidates.append(("business_record", record.id, record.title, f"{record.title}\n{record.content}", record))
    for record in (
        session.exec(
            select(ReportRecord)
            .where(ReportRecord.workspace_id == workspace_id)
            .order_by(ReportRecord.occurred_at.desc())
            .limit(_SCAN_LIMIT)
        ).all()
    ):
        candidates.append(("report_record", record.id, record.title, f"{record.title}\n{record.content}", record))
    for attachment in (
        session.exec(
            select(Attachment)
            .where(Attachment.workspace_id == workspace_id)
            .order_by(Attachment.created_at.desc())
            .limit(_SCAN_LIMIT)
        ).all()
    ):
        if attachment.extracted_text:
            candidates.append(
                ("attachment", attachment.id, attachment.original_name, f"{attachment.original_name}\n{attachment.extracted_text}", attachment)
            )
    return candidates


def retrieve_knowledge(
    session: Session,
    workspace_id: str,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """按关键词命中分对工作区内资料做召回，返回带片段与得分的列表。"""
    tokens = keyword_tokens(query)
    if not tokens:
        return []
    scored: list[tuple[int, str, str, str, str]] = []
    for source_type, identifier, title, content, _ in _collect_candidates(session, workspace_id):
        score = _score_text(title, tokens) * 2 + _score_text(content, tokens)
        # 阈值 2：单个中文字的偶然命中不构成相关性
        if score >= 2:
            scored.append((score, source_type, identifier, title, _snippet(content, tokens)))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "source": source_type,
            "id": identifier,
            "title": title,
            "snippet": snippet,
            "score": score,
        }
        for score, source_type, identifier, title, snippet in scored[:limit]
    ]
