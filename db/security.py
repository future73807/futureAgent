"""密码哈希与 JWT 会话令牌。"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
import jwt
from fastapi import HTTPException, status

from config import settings


def hash_password(password: str) -> str:
    _validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _validate_password(password: str) -> None:
    if len(password) < 10:
        raise HTTPException(status_code=422, detail="密码至少需要 10 个字符")
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=422, detail="密码不能超过 72 个字节")


def create_token(*, user_id: str, token_type: str, expires_delta: timedelta, session_id: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": session_id or uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或已过期的登录令牌",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if payload.get("type") != expected_type or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="令牌类型不正确")
    return payload
