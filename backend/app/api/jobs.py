from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import Job, JobAsset, Template
from ..schemas import JobAssetOut, JobOut
from ..services.idgen import new_id
from ..services.jobs import delete_job_assets, run_generation_job
from ..services.storage import storage
from ..services.task_manager import task_manager

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def serialize_job(job: Job) -> JobOut:
    assets: list[JobAssetOut] = []
    for asset in job.assets:
        url = None
        if asset.kind == "output" and not job.assets_deleted_at:
            url = f"/api/jobs/{job.id}/outputs/{asset.id}"
        assets.append(
            JobAssetOut(
                id=asset.id,
                kind=asset.kind,
                role=asset.role,
                order_index=asset.order_index,
                original_filename=asset.original_filename,
                mime_type=asset.mime_type,
                url=url,
            )
        )
    return JobOut(
        id=job.id,
        template_id=job.template_id,
        customer_name=job.customer_name,
        source_channel=job.source_channel,
        output_count=job.output_count,
        status=job.status,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        expires_at=job.expires_at,
        assets_deleted_at=job.assets_deleted_at,
        assets=assets,
    )


@router.post("", response_model=JobOut, status_code=202)
async def create_job(
    template_id: Annotated[str, Form()],
    identity_files: Annotated[list[UploadFile], File()],
    db: Session = Depends(get_db),
    customer_name: Annotated[str, Form()] = "",
    output_count: Annotated[int | None, Form(ge=1, le=100)] = None,
    identity_roles_csv: Annotated[str, Form()] = "",
    source_channel: Annotated[str, Form()] = "web",
) -> JobOut:
    template = db.scalar(
        select(Template).where(Template.id == template_id, Template.is_active.is_(True))
    )
    if not template:
        raise HTTPException(404, "Template not found")
    if not identity_files:
        raise HTTPException(422, "At least one identity image is required")

    requested_count = output_count or template.default_output_count
    if requested_count > template.max_output_count:
        raise HTTPException(422, f"This template allows at most {template.max_output_count} outputs")

    roles = [item.strip() for item in identity_roles_csv.split(",") if item.strip()]
    if roles and len(roles) != len(identity_files):
        raise HTTPException(422, "identity_roles_csv must contain one role per uploaded image")
    if not roles:
        roles = ["identity"] * len(identity_files)

    job_id = new_id("job")
    job = Job(
        id=job_id,
        template_id=template.id,
        customer_name=customer_name,
        source_channel=source_channel,
        output_count=requested_count,
        status="queued",
    )
    db.add(job)

    try:
        for index, (upload, role) in enumerate(zip(identity_files, roles, strict=True)):
            safe_name = storage.safe_filename(upload.filename, f"identity_{index + 1}.jpg")
            asset_id = new_id("asset")
            storage_key = f"jobs/{job_id}/inputs/{index:03d}_{asset_id}_{safe_name}"
            sha256, _ = await storage.save_upload(storage_key, upload)
            job.assets.append(
                JobAsset(
                    id=asset_id,
                    kind="input",
                    role=role,
                    order_index=index,
                    original_filename=upload.filename or safe_name,
                    storage_key=storage_key,
                    mime_type=upload.content_type or "application/octet-stream",
                    sha256=sha256,
                )
            )
        db.commit()
        db.refresh(job)
    except Exception:
        db.rollback()
        storage.delete_prefix(f"jobs/{job_id}")
        raise

    task_manager.create(run_generation_job(job.id))
    job = db.scalar(select(Job).where(Job.id == job.id).options(selectinload(Job.assets)))
    return serialize_job(job)


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobOut:
    job = db.scalar(select(Job).where(Job.id == job_id).options(selectinload(Job.assets)))
    if not job:
        raise HTTPException(404, "Job not found")
    return serialize_job(job)


@router.get("/{job_id}/outputs/{asset_id}")
def download_output(job_id: str, asset_id: str, db: Session = Depends(get_db)) -> FileResponse:
    job = db.get(Job, job_id)
    if not job or job.assets_deleted_at:
        raise HTTPException(404, "Output is unavailable")
    asset = db.scalar(
        select(JobAsset).where(
            JobAsset.id == asset_id,
            JobAsset.job_id == job_id,
            JobAsset.kind == "output",
        )
    )
    if not asset:
        raise HTTPException(404, "Output not found")
    path = storage.absolute(asset.storage_key)
    if not path.exists():
        raise HTTPException(410, "Output has already been deleted")
    return FileResponse(path, media_type=asset.mime_type, filename=asset.original_filename)


@router.delete("/{job_id}/assets", status_code=204)
def remove_job_assets(job_id: str) -> None:
    if not delete_job_assets(job_id):
        raise HTTPException(404, "Job not found")
