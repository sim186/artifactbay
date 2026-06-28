"""App configuration via environment (.env supported)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FOUNDRY_", env_file=".env", extra="ignore")

    # SQLite for instant local dev; swap to Postgres via FOUNDRY_DATABASE_URL.
    # e.g. postgresql+psycopg://user:pass@localhost/foundry
    database_url: str = "sqlite:///./foundry.db"

    base_url: str = "http://localhost:8000"

    # Bootstrap API key: seeded as a real (hashed) ApiKey row on startup so existing
    # agents/CLI keep working. Set empty to disable.
    api_key: str = "fdy_dev_changeme"

    # Auth. CHANGE jwt_secret + admin_password in real deploys.
    jwt_secret: str = "dev-insecure-change-me-please-32byte-minimum"
    jwt_ttl_hours: int = 720
    cookie_name: str = "foundry_session"
    cookie_secure: bool = False  # True behind HTTPS
    admin_username: str = "admin"
    admin_password: str = "admin"

    max_artifact_bytes: int = 25 * 1024 * 1024
    max_request_bytes: int = 50 * 1024 * 1024
    max_artifacts: int = 100


settings = Settings()
