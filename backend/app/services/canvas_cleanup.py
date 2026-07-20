from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from ..db import SessionLocal
from ..models import ProjectAsset
from ..settings import settings
from .storage import storage


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def cleanup_expired_canvas_assets() -> int:
    now = utcnow()
    customer_cutoff = now - timedelta(minutes=settings.customer_asset_ttl_minutes)
    output_cutoff = now - timedelta(minutes=settings.output_asset_ttl_minutes)
    removed = 0
    with SessionLocal() as db:
        assets = db.scalars(
            select(ProjectAsset).where(
                or_(
                    and_(ProjectAsset.kind == "customer_photo", ProjectAsset.created_at <= customer_cutoff),
                    and_(ProjectAsset.kind == "output", ProjectAsset.created_at <= output_cutoff),
                )
            )
        ).all()
        for asset in assets:
            storage.delete_key(asset.storage_key)
            db.delete(asset)
            removed += 1
        db.commit()
    return removed
