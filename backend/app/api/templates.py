from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import Template, TemplateAsset
from ..schemas import TemplateOut
from ..services.idgen import new_id
from ..services.storage import storage
from ..settings import settings

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.post("", response_model=TemplateOut, status_code=201)
async def create_template(
    title: Annotated[str, Form(min_length=1, max_length=200)],
    prompt_text: Annotated[str, Form(min_length=1)],
    reference_files: Annotated[list[UploadFile], File()],
    db: Session = Depends(get_db),
    description: Annotated[str, Form()] = "",
    input_schema_json: Annotated[str, Form()] = '{"identity": {"min": 1, "max": 10}}',
    default_output_count: Annotated[int, Form(ge=1, le=100)] = 1,
    max_output_count: Annotated[int, Form(ge=1, le=100)] = 10,
    model: Annotated[str, Form()] = "gpt-image-2",
    size: Annotated[str, Form()] = "1024x1536",
    quality: Annotated[str, Form()] = "high",
) -> Template:
    if not reference_files:
        raise HTTPException(422, "At least one reference image is required")
    if default_output_count > max_output_count:
        raise HTTPException(422, "default_output_count cannot exceed max_output_count")
    try:
        input_schema = json.loads(input_schema_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"input_schema_json is invalid: {exc.msg}") from exc

    template_id = new_id("tpl")
    template = Template(
        id=template_id,
        title=title,
        description=description,
        prompt_text=prompt_text,
        input_schema=input_schema,
        default_output_count=default_output_count,
        max_output_count=max_output_count,
        model=model or settings.openai_image_model,
        size=size,
        quality=quality,
    )
    db.add(template)

    try:
        for index, upload in enumerate(reference_files):
            safe_name = storage.safe_filename(upload.filename, f"reference_{index + 1}.png")
            asset_id = new_id("asset")
            storage_key = f"templates/{template_id}/references/{index:03d}_{asset_id}_{safe_name}"
            sha256, _ = await storage.save_upload(storage_key, upload)
            template.assets.append(
                TemplateAsset(
                    id=asset_id,
                    role="scene_reference",
                    order_index=index,
                    original_filename=upload.filename or safe_name,
                    storage_key=storage_key,
                    mime_type=upload.content_type or "application/octet-stream",
                    sha256=sha256,
                )
            )
        db.commit()
        db.refresh(template)
        return db.scalar(
            select(Template).where(Template.id == template.id).options(selectinload(Template.assets))
        )
    except Exception:
        db.rollback()
        storage.delete_prefix(f"templates/{template_id}")
        raise


@router.get("", response_model=list[TemplateOut])
def list_templates(db: Session = Depends(get_db)) -> list[Template]:
    return list(
        db.scalars(
            select(Template)
            .where(Template.is_active.is_(True))
            .options(selectinload(Template.assets))
            .order_by(Template.created_at.desc())
        ).all()
    )


@router.get("/{template_id}", response_model=TemplateOut)
def get_template(template_id: str, db: Session = Depends(get_db)) -> Template:
    template = db.scalar(
        select(Template).where(Template.id == template_id).options(selectinload(Template.assets))
    )
    if not template:
        raise HTTPException(404, "Template not found")
    return template


@router.delete("/{template_id}", status_code=204)
def deactivate_template(template_id: str, db: Session = Depends(get_db)) -> None:
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    template.is_active = False
    db.commit()
