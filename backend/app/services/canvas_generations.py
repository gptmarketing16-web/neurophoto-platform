from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..db import SessionLocal
from ..models import CanvasGeneration, GenerationMetric, Project, ProjectAsset, ProjectNode
from ..settings import settings
from .credentials import get_provider_settings
from .idgen import new_id
from .image_provider import get_image_provider
from .storage import storage


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_canvas_generation(generation_id: str) -> None:
    """Run exactly one prompt node.

    All customer-photo nodes in the same project are treated as incoming visual links.
    The prompt node contributes only its own prompt and its own persistent reference.
    """
    started_monotonic = time.monotonic()
    with SessionLocal() as db:
        generation = db.scalar(
            select(CanvasGeneration)
            .where(CanvasGeneration.id == generation_id)
            .options(
                selectinload(CanvasGeneration.prompt_node).selectinload(ProjectNode.assets),
            )
        )
        if not generation:
            return

        generation.status = "running"
        generation.started_at = utcnow()
        generation.error_message = None
        db.commit()

        try:
            project = db.scalar(
                select(Project)
                .where(Project.id == generation.project_id)
                .options(selectinload(Project.nodes).selectinload(ProjectNode.assets))
            )
            if not project:
                raise RuntimeError("Проект не найден")

            prompt_node = generation.prompt_node
            if prompt_node.node_type != "prompt":
                raise RuntimeError("Генерацию можно запускать только из блока промпта")

            config = dict(prompt_node.config or {})
            prompt_text = str(config.get("prompt_text", "")).strip()
            if not prompt_text:
                raise RuntimeError("В блоке не заполнен системный промпт")

            photo_assets: list[ProjectAsset] = []
            for node in project.nodes:
                if node.node_type == "photo":
                    photo_assets.extend(
                        asset for asset in node.assets if asset.kind == "customer_photo"
                    )

            reference_assets = [
                asset
                for asset in prompt_node.assets
                if asset.kind == "reference" and asset.generation_id is None
            ]

            if not photo_assets:
                raise RuntimeError("Добавьте хотя бы одно фото заказчика")
            if not reference_assets:
                raise RuntimeError("Загрузите референс в этот блок промпта")

            input_assets = photo_assets + reference_assets
            input_paths = [storage.absolute(asset.storage_key) for asset in input_assets]
            if any(not path.exists() for path in input_paths):
                raise RuntimeError("Один из исходных файлов уже удалён из временного хранилища")

            selected_provider = str(config.get("provider") or "openai").lower()
            if selected_provider not in {"openai", "gemini"}:
                selected_provider = "openai"
            provider_settings = get_provider_settings(db, selected_provider)
            api_key = str(provider_settings.get("api_key") or "")
            if not api_key and not settings.allow_mock_fallback:
                raise RuntimeError(f"Провайдер {selected_provider} не подключён")
            actual_provider = selected_provider if api_key else "mock"
            provider_config = dict(provider_settings)
            provider_config["provider"] = actual_provider
            if actual_provider == "mock":
                provider_config["connection_mode"] = "direct"
            provider = get_image_provider(provider_config)

            detected_ratio = str(config.get("detected_aspect_ratio") or "1:1")
            selected_ratio = str(config.get("aspect_ratio") or "auto")
            aspect_ratio = detected_ratio if selected_ratio == "auto" else selected_ratio
            default_model = str(provider_settings.get("model") or (
                settings.openai_image_model if selected_provider == "openai" else settings.gemini_image_model
            ))
            model = str(config.get("model") or default_model)

            output_dir = storage.absolute(
                f"projects/{project.id}/generations/{generation.id}/outputs"
            )
            generation_output = await provider.generate_from_references(
                prompt=prompt_text,
                image_paths=input_paths,
                output_count=generation.output_count,
                output_dir=output_dir,
                model=model,
                aspect_ratio=aspect_ratio,
                quality=str(config.get("quality") or "high"),
            )

            for index, path in enumerate(generation_output.paths):
                data = path.read_bytes()
                suffix = path.suffix.lower()
                mime_type = "image/png" if suffix == ".png" else "image/jpeg"
                storage_key = str(path.relative_to(storage.root))
                storage.persist_file(storage_key, path)
                generation.assets.append(
                    ProjectAsset(
                        id=new_id("asset"),
                        project_id=project.id,
                        node_id=prompt_node.id,
                        generation_id=generation.id,
                        kind="output",
                        order_index=index,
                        original_filename=path.name,
                        storage_key=storage_key,
                        mime_type=mime_type,
                        sha256=hashlib.sha256(data).hexdigest(),
                    )
                )

            generation.provider = actual_provider
            generation.status = "completed"
            generation.completed_at = utcnow()
            duration_ms = int((time.monotonic() - started_monotonic) * 1000)
            usage = generation_output.usage or {}
            db.add(
                GenerationMetric(
                    id=new_id("metric"),
                    generation_id=generation.id,
                    project_id=project.id,
                    prompt_node_id=prompt_node.id,
                    provider=actual_provider,
                    model=model,
                    image_count=len(generation_output.paths),
                    input_tokens=int(usage.get("input_tokens", 0) or 0),
                    output_tokens=int(usage.get("output_tokens", 0) or 0),
                    total_tokens=int(usage.get("total_tokens", 0) or 0),
                    duration_ms=duration_ms,
                )
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            generation.status = "failed"
            generation.error_message = str(exc)
            generation.completed_at = utcnow()
            db.commit()
