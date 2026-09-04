"""工作区内知识检索（RAG 召回层）：关键词 + 可选向量融合。

- 关键词召回：对查询提取 ASCII 词与中文单字/二元组合，在知识库文档、
  业务/汇报记录与附件提取文本里按命中打分排序，任何数据库可用。
- 向量召回（可选）：``EMBEDDING_PROVIDER`` 启用后，知识库文档切块向量化
  （本地 Ollama 的 qwen3-embedding 即可），查询向量做余弦融合加权；
  embedding 不可用时自动退回纯关键词，行为与历史版本一致。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from sqlmodel import Session, select

from core.embedding import chunk_text, cosine_similarity, embed_texts, embedding_enabled
from config import settings
from db.models import Attachment, BusinessRecord
from db.report_models import KnowledgeBase, KnowledgeChunk, ReportRecord

logger = logging.getLogger(__name__)

_TOKEN_LIMIT = 24
_SCAN_LIMIT = 200
_SNIPPET_WINDOW = 90
_VECTOR_WEIGHT = 6.0


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


def _chunk_scores(session: Session, workspace_id: str, query_vector: list[float], limit: int) -> list[dict[str, Any]]:
    """对当前工作区的知识块做余弦打分，返回按分数降序的 KB 命中。"""
    chunks = session.exec(
        select(KnowledgeChunk).where(KnowledgeChunk.workspace_id == workspace_id)
    ).all()
    kb_rows = session.exec(
        select(KnowledgeBase).where(KnowledgeBase.workspace_id == workspace_id)
    ).all()
    titles = {kb.id: kb.title for kb in kb_rows}
    scored: list[tuple[float, str, str, str]] = []
    for chunk in chunks:
        try:
            vector = json.loads(chunk.embedding_json or "[]")
        except ValueError:
            continue
        score = cosine_similarity(query_vector, vector)
        if score <= 0.05:
            continue
        title = titles.get(chunk.kb_id, "知识库")
        snippet = chunk.content[:_SNIPPET_WINDOW]
        scored.append((score, chunk.kb_id, title, snippet))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {"source": "knowledge_base", "id": kb_id, "title": title, "snippet": snippet, "score": score * _VECTOR_WEIGHT}
        for score, kb_id, title, snippet in scored[:limit]
    ]


async def retrieve_knowledge_smart(
    session: Session,
    workspace_id: str,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """关键词召回 + 可选向量融合：embedding 不可用时行为与纯关键词一致。"""
    keyword_hits = retrieve_knowledge(session, workspace_id, query, limit=limit)
    if not embedding_enabled():
        return keyword_hits
    try:
        vectors = await embed_texts([query])
    except Exception:  # noqa: BLE001 - 检索是同步路径的安全网
        vectors = None
    if not vectors:
        return keyword_hits
    vector_hits = _chunk_scores(session, workspace_id, vectors[0], limit=limit)
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for item in keyword_hits + vector_hits:
        key = (item["source"], item["id"])
        if key in merged:
            merged[key]["score"] = max(merged[key]["score"], item["score"])
        else:
            merged[key] = item
    results = sorted(merged.values(), key=lambda item: item["score"], reverse=True)
    return results[:limit]


def retrieve_knowledge_smart_sync(
    session: Session,
    workspace_id: str,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """同步路由使用的包装：线程池中执行，无运行中的事件循环。"""
    try:
        return asyncio.run(retrieve_knowledge_smart(session, workspace_id, query, limit))
    except Exception:  # noqa: BLE001
        logger.warning("knowledge retrieval: 向量融合失败，退回关键词召回", exc_info=True)
        return retrieve_knowledge(session, workspace_id, query, limit)


async def reindex_knowledge_base(session: Session, workspace_id: str, kb: KnowledgeBase) -> bool:
    """对单个知识库文档重新切块向量化；embedding 不可用返回 False。"""
    if not embedding_enabled():
        return False
    chunks = chunk_text(kb.content or kb.title)
    if not chunks:
        return False
    vectors = await embed_texts(chunks)
    if not vectors:
        return False
    for old in session.exec(
        select(KnowledgeChunk).where(KnowledgeChunk.kb_id == kb.id)
    ).all():
        session.delete(old)
    for index, (content, vector) in enumerate(zip(chunks, vectors)):
        session.add(
            KnowledgeChunk(
                workspace_id=workspace_id,
                kb_id=kb.id,
                chunk_index=index,
                content=content[:4000],
                embedding_json=json.dumps(vector),
                model_name=settings.embedding_model,
                kb_updated_at=kb.updated_at,
            )
        )
    session.commit()
    return True
