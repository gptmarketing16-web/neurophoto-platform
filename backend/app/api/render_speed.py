from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, assert_project_access
from ..db import get_db
from ..models import Project, ProjectAsset, ProjectNode
from ..services.idgen import new_id
from ..services.storage import storage
from ..settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["canvas-render-speed"])


class InstantNodeCreate(BaseModel):
    node_type: str
    title: str | None = None
    x: float = 0.0
    y: float = 0.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_project_for_write(db: Session, user, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Проект не найден")
    assert_project_access(
        user,
        project_id,
        write=True,
        project_type=project.project_type,
    )
    return project


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


def next_prompt_number(db: Session, project_id: str) -> int:
    maximum = db.scalar(
        select(func.max(ProjectNode.config["reference_number"].as_integer())).where(
            ProjectNode.project_id == project_id,
            ProjectNode.node_type == "prompt",
        )
    )
    return int(maximum or 0) + 1


def node_payload(node: ProjectNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "project_id": node.project_id,
        "node_type": node.node_type,
        "title": node.title,
        "x": node.x,
        "y": node.y,
        "config": node.config or {},
        "assets": [],
        "generations": [],
        "latest_generation": None,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
    }


@router.post("/api/projects/{project_id}/nodes/instant-create", status_code=201)
def instant_create_node(
    project_id: str,
    payload: InstantNodeCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = load_project_for_write(db, user, project_id)
    node_type = payload.node_type.strip().lower()
    if node_type not in {"photo", "prompt", "note"}:
        raise HTTPException(422, "node_type должен быть photo, prompt или note")

    if node_type == "photo":
        number = count_nodes(db, project_id, "photo") + 1
        title = (payload.title or f"Фото заказчика {number}").strip()
        config: dict[str, Any] = {}
    elif node_type == "note":
        number = count_nodes(db, project_id, "note") + 1
        title = (payload.title or f"Заметка {number}").strip()
        config = {"note_text": "", "target_node_ids": []}
    else:
        number = next_prompt_number(db, project_id)
        title = (payload.title or f"Генерация №{number}").strip()
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
        project_id=project_id,
        node_type=node_type,
        title=title or "Без названия",
        x=float(payload.x),
        y=float(payload.y),
        config=config,
    )
    node.project = project
    db.add(node)
    project.updated_at = utcnow()
    db.commit()
    return node_payload(node)


def signed_asset_url(storage_key: str, expires_seconds: int = 900) -> str | None:
    client = getattr(storage, "client", None)
    bucket = getattr(storage, "bucket", None)
    if client is None or not bucket:
        return None
    try:
        return str(
            client.generate_presigned_url(
                "get_object",
                Params={"Bucket": str(bucket), "Key": storage_key},
                ExpiresIn=expires_seconds,
            )
        )
    except Exception:
        logger.warning("Could not create a signed URL for canvas asset", exc_info=True)
        return None


@router.get("/api/canvas/assets/{asset_id}/direct")
def get_canvas_asset_direct(
    asset_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    row = db.execute(
        select(ProjectAsset, Project.project_type)
        .join(Project, Project.id == ProjectAsset.project_id)
        .where(ProjectAsset.id == asset_id)
    ).one_or_none()
    if not row:
        raise HTTPException(404, "Изображение не найдено")
    asset, project_type = row
    assert_project_access(
        user,
        asset.project_id,
        write=False,
        project_type=project_type,
    )

    signed_url = signed_asset_url(asset.storage_key)
    if signed_url:
        return RedirectResponse(
            signed_url,
            status_code=307,
            headers={"Cache-Control": "private, max-age=300"},
        )

    path = storage.absolute(asset.storage_key)
    if not path.exists():
        raise HTTPException(410, "Файл отсутствует в хранилище")
    return FileResponse(
        path,
        media_type=asset.mime_type,
        filename=asset.original_filename,
        headers={"Cache-Control": "private, max-age=3600"},
    )
