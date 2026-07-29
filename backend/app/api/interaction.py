from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser
from ..db import get_db
from ..models import Project, ProjectNode
from ..services.idgen import new_id
from ..settings import settings
from .performance import load_project_for_write, replace_node_asset_fast

router = APIRouter(tags=["canvas-interaction"])


class FastNodeCreate(BaseModel):
    node_type: str
    title: str | None = None
    x: float = 0.0
    y: float = 0.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def count_nodes(db: Session, project_id: str, node_type: str) -> int:
    return int(
        db.scalar(
            select(func.count(ProjectNode.id)).where(
                ProjectNode.project_id == project_id,
                ProjectNode.node_type == node_type,
            )
        )
        or 0
    )


def next_reference_number(db: Session, project_id: str) -> int:
    configs = db.scalars(
        select(ProjectNode.config).where(
            ProjectNode.project_id == project_id,
            ProjectNode.node_type == "prompt",
        )
    ).all()
    numbers: list[int] = []
    for config in configs:
        try:
            numbers.append(int((config or {}).get("reference_number", 0)))
        except (TypeError, ValueError):
            continue
    return max(numbers, default=0) + 1


def build_node(
    *,
    db: Session,
    project: Project,
    node_type: str,
    x: float,
    y: float,
    title: str | None = None,
) -> ProjectNode:
    normalized = node_type.strip().lower()
    if normalized not in {"photo", "prompt", "note"}:
        raise HTTPException(422, "node_type должен быть photo, prompt или note")

    if normalized == "photo":
        number = count_nodes(db, project.id, "photo") + 1
        node_title = (title or f"Фото заказчика {number}").strip()
        config: dict[str, Any] = {}
    elif normalized == "note":
        number = count_nodes(db, project.id, "note") + 1
        node_title = (title or f"Заметка {number}").strip()
        config = {"note_text": "", "target_node_ids": []}
    else:
        number = next_reference_number(db, project.id)
        node_title = (title or f"Генерация №{number}").strip()
        config = {
            "reference_number": number,
            "prompt_text": "",
            "output_count": 1,
            "provider": "openai",
            "model": settings.openai_image_model,
            "aspect_ratio": "auto",
            "detected_aspect_ratio": "1:1",
            "quality": "high",
            "output_format": "png",
            "prompt_locked": False,
            "reference_locked": False,
        }

    node = ProjectNode(
        id=new_id("node"),
        project_id=project.id,
        node_type=normalized,
        title=node_title or "Без названия",
        x=float(x),
        y=float(y),
        config=config,
    )
    node.project = project
    db.add(node)
    project.updated_at = utcnow()
    return node


def node_out(node: ProjectNode, assets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": node.id,
        "project_id": node.project_id,
        "node_type": node.node_type,
        "title": node.title,
        "x": node.x,
        "y": node.y,
        "config": node.config or {},
        "assets": assets or [],
        "generations": [],
        "latest_generation": None,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
    }


@router.post("/api/projects/{project_id}/nodes/fast-create", status_code=201)
def fast_create_node(
    project_id: str,
    payload: FastNodeCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = load_project_for_write(db, user, project_id)
    node = build_node(
        db=db,
        project=project,
        node_type=payload.node_type,
        title=payload.title,
        x=payload.x,
        y=payload.y,
    )
    db.commit()
    db.refresh(node)
    return node_out(node)


@router.post("/api/projects/{project_id}/nodes/fast-photo", status_code=201)
async def fast_create_photo_with_upload(
    project_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    x: float = Form(...),
    y: float = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = load_project_for_write(db, user, project_id)
    node = build_node(
        db=db,
        project=project,
        node_type="photo",
        x=x,
        y=y,
    )
    db.flush()
    try:
        asset = await replace_node_asset_fast(
            node=node,
            kind="customer_photo",
            upload=file,
            background_tasks=background_tasks,
            db=db,
        )
    except Exception:
        db.rollback()
        raise
    return node_out(node, [asset])
