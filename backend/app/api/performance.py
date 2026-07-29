from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import CurrentUser, assert_project_access
from ..db import get_db
from ..models import Project, ProjectAsset, ProjectNode
from ..services.idgen import new_id
from ..services.image_provider import closest_aspect_ratio
from ..services.storage import storage

router = APIRouter(tags=["canvas-performance"])


class FastSaveRequest(BaseModel):
    project: dict[str, Any] = Field(default_factory=dict)
    nodes: list[dict[str, Any]] = Field(default_factory=list)


class BulkDeleteRequest(BaseModel):
    node_ids: list[str] = Field(default_factory=list)


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


def asset_out(asset: ProjectAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "kind": asset.kind,
        "order_index": asset.order_index,
        "original_filename": asset.original_filename,
        "mime_type": asset.mime_type,
        "url": f"/api/canvas/assets/{asset.id}",
        "created_at": asset.created_at,
        "expires_at": None,
    }


@router.post("/api/projects/{project_id}/fast-save")
def fast_save_project(
    project_id: str,
    payload: FastSaveRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = load_project_for_write(db, user, project_id)
    project_values = dict(payload.project or {})

    if "title" in project_values:
        title = str(project_values.get("title") or "").strip()
        if not title:
            raise HTTPException(422, "Название проекта не может быть пустым")
        project.title = title

    if "viewport" in project_values and project_values["viewport"] is not None:
        viewport = dict(project_values["viewport"] or {})
        edge_style = str(
            viewport.get(
                "edge_style",
                (project.viewport or {}).get("edge_style", "curved"),
            )
        )
        if edge_style not in {"curved", "orthogonal"}:
            edge_style = "curved"
        project.viewport = {
            "x": float(viewport.get("x", 0)),
            "y": float(viewport.get("y", 0)),
            "zoom": max(0.15, min(2.5, float(viewport.get("zoom", 1)))),
            "edge_style": edge_style,
        }

    requested_items: list[tuple[str, dict[str, Any]]] = []
    for item in payload.nodes[:1000]:
        node_id = str(item.get("id") or "").strip()
        if not node_id:
            continue
        requested_items.append((node_id, dict(item.get("changes") or {})))

    node_ids = list(dict.fromkeys(node_id for node_id, _ in requested_items))
    nodes = (
        db.scalars(
            select(ProjectNode).where(
                ProjectNode.project_id == project_id,
                ProjectNode.id.in_(node_ids),
            )
        ).all()
        if node_ids
        else []
    )
    node_by_id = {node.id: node for node in nodes}

    needs_note_validation = any(
        node_by_id.get(node_id)
        and node_by_id[node_id].node_type == "note"
        and "config" in changes
        for node_id, changes in requested_items
    )
    valid_project_node_ids: set[str] = set()
    if needs_note_validation:
        valid_project_node_ids = set(
            db.scalars(
                select(ProjectNode.id).where(ProjectNode.project_id == project_id)
            ).all()
        )

    saved_nodes = 0
    for node_id, values in requested_items:
        node = node_by_id.get(node_id)
        if not node:
            continue
        if "title" in values:
            node.title = str(values.get("title") or "").strip() or node.title
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
                if (
                    "prompt_text" in incoming
                    and incoming.get("prompt_text") != old_config.get("prompt_text")
                ):
                    raise HTTPException(423, "Системный промпт заблокирован")
            if "output_count" in merged:
                merged["output_count"] = max(
                    1,
                    min(20, int(merged["output_count"])),
                )
            if node.node_type == "note":
                merged["target_node_ids"] = [
                    target_id
                    for target_id in merged.get("target_node_ids", [])
                    if target_id in valid_project_node_ids and target_id != node.id
                ]
            node.config = merged
        node.updated_at = utcnow()
        saved_nodes += 1

    project.updated_at = utcnow()
    db.commit()
    return {
        "saved": True,
        "nodes": saved_nodes,
        "updated_at": project.updated_at,
    }


@router.post("/api/projects/{project_id}/nodes/bulk-delete")
def bulk_delete_nodes(
    project_id: str,
    payload: BulkDeleteRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = load_project_for_write(db, user, project_id)
    requested_ids = list(
        dict.fromkeys(str(node_id).strip() for node_id in payload.node_ids if str(node_id).strip())
    )[:500]
    if not requested_ids:
        return {"deleted": [], "updated_at": project.updated_at}

    nodes = db.scalars(
        select(ProjectNode).where(
            ProjectNode.project_id == project_id,
            ProjectNode.id.in_(requested_ids),
        )
    ).all()
    deleted_ids = [node.id for node in nodes]
    if not deleted_ids:
        return {"deleted": [], "updated_at": project.updated_at}

    storage_keys = list(
        db.scalars(
            select(ProjectAsset.storage_key).where(
                ProjectAsset.project_id == project_id,
                ProjectAsset.node_id.in_(deleted_ids),
            )
        ).all()
    )
    for node in nodes:
        db.delete(node)
    project.updated_at = utcnow()
    db.commit()

    if storage_keys:
        background_tasks.add_task(storage.delete_keys, storage_keys)
    return {"deleted": deleted_ids, "updated_at": project.updated_at}


async def replace_node_asset_fast(
    *,
    node: ProjectNode,
    kind: str,
    upload: UploadFile,
    background_tasks: BackgroundTasks,
    db: Session,
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
        asset
        for asset in node.assets
        if asset.kind == kind and asset.generation_id is None
    ]
    old_storage_keys = [asset.storage_key for asset in old_assets]

    safe_name = storage.safe_filename(upload.filename, "image.jpg")
    asset_id = new_id("asset")
    storage_key = (
        f"projects/{node.project_id}/nodes/{node.id}/{kind}/"
        f"{asset_id}_{safe_name}"
    )
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

    for old_asset in old_assets:
        db.delete(old_asset)

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

    if old_storage_keys:
        background_tasks.add_task(storage.delete_keys, old_storage_keys)
    return asset_out(asset)


@router.post("/api/canvas/nodes/{node_id}/fast-photo")
async def fast_upload_customer_photo(
    node_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    node = db.scalar(
        select(ProjectNode)
        .where(ProjectNode.id == node_id)
        .options(selectinload(ProjectNode.assets), selectinload(ProjectNode.project))
    )
    if not node:
        raise HTTPException(404, "Блок не найден")
    assert_project_access(
        user,
        node.project_id,
        write=True,
        project_type=node.project.project_type,
    )
    return await replace_node_asset_fast(
        node=node,
        kind="customer_photo",
        upload=file,
        background_tasks=background_tasks,
        db=db,
    )


@router.post("/api/canvas/nodes/{node_id}/fast-reference")
async def fast_upload_reference(
    node_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    node = db.scalar(
        select(ProjectNode)
        .where(ProjectNode.id == node_id)
        .options(selectinload(ProjectNode.assets), selectinload(ProjectNode.project))
    )
    if not node:
        raise HTTPException(404, "Блок не найден")
    assert_project_access(
        user,
        node.project_id,
        write=True,
        project_type=node.project.project_type,
    )
    return await replace_node_asset_fast(
        node=node,
        kind="reference",
        upload=file,
        background_tasks=background_tasks,
        db=db,
    )
