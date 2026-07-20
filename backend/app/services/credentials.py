from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..models import ProviderCredential
from ..settings import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.app_secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_key(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_key(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "•" * len(value)
    return f"{value[:4]}••••••••{value[-4:]}"


def get_credential(db: Session, provider: str) -> ProviderCredential | None:
    return db.get(ProviderCredential, provider.lower())


def _defaults(provider: str) -> dict[str, str]:
    if provider == "openai":
        return {
            "api_key": settings.openai_api_key or "",
            "base_url": settings.openai_api_base_url,
            "model": settings.openai_image_model,
        }
    return {
        "api_key": settings.gemini_api_key or "",
        "base_url": settings.gemini_api_base_url,
        "model": settings.gemini_image_model,
    }


def get_provider_settings(db: Session, provider: str) -> dict[str, Any]:
    provider = provider.lower()
    defaults = _defaults(provider)
    credential = get_credential(db, provider)
    api_key = decrypt_key(credential.encrypted_api_key) if credential else ""
    return {
        "provider": provider,
        "api_key": api_key or defaults["api_key"],
        "connection_mode": (credential.connection_mode if credential else "direct") or "direct",
        "base_url": (credential.api_base_url if credential else "") or defaults["base_url"],
        "model": (credential.model_name if credential else "") or defaults["model"],
        "auth_header": (credential.auth_header if credential else "Authorization") or "Authorization",
        "auth_prefix": (credential.auth_prefix if credential else "Bearer") or "",
    }


def get_api_key(db: Session, provider: str) -> str:
    return str(get_provider_settings(db, provider)["api_key"] or "")


def upsert_credential(
    db: Session,
    *,
    provider: str,
    api_key: str | None = None,
    is_locked: bool | None = None,
    connection_mode: str | None = None,
    api_base_url: str | None = None,
    model_name: str | None = None,
    auth_header: str | None = None,
    auth_prefix: str | None = None,
) -> ProviderCredential:
    provider = provider.lower()
    credential = db.get(ProviderCredential, provider)
    if not credential:
        credential = ProviderCredential(provider=provider)
        db.add(credential)
    if api_key is not None and api_key.strip():
        credential.encrypted_api_key = encrypt_key(api_key.strip())
        credential.is_connected = False
        credential.last_error = None
    if is_locked is not None:
        credential.is_locked = bool(is_locked)
    if connection_mode is not None:
        mode = connection_mode.strip().lower()
        if mode not in {"direct", "integrator"}:
            raise ValueError("connection_mode must be direct or integrator")
        credential.connection_mode = mode
    if api_base_url is not None:
        credential.api_base_url = api_base_url.strip().rstrip("/")
    if model_name is not None:
        credential.model_name = model_name.strip()
    if auth_header is not None:
        credential.auth_header = auth_header.strip() or "Authorization"
    if auth_prefix is not None:
        credential.auth_prefix = auth_prefix.strip()
    credential.updated_at = utcnow()
    db.commit()
    db.refresh(credential)
    return credential
