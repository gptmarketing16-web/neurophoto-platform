from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ProjectAsset
from app.services.storage import storage
from app.settings import settings


def error_code(exc: Exception) -> str:
    response = getattr(exc, "response", {}) or {}
    error = response.get("Error") or {}
    return str(error.get("Code", "")) or "no-code"


print("STORAGE_TYPE:", type(storage).__name__)
print("STORAGE_BACKEND:", settings.storage_backend)
print(
    "S3_CONFIGURED:",
    all(
        [
            settings.s3_endpoint_url,
            settings.s3_bucket,
            settings.s3_access_key,
            settings.s3_secret_key,
        ]
    ),
)

with SessionLocal() as db:
    assets = db.scalars(
        select(ProjectAsset)
        .where(ProjectAsset.kind == "reference")
        .order_by(ProjectAsset.created_at.desc())
        .limit(20)
    ).all()

print("REFERENCES_IN_DB:", len(assets))

found = 0
missing = 0
errors = 0
codes: dict[str, int] = {}

for asset in assets:
    try:
        path = storage.absolute(asset.storage_key)
        if path.exists():
            found += 1
        else:
            missing += 1
    except Exception as exc:  # diagnostics must report, not abort
        errors += 1
        code = error_code(exc)
        codes[code] = codes.get(code, 0) + 1

print("FOUND:", found)
print("MISSING:", missing)
print("ACCESS_ERRORS:", errors)
for code, count in sorted(codes.items()):
    print(f"ERROR_CODE_{code}: {count}")
