from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_editor, require_owner
from ..db import get_db
from ..models import CanvasGeneration, GenerationMetric, ProjectAsset, ProviderCredential
from ..services.credentials import decrypt_key, get_provider_settings, mask_key, upsert_credential
from ..services.storage import storage
from ..settings import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


class CredentialUpdate(BaseModel):
    api_key: str | None = None
    is_locked: bool | None = None
    connection_mode: str | None = None
    api_base_url: str | None = None
    model_name: str | None = None
    auth_header: str | None = None
    auth_prefix: str | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _provider_out(credential: ProviderCredential | None, provider: str) -> dict[str, Any]:
    resolved = get_provider_settings_from_credential(credential, provider)
    return {
        "provider": provider,
        "is_connected": bool(credential.is_connected) if credential else bool(resolved["api_key"]),
        "is_locked": bool(credential.is_locked) if credential else True,
        "masked_key": mask_key(str(resolved["api_key"])),
        "last_error": credential.last_error if credential else None,
        "last_tested_at": credential.last_tested_at if credential else None,
        "connection_mode": resolved["connection_mode"],
        "api_base_url": resolved["base_url"],
        "default_model": resolved["model"],
        "auth_header": resolved["auth_header"],
        "auth_prefix": resolved["auth_prefix"],
    }


def get_provider_settings_from_credential(credential: ProviderCredential | None, provider: str) -> dict[str, Any]:
    if provider == "openai":
        default_key = settings.openai_api_key or ""
        default_url = settings.openai_api_base_url
        default_model = settings.openai_image_model
    else:
        default_key = settings.gemini_api_key or ""
        default_url = settings.gemini_api_base_url
        default_model = settings.gemini_image_model
    return {
        "api_key": (decrypt_key(credential.encrypted_api_key) if credential else "") or default_key,
        "connection_mode": (credential.connection_mode if credential else "direct") or "direct",
        "base_url": (credential.api_base_url if credential else "") or default_url,
        "model": (credential.model_name if credential else "") or default_model,
        "auth_header": (credential.auth_header if credential else "Authorization") or "Authorization",
        "auth_prefix": (credential.auth_prefix if credential else "Bearer") or "",
    }


