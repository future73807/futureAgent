"""进程内滑动窗口限流器（认证接口防爆破）。

- 单进程部署足够；多副本部署应在网关（nginx limit_req）做等效限制。
- 中间件只保护登录/注册/刷新三类端点；limit<=0 时完全放行，便于测试与关闭。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from config import settings

_auth_events: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def hit_auth_limit(key: str) -> bool:
    """记录一次认证尝试；超过阈值返回 False。"""
    limit = max(0, settings.auth_rate_limit_per_minute)
    if limit <= 0:
        return True
    now = time.monotonic()
    window = 60.0
    with _lock:
        bucket = _auth_events[key]
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def client_ip(request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


AUTH_PROTECTED_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
}


async def rate_limit_auth_middleware(request, call_next):
    if request.method == "POST" and request.url.path in AUTH_PROTECTED_PATHS:
        if not hit_auth_limit(f"auth:{client_ip(request)}"):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=429,
                content={"detail": "尝试过于频繁，请稍后再试。"},
                headers={"Retry-After": "60"},
            )
    return await call_next(request)
