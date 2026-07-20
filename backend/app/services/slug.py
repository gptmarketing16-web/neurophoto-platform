from __future__ import annotations

import re
import unicodedata

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]{2,47}$")
RESERVED_SLUGS = {
    "api",
    "app",
    "docs",
    "redoc",
    "openapi",
    "health",
    "static",
    "admin",
    "login",
    "logout",
    "signup",
    "register",
    "settings",
    "support",
}


def normalize_slug(value: str) -> str:
    """Normalize a user-facing workspace slug into a safe URL path segment."""
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = re.sub(r"[\s\-]+", "_", ascii_value)
    ascii_value = re.sub(r"[^a-z0-9_]", "", ascii_value)
    ascii_value = re.sub(r"_+", "_", ascii_value).strip("_")
    return ascii_value[:48]


def validate_slug(value: str) -> str:
    slug = normalize_slug(value)
    if slug in RESERVED_SLUGS:
        raise ValueError("Этот адрес зарезервирован системой")
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("Адрес должен содержать 3–48 латинских букв, цифр или символов _")
    return slug
