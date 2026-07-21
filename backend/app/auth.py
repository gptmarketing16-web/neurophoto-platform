from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal, get_db
from .models import User
from .services.idgen import new_id
from .settings import settings

password_hash = PasswordHash.recommended()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(value: str) -> str:
    if len(value) < 10:
        raise ValueError("Пароль должен содержать не менее 10 символов")
    return password_hash.hash(value)


def verify_password(value: str, hashed: str) -> bool:
    try:
        return password_hash.verify(value, hashed)
    except Exception:
        return False


def create_session_token(user: User) -> str:
    now = utcnow()
    payload = {
        "sub": user.id,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.session_ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm="HS256")


def decode_session_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=["HS256"])
        return str(payload.get("sub") or "") or None
    except jwt.PyJWTError:
        return None


def ensure_owner() -> None:
    email = settings.owner_email.strip().lower()
    if not email or not settings.owner_password:
        return
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            if user.role != "owner":
                user.role = "owner"
                db.commit()
            return
        user = User(
            id=new_id("usr"),
            email=email,
            display_name=settings.owner_name.strip() or "Владелец",
            password_hash=hash_password(settings.owner_password),
            role="owner",
            allowed_project_ids=[],
            is_active=True,
        )
        db.add(user)
        db.commit()


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    if not session_token:
        raise HTTPException(401, "Требуется вход")
    user_id = decode_session_token(session_token)
    if not user_id:
        raise HTTPException(401, "Сессия истекла")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Пользователь отключён")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_owner(user: CurrentUser) -> User:
    if user.role != "owner":
        raise HTTPException(403, "Доступно только владельцу")
    return user


def require_editor(user: CurrentUser) -> User:
    if user.role not in {"owner", "operator"}:
        raise HTTPException(403, "Недостаточно прав для изменения")
    return user


def can_access_project(user: User, project_id: str) -> bool:
    return user.role == "owner" or project_id in (user.allowed_project_ids or [])


def assert_project_access(user: User, project_id: str, *, write: bool = False, project_type: str | None = None) -> None:
    if not can_access_project(user, project_id):
        raise HTTPException(403, "Нет доступа к этому проекту")
    if write and user.role not in {"owner", "operator"}:
        raise HTTPException(403, "Проект доступен только для просмотра")
    if write and project_type == "agent" and user.role != "owner":
        raise HTTPException(403, "Проект AI-агента доступен менеджеру только для просмотра")
