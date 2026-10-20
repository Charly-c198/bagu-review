"""认证路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import User
from ..schemas import LoginRequest
from ..security import (
    clear_auth_cookies,
    create_session,
    extract_token,
    get_current_user,
    login_limiter,
    revoke_session,
    set_auth_cookies,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "local"
    login_limiter.check(ip)
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        login_limiter.record(ip, False)
        raise ApiError(401, "AUTH_INVALID", "用户名或口令错误")
    login_limiter.record(ip, True)
    token, csrf, _session = create_session(db, user)
    response = JSONResponse(
        ok(
            {
                "token": token,
                "csrf_token": csrf,
                "user": {"id": user.id, "username": user.username},
            }
        )
    )
    set_auth_cookies(response, token, csrf)
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    token, _ = extract_token(request)
    revoke_session(db, token)
    response = JSONResponse(ok(None, "已退出登录"))
    clear_auth_cookies(response)
    return response


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return ok({"id": user.id, "username": user.username})
