from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import CurrentUser, assert_project_access
from ..db import get_db
from ..models import CanvasGeneration, Project, ProjectAsset, ProjectNode
from ..schemas import GenerateNodeRequest, NodeCreate, NodePatch, ProjectCreate, ProjectPatch
from ..services.image_provider import closest_aspect_ratio
from ..services.idgen import new_id
from ..services.storage import storage
from ..services.generation_queue import enqueue_generation
from ..settings import settings

router = APIRouter(tags=["canvas"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _project_query(project_id: str):
    return (
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.nodes).selectinload(ProjectNode.assets),
            selectinload(Project.nodes)
            .selectinload(ProjectNode.generations)
            .selectinload(CanvasGeneration.assets),
        )
    )


def _load_project(db: Session, project_id: str, user=None, *, write: bool = False) -> Project:
    project = db.scalar(_project_query(project_id))
    if not project:
        raise HTTPException(404, "Проект не найден")
    if user is not None:
        assert_project_access(user, project_id, write=write)
    return project


def _asset_out(asset: ProjectAsset) -> dict[str, Any]:
    expires_at = None
    if asset.kind == "customer_photo":
        expires_at = asset.created_at + timedelta(minutes=settings.customer_asset_ttl_minutes)
    elif asset.kind == "output":
        expires_at = asset.created_at + timedelta(minutes=settings.output_asset_ttl_minutes)
    return {
        "id": asset.id,
        "kind": asset.kind,
        "order_index": asset.order_index,
        "original_filename": asset.original_filename,
        "mime_type": asset.mime_type,
        "url": f"/api/canvas/assets/{asset.id}",
        "created_at": asset.created_at,
        "expires_at": expires_at,
    }


def _generation_out(generation: CanvasGeneration) -> dict[str, Any]:
    return {
        "id": generation.id,
        "prompt_node_id": generation.prompt_node_id,
        "status": generation.status,
        "output_count": generation.output_count,
        "provider": generation.provider,
        "error_message": generation.error_message,
        "created_at": generation.created_at,
        "started_at": generation.started_at,
        "completed_at": generation.completed_at,
        "outputs": [_asset_out(asset) for asset in generation.assets if asset.kind == "output"],
    }


def _node_out(node: ProjectNode) -> dict[str, Any]:
    generations = sorted(node.generations, key=lambda item: item.created_at)
    return {
        "id": node.id,
        "project_id": node.project_id,
        "node_type": node.node_type,
        "title": node.title,
        "x": node.x,
        "y": node.y,
        "config": node.config or {},
        "assets": [
            _asset_out(asset)
            for asset in node.assets
            if asset.generation_id is None and asset.kind in {"customer_photo", "reference"}
        ],
        "generations": [_generation_out(item) for item in generations],
        "latest_generation": _generation_out(generations[-1]) if generations else None,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
    }


def _project_out(project: Project) -> dict[str, Any]:
    nodes = sorted(project.nodes, key=lambda item: item.created_at)
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "theme": project.theme,
        "tags": project.tags or [],
        "viewport": project.viewport or {"x": 80, "y": 80, "zoom": 1},
        "nodes": [_node_out(node) for node in nodes],
        "photo_count": sum(node.node_type == "photo" for node in nodes),
        "prompt_count": sum(node.node_type == "prompt" for node in nodes),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def next_reference_number(project: Project) -> int:
    numbers: list[int] = []
    for node in project.nodes:
        if node.node_type != "prompt":
            continue
        try:
            numbers.append(int((node.config or {}).get("reference_number", 0)))
        except (TypeError, ValueError):
            continue
    return max(numbers, default=0) + 1


