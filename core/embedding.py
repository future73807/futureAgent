"""可插拔的文本向量层（embedding）。

- ``EMBEDDING_PROVIDER=off``（默认）时完全禁用，检索退回关键词召回。
- ``ollama``：调用本地 Ollama 的 OpenAI 兼容 ``/v1/embeddings``，
  推荐 ``qwen3-embedding``（``ollama pull qwen3-embedding``）。
- ``openai``：LiteLLM 代理或 OpenAI 兼容服务。

任何失败（未配置/网络/维度异常）都返回 ``None``，由调用方降级；
向量以 JSON 数组形式随 ``KnowledgeChunk`` 持久化，检索时在进程内
做余弦计算，不依赖 pgvector —— 因此 SQLite 开发环境同样可用。
"""
from __future__ import annotations

import logging
import math

import httpx

from config import settings

logger = logging.getLogger(__name__)

_EMBED_TIMEOUT_SECONDS = 30.0
_MAX_BATCH_TEXTS = 32
_MAX_TEXT_CHARS = 4000


def embedding_enabled() -> bool:
    provider = settings.embedding_provider.strip().lower()
    return provider in {"ollama", "openai"} and bool(settings.embedding_model.strip())


def chunk_text(content: str, *, chunk_chars: int = 800, overlap: int = 100, max_chunks: int = 20) -> list[str]:
    """把长文档切成带重叠的块；超长文档截断到 ``max_chunks`` 块。"""
    cleaned = (content or "").strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    length = len(cleaned)
    while start < length and len(chunks) < max_chunks:
        end = min(start + chunk_chars, length)
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = end - overlap if overlap < chunk_chars else end
    return chunks


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    return _cosine(a, b)


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """批量向量化；未启用或失败返回 None（调用方降级为关键词召回）。"""
    if not embedding_enabled() or not texts:
        return None
    cleaned = [t[:_MAX_TEXT_CHARS] for t in texts]
    provider = settings.embedding_provider.strip().lower()
    try:
        if provider == "ollama":
            base = settings.ollama_base_url.strip().rstrip("/")
            root = base[:-3] if base.endswith("/v1") else base
            url = f"{root}/v1/embeddings"
        else:
            url = f"{settings.openai_base_url.rstrip('/')}/embeddings"
        async with httpx.AsyncClient(timeout=_EMBED_TIMEOUT_SECONDS, trust_env=False) as client:
            response = await client.post(
                url,
                json={"model": settings.embedding_model, "input": cleaned},
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or len(data) != len(cleaned):
            logger.warning("embedding: 返回条目数不匹配（期望 %s）", len(cleaned))
            return None
        vectors = []
        for item in sorted(data, key=lambda entry: entry.get("index", 0)):
            vector = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vector, list) or not vector:
                return None
            vectors.append([float(value) for value in vector])
        if vectors and any(len(v) != len(vectors[0]) for v in vectors):
            logger.warning("embedding: 返回向量维度不一致")
            return None
        return vectors
    except Exception:  # noqa: BLE001 - 向量化是增强能力，失败一律降级
        logger.warning("embedding: 向量化失败，本次使用关键词召回", exc_info=True)
        return None
