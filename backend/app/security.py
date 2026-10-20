"""口令哈希、服务端会话、登录限流与认证依赖。"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from datetime import timedelta

import bcrypt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import (
    APP_PASSWORD,
    APP_USERNAME,
    CSRF_COOKIE,
    SESSION_COOKIE,
    TOKEN_TTL_MINUTES,
)
from .database import get_db
from .errors import ApiError
from .models import AuthSession, User
from .utils.timeutil import utcnow


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User) -> tuple[str, str, AuthSession]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    session = AuthSession(
        user_id=user.id,
        token_hash=_token_hash(token),
        expires_at=utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return token, csrf, session


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == _token_hash(token))
    )
    if session and session.revoked_at is None:
        session.revoked_at = utcnow()
        db.commit()


def extract_token(request: Request) -> tuple[str | None, bool]:
    """返回 (token, 是否来自 cookie)。"""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token:
            return token, False
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return cookie, True
    return None, False


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token, from_cookie = extract_token(request)
    if not token:
        raise ApiError(401, "AUTH_REQUIRED", "请先登录")

    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == _token_hash(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )
    if not session:
        raise ApiError(401, "AUTH_REQUIRED", "登录已失效，请重新登录")
    user = db.get(User, session.user_id)
    if not user:
        raise ApiError(401, "AUTH_REQUIRED", "用户不存在")

    if from_cookie and request.method not in ("GET", "HEAD", "OPTIONS"):
        csrf_header = request.headers.get("X-CSRF-Token", "")
        csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
        if not csrf_cookie or not secrets.compare_digest(csrf_header, csrf_cookie):
            raise ApiError(403, "AUTH_REQUIRED", "CSRF 校验失败，请重新登录")

    request.state.user = user
    request.state.auth_token = token
    return user


def ensure_default_user() -> None:
    from .database import SessionLocal

    db = SessionLocal()
    try:
        if db.scalar(select(User.id).limit(1)) is None:
            db.add(
                User(
                    username=APP_USERNAME,
                    password_hash=hash_password(APP_PASSWORD),
                )
            )
            db.commit()
    finally:
        db.close()


class LoginLimiter:
    """进程内登录限流：5 次/分钟/IP，连续失败 10 次锁定 15 分钟。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempts: dict[str, list[float]] = {}
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def check(self, ip: str) -> None:
        now = time.time()
        with self._lock:
            locked = self._locked_until.get(ip, 0)
            if locked > now:
                raise ApiError(
                    429,
                    "RATE_LIMITED",
                    f"失败次数过多，请在 {int((locked - now) // 60) + 1} 分钟后重试",
                )
            attempts = [t for t in self._attempts.get(ip, []) if now - t < 60]
            self._attempts[ip] = attempts
            if len(attempts) >= 5:
                raise ApiError(429, "RATE_LIMITED", "登录过于频繁，请稍后再试")

    def record(self, ip: str, success: bool) -> None:
        now = time.time()
        with self._lock:
            self._attempts.setdefault(ip, []).append(now)
            if success:
                self._failures[ip] = 0
                self._locked_until.pop(ip, None)
            else:
                failures = self._failures.get(ip, 0) + 1
                self._failures[ip] = failures
                if failures >= 10:
                    self._locked_until[ip] = now + 15 * 60
                    self._failures[ip] = 0


login_limiter = LoginLimiter()


def set_auth_cookies(response, token: str, csrf: str) -> None:
    max_age = TOKEN_TTL_MINUTES * 60
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=max_age,
        httponly=False,
        samesite="lax",
        secure=False,
        path="/",
    )


def clear_auth_cookies(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
