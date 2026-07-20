from __future__ import annotations

from sqlalchemy import inspect, text

from .db import engine


PROVIDER_COLUMNS = {
    "connection_mode": "VARCHAR(40) DEFAULT 'direct'",
    "api_base_url": "VARCHAR(500) DEFAULT ''",
    "model_name": "VARCHAR(160) DEFAULT ''",
    "auth_header": "VARCHAR(100) DEFAULT 'Authorization'",
    "auth_prefix": "VARCHAR(40) DEFAULT 'Bearer'",
}


def ensure_compatible_schema() -> None:
    inspector = inspect(engine)
    if "provider_credentials" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("provider_credentials")}
    with engine.begin() as connection:
        for name, ddl in PROVIDER_COLUMNS.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE provider_credentials ADD COLUMN {name} {ddl}"))