@router.get("/providers", dependencies=[Depends(require_editor)])
def providers(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [_provider_out(db.get(ProviderCredential, name), name) for name in ("openai", "gemini")]


@router.put("/providers/{provider}", dependencies=[Depends(require_owner)])
def save_provider(provider: str, payload: CredentialUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    provider = provider.lower()
    if provider not in {"openai", "gemini"}:
        raise HTTPException(404, "Неизвестный провайдер")
    try:
        credential = upsert_credential(
            db,
            provider=provider,
            api_key=payload.api_key,
            is_locked=payload.is_locked,
            connection_mode=payload.connection_mode,
            api_base_url=payload.api_base_url,
            model_name=payload.model_name,
            auth_header=payload.auth_header,
            auth_prefix=payload.auth_prefix,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _provider_out(credential, provider)


def _auth_headers(config: dict[str, Any]) -> dict[str, str]:
    key = str(config.get("api_key") or "")
    if not key:
        return {}
    prefix = str(config.get("auth_prefix") or "").strip()
    value = f"{prefix} {key}".strip()
    return {str(config.get("auth_header") or "Authorization"): value}


async def _test_direct(provider: str, config: dict[str, Any]) -> None:
    key = str(config["api_key"])
    base = str(config["base_url"]).rstrip("/")
    model = str(config["model"])
    async with httpx.AsyncClient(timeout=25) as client:
        if provider == "openai":
            response = await client.get(
                f"{base}/models/{quote(model, safe='')}",
                headers={"Authorization": f"Bearer {key}"},
            )
        else:
            # Standard Gemini REST endpoint. Custom integrators should use Integrator mode.
            base = base.rstrip("/")
            if base.endswith("/v1beta"):
                url = f"{base}/models/{quote(model, safe='')}"
            else:
                url = f"{base}/v1beta/models/{quote(model, safe='')}"
            response = await client.get(url, headers={"x-goog-api-key": key})
    if response.status_code >= 400:
        raise RuntimeError(f"Провайдер вернул {response.status_code}: {response.text[:500]}")


async def _test_integrator(config: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        response = await client.get(str(config["base_url"]), headers=_auth_headers(config))
    # 405 is acceptable: many generation endpoints only allow POST.
    if response.status_code in {401, 403, 404} or response.status_code >= 500:
        raise RuntimeError(f"Интегратор вернул {response.status_code}: {response.text[:500]}")


@router.post("/providers/{provider}/test", dependencies=[Depends(require_owner)])
async def test_provider(provider: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    provider = provider.lower()
    if provider not in {"openai", "gemini"}:
        raise HTTPException(404, "Неизвестный провайдер")
    config = get_provider_settings(db, provider)
    if not config["api_key"]:
        raise HTTPException(422, "Сначала сохраните API-ключ")
    credential = db.get(ProviderCredential, provider)
    if not credential:
        credential = upsert_credential(db, provider=provider, api_key=str(config["api_key"]), is_locked=True)
    try:
        if config["connection_mode"] == "integrator":
            await _test_integrator(config)
        else:
            await _test_direct(provider, config)
        credential.is_connected = True
        credential.last_error = None
    except Exception as exc:
        credential.is_connected = False
        credential.last_error = str(exc)
    credential.last_tested_at = utcnow()
    credential.updated_at = utcnow()
    db.commit()
    if not credential.is_connected:
        raise HTTPException(422, credential.last_error or "Не удалось подключиться")
    return _provider_out(credential, provider)


def _dir_size(path: Path) -> int:
    total = 0
    if path.exists():
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    return total


@router.get("/diagnostics", dependencies=[Depends(require_editor)])
def diagnostics(db: Session = Depends(get_db)) -> dict[str, Any]:
    now = utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_generations = db.scalar(select(func.count(CanvasGeneration.id)).where(CanvasGeneration.created_at >= day_start)) or 0
    today_completed = db.scalar(select(func.count(CanvasGeneration.id)).where(CanvasGeneration.created_at >= day_start, CanvasGeneration.status == "completed")) or 0
    today_failed = db.scalar(select(func.count(CanvasGeneration.id)).where(CanvasGeneration.created_at >= day_start, CanvasGeneration.status == "failed")) or 0
    metric_totals = db.execute(
        select(
            func.coalesce(func.sum(GenerationMetric.image_count), 0),
            func.coalesce(func.sum(GenerationMetric.total_tokens), 0),
            func.coalesce(func.sum(GenerationMetric.input_tokens), 0),
            func.coalesce(func.sum(GenerationMetric.output_tokens), 0),
        ).where(GenerationMetric.created_at >= day_start)
    ).one()
    all_images = db.scalar(select(func.coalesce(func.sum(GenerationMetric.image_count), 0))) or 0
    temp_customer = db.scalar(select(func.count(ProjectAsset.id)).where(ProjectAsset.kind == "customer_photo")) or 0
    temp_outputs = db.scalar(select(func.count(ProjectAsset.id)).where(ProjectAsset.kind == "output")) or 0
    provider_rows = db.execute(
        select(GenerationMetric.provider, func.sum(GenerationMetric.image_count), func.sum(GenerationMetric.total_tokens))
        .where(GenerationMetric.created_at >= day_start)
        .group_by(GenerationMetric.provider)
    ).all()
    return {
        "today": {
            "runs": int(today_generations), "completed": int(today_completed), "failed": int(today_failed),
            "images": int(metric_totals[0]), "tokens": int(metric_totals[1]),
            "input_tokens": int(metric_totals[2]), "output_tokens": int(metric_totals[3]),
        },
        "all_time_images": int(all_images),
        "temporary": {
            "customer_photos": int(temp_customer), "outputs": int(temp_outputs),
            "storage_bytes": _dir_size(storage.root),
            "customer_ttl_minutes": settings.customer_asset_ttl_minutes,
            "output_ttl_minutes": settings.output_asset_ttl_minutes,
        },
        "providers": [
            {"provider": row[0], "images": int(row[1] or 0), "tokens": int(row[2] or 0)}
            for row in provider_rows
        ],
    }