@router.get("/api/projects")
def list_projects(user: CurrentUser, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    query = select(Project).options(selectinload(Project.nodes)).order_by(Project.updated_at.desc())
    if user.role != "owner":
        allowed = user.allowed_project_ids or []
        if not allowed:
            return []
        query = query.where(Project.id.in_(allowed))
    projects = db.scalars(query).all()
    return [
        {
            "id": project.id,
            "title": project.title,
            "description": project.description,
            "theme": project.theme,
            "tags": project.tags or [],
            "photo_count": sum(node.node_type == "photo" for node in project.nodes),
            "prompt_count": sum(node.node_type == "prompt" for node in project.nodes),
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }
        for project in projects
    ]


@router.post("/api/projects", status_code=201)
def create_project(payload: ProjectCreate, user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    if user.role not in {"owner", "operator"}:
        raise HTTPException(403, "Недостаточно прав для создания проекта")
    title = payload.title.strip()
    if not title:
        raise HTTPException(422, "Введите название проекта")
    project = Project(
        id=new_id("prj"),
        title=title,
        description=payload.description.strip(),
        theme=payload.theme.strip(),
        tags=[tag.strip() for tag in payload.tags if tag.strip()],
        viewport={"x": 80.0, "y": 80.0, "zoom": 1.0, "edge_style": "curved"},
    )
    db.add(project)
    db.commit()
    if user.role != "owner":
        user.allowed_project_ids = list(dict.fromkeys([*(user.allowed_project_ids or []), project.id]))
        db.commit()
    return _project_out(_load_project(db, project.id, user))


@router.get("/api/projects/{project_id}")
def get_project(project_id: str, user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _project_out(_load_project(db, project_id, user))


@router.patch("/api/projects/{project_id}")
def patch_project(
    project_id: str, payload: ProjectPatch, user: CurrentUser, db: Session = Depends(get_db)
) -> dict[str, Any]:
    assert_project_access(user, project_id, write=True)
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Проект не найден")
    values = payload.model_dump(exclude_unset=True)
    if "title" in values:
        title = str(values["title"] or "").strip()
        if not title:
            raise HTTPException(422, "Название проекта не может быть пустым")
        project.title = title
    for field in ("description", "theme"):
        if field in values:
            setattr(project, field, str(values[field] or "").strip())
    if "tags" in values:
        project.tags = [str(tag).strip() for tag in (values["tags"] or []) if str(tag).strip()]
    if "viewport" in values and values["viewport"] is not None:
        viewport = values["viewport"]
        edge_style = str(viewport.get("edge_style", (project.viewport or {}).get("edge_style", "curved")))
        if edge_style not in {"curved", "orthogonal"}:
            edge_style = "curved"
        project.viewport = {
            "x": float(viewport.get("x", 0)),
            "y": float(viewport.get("y", 0)),
            "zoom": max(0.15, min(2.5, float(viewport.get("zoom", 1)))),
            "edge_style": edge_style,
        }
    project.updated_at = utcnow()
    db.commit()
    return _project_out(_load_project(db, project_id, user))


@router.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: str, user: CurrentUser, db: Session = Depends(get_db)) -> None:
    assert_project_access(user, project_id, write=True)
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Проект не найден")
    storage_keys = list(
        db.scalars(select(ProjectAsset.storage_key).where(ProjectAsset.project_id == project_id)).all()
    )
    db.delete(project)
    db.commit()
    storage.delete_keys(storage_keys)


@router.post("/api/projects/{project_id}/nodes", status_code=201)
def create_node(
    project_id: str, payload: NodeCreate, user: CurrentUser, db: Session = Depends(get_db)
) -> dict[str, Any]:
    project = _load_project(db, project_id, user, write=True)
    node_type = payload.node_type.strip().lower()
    if node_type not in {"photo", "prompt", "note"}:
        raise HTTPException(422, "node_type должен быть photo, prompt или note")

    if node_type == "photo":
        count = sum(node.node_type == "photo" for node in project.nodes) + 1
        title = (payload.title or f"Фото заказчика {count}").strip()
        config: dict[str, Any] = {}
    elif node_type == "note":
        count = sum(node.node_type == "note" for node in project.nodes) + 1
        title = (payload.title or f"Заметка {count}").strip()
        config = {"note_text": "", "target_node_ids": []}
    else:
        number = next_reference_number(project)
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
            "prompt_locked": False,
            "reference_locked": False,
        }

    node = ProjectNode(
        id=new_id("node"),
        project_id=project.id,
        node_type=node_type,
        title=title,
        x=float(payload.x),
        y=float(payload.y),
        config=config,
    )
    db.add(node)
    project.updated_at = utcnow()
    db.commit()
    return _node_out(
        db.scalar(
            select(ProjectNode)
            .where(ProjectNode.id == node.id)
            .options(
                selectinload(ProjectNode.assets),
                selectinload(ProjectNode.generations).selectinload(CanvasGeneration.assets),
            )
        )
    )


@router.patch("/api/canvas/nodes/{node_id}")
def patch_node(node_id: str, payload: NodePatch, user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    node = db.scalar(
        select(ProjectNode)
        .where(ProjectNode.id == node_id)
        .options(
            selectinload(ProjectNode.assets),
            selectinload(ProjectNode.generations).selectinload(CanvasGeneration.assets),
        )
    )
    if not node:
        raise HTTPException(404, "Блок не найден")
    assert_project_access(user, node.project_id, write=True)
    values = payload.model_dump(exclude_unset=True)
    if "title" in values:
        node.title = str(values["title"] or "").strip() or node.title
    if "x" in values:
        node.x = float(values["x"])
    if "y" in values:
        node.y = float(values["y"])
    if "config" in values and values["config"] is not None:
        old_config = dict(node.config or {})
        incoming = dict(values["config"] or {})
        merged = dict(old_config)
        merged.update(incoming)
        if old_config.get("prompt_locked") and incoming.get("prompt_locked", True):
            if "prompt_text" in incoming and incoming.get("prompt_text") != old_config.get("prompt_text"):
                raise HTTPException(423, "Системный промпт заблокирован")
        if "output_count" in merged:
            merged["output_count"] = max(1, min(20, int(merged["output_count"])))
        if node.node_type == "note":
            valid_ids = {item.id for item in node.project.nodes if item.id != node.id}
            merged["target_node_ids"] = [
                item for item in merged.get("target_node_ids", []) if item in valid_ids
            ]
        node.config = merged
    node.updated_at = utcnow()
    node.project.updated_at = utcnow()
    db.commit()
    db.refresh(node)
    return _node_out(node)


@router.delete("/api/canvas/nodes/{node_id}", status_code=204)
def delete_node(node_id: str, user: CurrentUser, db: Session = Depends(get_db)) -> None:
    node = db.get(ProjectNode, node_id)
    if not node:
        raise HTTPException(404, "Блок не найден")
    assert_project_access(user, node.project_id, write=True)
    project_id = node.project_id
    generation_ids = list(
        db.scalars(
            select(CanvasGeneration.id).where(CanvasGeneration.prompt_node_id == node.id)
        ).all()
    )
    asset_filter = ProjectAsset.node_id == node.id
    if generation_ids:
        asset_filter = asset_filter | ProjectAsset.generation_id.in_(generation_ids)
    storage_keys = list(
        db.scalars(select(ProjectAsset.storage_key).where(asset_filter)).all()
    )
    project = db.get(Project, project_id)
    db.delete(node)
    if project:
        project.updated_at = utcnow()
    db.commit()
    storage.delete_keys(storage_keys)


async def _replace_node_asset(
    *, node: ProjectNode, kind: str, upload: UploadFile, db: Session
) -> dict[str, Any]:
    if node.node_type == "photo" and kind != "customer_photo":
        raise HTTPException(422, "В фото-блок можно загрузить только фото заказчика")
    if node.node_type == "prompt" and kind != "reference":
        raise HTTPException(422, "В промпт-блок можно загрузить только референс")
    if not (upload.content_type or "").startswith("image/"):
        raise HTTPException(422, "Нужно выбрать изображение")

    if kind == "reference" and bool((node.config or {}).get("reference_locked")):
        raise HTTPException(423, "Референс заблокирован")

    old_assets = [
        asset for asset in node.assets
        if asset.kind == kind and asset.generation_id is None
    ]
    for asset in old_assets:
        storage.delete_key(asset.storage_key)
        db.delete(asset)

    safe_name = storage.safe_filename(upload.filename, "image.png")
    asset_id = new_id("asset")
    storage_key = f"projects/{node.project_id}/nodes/{node.id}/{kind}/{asset_id}_{safe_name}"
    try:
        sha256, _ = await storage.save_upload(storage_key, upload)
    except ValueError as exc:
        raise HTTPException(413, str(exc)) from exc

    if kind == "reference":
        try:
            with Image.open(storage.absolute(storage_key)) as image:
                width, height = image.size
            config = dict(node.config or {})
            config["detected_aspect_ratio"] = closest_aspect_ratio(width, height)
            config["reference_width"] = width
            config["reference_height"] = height
            node.config = config
        except Exception:
            pass

    asset = ProjectAsset(
        id=asset_id,
        project_id=node.project_id,
        node_id=node.id,
        generation_id=None,
        kind=kind,
        order_index=0,
        original_filename=upload.filename or safe_name,
        storage_key=storage_key,
        mime_type=upload.content_type or "application/octet-stream",
        sha256=sha256,
    )
    db.add(asset)
    node.updated_at = utcnow()
    node.project.updated_at = utcnow()
    db.commit()
    return _asset_out(asset)


@router.post("/api/canvas/nodes/{node_id}/photo")
async def upload_customer_photo(
    node_id: str, user: CurrentUser, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    node = db.scalar(
        select(ProjectNode)
        .where(ProjectNode.id == node_id)
        .options(selectinload(ProjectNode.assets), selectinload(ProjectNode.project))
    )
    if not node:
        raise HTTPException(404, "Блок не найден")
    assert_project_access(user, node.project_id, write=True)
    return await _replace_node_asset(node=node, kind="customer_photo", upload=file, db=db)


@router.post("/api/canvas/nodes/{node_id}/reference")
async def upload_reference(
    node_id: str, user: CurrentUser, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    node = db.scalar(
        select(ProjectNode)
        .where(ProjectNode.id == node_id)
        .options(selectinload(ProjectNode.assets), selectinload(ProjectNode.project))
    )
    if not node:
        raise HTTPException(404, "Блок не найден")
    assert_project_access(user, node.project_id, write=True)
    return await _replace_node_asset(node=node, kind="reference", upload=file, db=db)


@router.post("/api/canvas/nodes/{node_id}/generate", status_code=202)
async def generate_node(
    node_id: str,
    payload: GenerateNodeRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    node = db.scalar(
        select(ProjectNode)
        .where(ProjectNode.id == node_id)
        .options(selectinload(ProjectNode.assets))
    )
    if not node:
        raise HTTPException(404, "Блок не найден")
    assert_project_access(user, node.project_id, write=True)
    if node.node_type != "prompt":
        raise HTTPException(422, "Генерация запускается только из промпт-блока")
    config = node.config or {}
    if not str(config.get("prompt_text", "")).strip():
        raise HTTPException(422, "Заполните системный промпт")
    if not any(asset.kind == "reference" for asset in node.assets):
        raise HTTPException(422, "Загрузите референс")
    photo_exists = db.scalar(
        select(ProjectAsset.id)
        .join(ProjectNode, ProjectNode.id == ProjectAsset.node_id)
        .where(
            ProjectNode.project_id == node.project_id,
            ProjectNode.node_type == "photo",
            ProjectAsset.kind == "customer_photo",
        )
        .limit(1)
    )
    if not photo_exists:
        raise HTTPException(422, "Добавьте хотя бы одно фото заказчика")

    requested = payload.output_count or int(config.get("output_count", 1))
    requested = max(1, min(20, int(requested)))
    generation = CanvasGeneration(
        id=new_id("gen"),
        project_id=node.project_id,
        prompt_node_id=node.id,
        status="queued",
        output_count=requested,
        provider=str(config.get("provider") or "openai"),
    )
    db.add(generation)
    node.project.updated_at = utcnow()
    db.commit()
    enqueue_generation(generation.id)
    return _generation_out(generation)


@router.get("/api/canvas/generations/{generation_id}")
def get_generation(generation_id: str, user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    generation = db.scalar(
        select(CanvasGeneration)
        .where(CanvasGeneration.id == generation_id)
        .options(selectinload(CanvasGeneration.assets))
    )
    if not generation:
        raise HTTPException(404, "Генерация не найдена")
    assert_project_access(user, generation.project_id)
    return _generation_out(generation)


@router.get("/api/canvas/assets/{asset_id}")
def get_canvas_asset(asset_id: str, user: CurrentUser, db: Session = Depends(get_db)) -> FileResponse:
    asset = db.get(ProjectAsset, asset_id)
    if not asset:
        raise HTTPException(404, "Изображение не найдено")
    assert_project_access(user, asset.project_id)
    path = storage.absolute(asset.storage_key)
    if not path.exists():
        raise HTTPException(410, "Файл отсутствует в хранилище")
    return FileResponse(
        path,
        media_type=asset.mime_type,
        filename=asset.original_filename,
        headers={"Cache-Control": "private, max-age=3600"},
    )
