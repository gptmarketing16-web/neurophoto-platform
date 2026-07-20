from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Workspace
from ..schemas import SlugAvailabilityOut, WorkspaceOut, WorkspaceUpsert
from ..services.idgen import new_id
from ..services.slug import normalize_slug, validate_slug

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


def get_current_workspace(db: Session) -> Workspace | None:
    return db.scalar(select(Workspace).order_by(Workspace.created_at.asc()).limit(1))


@router.get("", response_model=WorkspaceOut | None)
def read_workspace(db: Session = Depends(get_db)) -> Workspace | None:
    return get_current_workspace(db)


@router.get("/slug-availability", response_model=SlugAvailabilityOut)
def check_slug(
    slug: str = Query(min_length=1, max_length=120),
    db: Session = Depends(get_db),
) -> SlugAvailabilityOut:
    normalized = normalize_slug(slug)
    try:
        normalized = validate_slug(slug)
    except ValueError as exc:
        return SlugAvailabilityOut(
            requested=slug,
            normalized=normalized,
            available=False,
            reason=str(exc),
        )

    current = get_current_workspace(db)
    owner_id = current.id if current else None
    existing = db.scalar(select(Workspace).where(Workspace.slug == normalized))
    available = existing is None or existing.id == owner_id
    return SlugAvailabilityOut(
        requested=slug,
        normalized=normalized,
        available=available,
        reason=None if available else "Этот адрес уже занят",
    )


@router.put("", response_model=WorkspaceOut)
def upsert_workspace(payload: WorkspaceUpsert, db: Session = Depends(get_db)) -> Workspace:
    try:
        slug = validate_slug(payload.slug)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    display_name = payload.display_name.strip()
    tagline = payload.tagline.strip()
    if not 2 <= len(display_name) <= 120:
        raise HTTPException(422, "Название должно содержать 2–120 символов")
    if len(tagline) > 240:
        raise HTTPException(422, "Описание не должно превышать 240 символов")

    workspace = get_current_workspace(db)
    existing = db.scalar(select(Workspace).where(Workspace.slug == slug))
    if existing and (workspace is None or existing.id != workspace.id):
        raise HTTPException(409, "Этот адрес уже занят")

    if workspace is None:
        workspace = Workspace(
            id=new_id("ws"),
            display_name=display_name,
            slug=slug,
            tagline=tagline,
            is_public=payload.is_public,
        )
        db.add(workspace)
    else:
        workspace.display_name = display_name
        workspace.slug = slug
        workspace.tagline = tagline
        workspace.is_public = payload.is_public

    try:
        db.commit()
        db.refresh(workspace)
        return workspace
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Этот адрес уже занят") from exc
