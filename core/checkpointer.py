"""LangGraph 会话记忆检查点（仅 PostgreSQL 部署启用）。

- SQLite/开发环境返回 ``None``，Agent 行为与既有完全一致。
- Postgres 部署时构建 ``AsyncPostgresSaver``（连接池由本模块持有，
  ``aclose_checkpointer`` 在应用关闭时释放）；任何初始化失败都降级为
  ``None`` 并记录日志，绝不阻塞启动。
"""
from __future__ import annotations

import asyncio
import logging
import time

from config import settings

logger = logging.getLogger(__name__)

_checkpointer = None
_initial_lock = asyncio.Lock()
_closed = False
# 初始化失败后的冷却期：避免每个 governed run 都等待一次必然失败的网络连接。
_RETRY_COOLDOWN_SECONDS = 120.0
_disabled_until = 0.0


async def get_checkpointer():
    """返回进程级 AsyncPostgresSaver 单例；不可用时返回 None。"""
    global _checkpointer, _disabled_until
    if _checkpointer is not None:
        return _checkpointer
    if _closed or time.monotonic() < _disabled_until:
        return None
    if not settings.checkpoint_conn_str.startswith("postgresql"):
        return None
    async with _initial_lock:
        if _checkpointer is not None or _closed or time.monotonic() < _disabled_until:
            return _checkpointer
        try:
            from psycopg_pool import AsyncConnectionPool
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            pool = AsyncConnectionPool(
                conninfo=settings.checkpoint_conn_str,
                max_size=5,
                open=False,
                check=False,
            )
            await pool.open(wait=False, timeout=10)
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            _checkpointer = saver
            logger.info("checkpointer: LangGraph 会话记忆已启用（PostgreSQL）")
        except Exception:  # noqa: BLE001 - 记忆是增强能力，失败不阻塞启动
            _disabled_until = time.monotonic() + _RETRY_COOLDOWN_SECONDS
            logger.warning("checkpointer: 初始化失败，冷却期内降级为无跨请求记忆", exc_info=True)
            _checkpointer = None
    return _checkpointer


async def aclose_checkpointer() -> None:
    """应用关闭时释放连接池。"""
    global _checkpointer, _closed
    _closed = True
    if _checkpointer is None:
        return
    saver = _checkpointer
    _checkpointer = None
    pool = getattr(saver, "pool", None) or getattr(saver, "conn", None)
    try:
        if pool is not None and hasattr(pool, "close"):
            await pool.close()
    except Exception:  # noqa: BLE001
        logger.debug("checkpointer: 关闭连接池失败", exc_info=True)
