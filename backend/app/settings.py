from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NeuroPhoto Platform"
    app_env: str = "development"  # development | production
    database_url: str = "sqlite:///./data/neurophoto.db"
    storage_root: Path = Path("./data/storage")
    storage_backend: str = "local"  # local | s3
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "ru-1"

    image_provider: str = "mock"  # retained for health display
    allow_mock_fallback: bool = True

    openai_api_key: str | None = None
    openai_api_base_url: str = "https://api.openai.com/v1"
    openai_image_model: str = "gpt-image-2"
    openai_max_concurrency: int = 2

    gemini_api_key: str | None = None
    gemini_api_base_url: str = "https://generativelanguage.googleapis.com"
    gemini_image_model: str = "gemini-3.1-flash-image"
    gemini_max_concurrency: int = 2

    app_secret_key: str = "local-development-key-change-me"
    session_cookie_name: str = "neurophoto_session"
    session_ttl_hours: int = 24
    secure_cookies: bool = False
    owner_email: str = "owner@example.com"
    owner_password: str = "ChangeMe123!"
    owner_name: str = "Владелец"

    redis_url: str | None = None
    queue_mode: str = "inline"  # inline | redis

    customer_asset_ttl_minutes: int = 30
    output_asset_ttl_minutes: int = 60
    temp_ttl_minutes: int = 60
    cleanup_interval_seconds: int = 60
    max_upload_mb: int = 50

    max_webhook_secret: str | None = None
    automation_api_token: str | None = None
    max_bot_token: str | None = None
    max_api_base_url: str = "https://platform-api2.max.ru"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
settings.storage_root.mkdir(parents=True, exist_ok=True)
