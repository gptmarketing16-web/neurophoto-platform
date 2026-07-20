from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import hash_password, require_owner
from ..db import get_db
from ..models import Project, User
from ..services.idgen import new_id

router = APIRouter(prefix="/api/admin/users", tags=["users"], dependencies=[Depends(require_owner)])


class UserCreate(BaseModel):
    email: str
    display_name: str = ""
    password: str = Field(min_length=10)
    role: str = "operator"
    allowed_project_ids: list[str] = []


class UserPatch(BaseModel):
    display_name: str | None = None
    password: str | None = Field(default=None, min_length=10)
    role: str | None = None
    allowed_project_ids: list[str] | None = None
    is_active: bool | None = None


def out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "allowed_project_ids": user.allowed_project_ids or [],
        "is_active": user.is_active,
        "created_at": user.created_at,
    }


def validate_role(role: str) -> str:
    value = role.strip().lower()
    if value not in {"owner", "operator", "viewer"}:
        raise HTTPException(422, "Роль должна быть owner, operator или viewer")
    return value


def validate_projects(db: Session, ids: list[str]) -> list[str]:
    unique = list(dict.fromkeys(ids))
    if not unique:
        return []
    existing = set(db.scalars(select(Project.id).where(Project.id.in_(unique))).all())
    missing = [item for item in unique if item not in existing]
    if missing:
        raise HTTPException(422, f"Проекты не найдены: {', '.join(missing)}")
    return unique


@router.get("")
def list_users(db: Session = Depends(get_db)) -> list[dict]:
    return [out(item) for item in db.scalars(select(User).order_by(User.created_at)).all()]


@router.post("", status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> dict:
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(422, "Введите корректный email")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Пользователь уже существует")
    user = User(
        id=new_id("usr"),
        email=email,
        display_name=payload.display_name.strip() or email.split("@", 1)[0],
        password_hash=hash_password(payload.password),
        role=validate_role(payload.role),
        allowed_project_ids=validate_projects(db, payload.allowed_project_ids),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return out(user)


@router.patch("/{user_id}")
def patch_user(
    user_id: str,
    payload: UserPatch,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    values = payload.model_dump(exclude_unset=True)
    if user.id == actor.id:
        if values.get("is_active") is False:
            raise HTTPException(422, "Нельзя отключить собственный аккаунт")
        if values.get("role") and str(values["role"]).lower() != "owner":
            raise HTTPException(422, "Нельзя снять с себя роль владельца")
    if "display_name" in values:
        user.display_name = str(values["display_name"] or "").strip()
    if values.get("password"):
        user.password_hash = hash_password(str(values["password"]))
    if values.get("role"):
        user.role = validate_role(str(values["role"]))
    if "allowed_project_ids" in values:
        user.allowed_project_ids = validate_projects(db, values["allowed_project_ids"] or [])
    if "is_active" in values:
        user.is_active = bool(values["is_active"])
    db.commit()
    db.refresh(user)
    return out(user)
