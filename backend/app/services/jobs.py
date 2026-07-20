from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..db import SessionLocal
from ..models import Job, JobAsset, Template
from ..settings import settings
from .idgen import new_id
from .image_provider import get_image_provider
from .storage import storage


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_generation_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.scalar(
            select(Job)
            .where(Job.id == job_id)
            .options(selectinload(Job.template).selectinload(Template.assets), selectinload(Job.assets))
        )
        if not job:
            return
        job.status = "running"
        job.started_at = utcnow()
        db.commit()

        try:
            template_paths = [storage.absolute(asset.storage_key) for asset in job.template.assets]
            input_assets = sorted(
                [asset for asset in job.assets if asset.kind == "input"], key=lambda item: item.order_index
            )
            input_paths = [storage.absolute(asset.storage_key) for asset in input_assets]
            all_inputs = template_paths + input_paths

            provider = get_image_provider(settings.image_provider, settings.openai_api_key or "")
            output_dir = storage.absolute(f"jobs/{job.id}/outputs")
            generation_output = await provider.generate_from_references(
                prompt=job.template.prompt_text,
                image_paths=all_inputs,
                output_count=job.output_count,
                output_dir=output_dir,
                model=job.template.model,
                aspect_ratio="2:3" if job.template.size == "1024x1536" else "3:2" if job.template.size == "1536x1024" else "1:1",
                quality=job.template.quality,
            )

            for index, path in enumerate(generation_output.paths):
                data = path.read_bytes()
                storage_key = str(path.relative_to(storage.root))
                storage.persist_file(storage_key, path)
                job.assets.append(
                    JobAsset(
                        id=new_id("asset"),
                        kind="output",
                        role="generated",
                        order_index=index,
                        original_filename=path.name,
                        storage_key=storage_key,
                        mime_type="image/png" if path.suffix.lower() == ".png" else "image/jpeg",
                        sha256=hashlib.sha256(data).hexdigest(),
                    )
                )

            job.status = "completed"
            job.completed_at = utcnow()
            job.expires_at = utcnow() + timedelta(minutes=settings.temp_ttl_minutes)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - error is persisted for operators
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = utcnow()
            job.expires_at = utcnow() + timedelta(minutes=settings.temp_ttl_minutes)
            db.commit()


def delete_job_assets(job_id: str) -> bool:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job:
            return False
        storage.delete_prefix(f"jobs/{job.id}")
        job.assets_deleted_at = utcnow()
        if job.status == "completed":
            job.status = "assets_deleted"
        db.commit()
        return True


def cleanup_expired_jobs() -> int:
    now = utcnow()
    removed = 0
    with SessionLocal() as db:
        jobs = db.scalars(
            select(Job).where(
                Job.expires_at.is_not(None),
                Job.expires_at <= now,
                Job.assets_deleted_at.is_(None),
            )
        ).all()
        for job in jobs:
            storage.delete_prefix(f"jobs/{job.id}")
            job.assets_deleted_at = now
            if job.status == "completed":
                job.status = "assets_deleted"
            removed += 1
        db.commit()
    return removed
