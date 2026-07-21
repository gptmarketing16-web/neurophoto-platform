from __future__ import annotations

from sqlalchemy import inspect, text

from .db import engine


PROJECT_COLUMNS = {
    "project_type": "VARCHAR(20) DEFAULT 'user'",
}


PROVIDER_COLUMNS = {
    "connection_mode": "VARCHAR(40) DEFAULT 'direct'",
    "api_base_url": "VARCHAR(500) DEFAULT ''",
    "model_name": "VARCHAR(160) DEFAULT ''",
    "auth_header": "VARCHAR(100) DEFAULT 'Authorization'",
    "auth_prefix": "VARCHAR(40) DEFAULT 'Bearer'",
}


def ensure_compatible_schema() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        if "projects" in tables:
            existing_projects = {column["name"] for column in inspector.get_columns("projects")}
            for name, ddl in PROJECT_COLUMNS.items():
                if name not in existing_projects:
                    connection.execute(text(f"ALTER TABLE projects ADD COLUMN {name} {ddl}"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_projects_project_type ON projects (project_type)"))
        if "provider_credentials" in tables:
            existing = {column["name"] for column in inspector.get_columns("provider_credentials")}
            for name, ddl in PROVIDER_COLUMNS.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE provider_credentials ADD COLUMN {name} {ddl}"))
