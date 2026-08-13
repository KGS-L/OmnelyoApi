"""Configuration stricte et isolée du backend SaaS."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ShortPilot Platform API"
    api_environment: str = "development"
    api_database_url: str = "postgresql+psycopg://robot:robot@localhost:5432/robot_short_yt"
    redis_url: str = "redis://localhost:6379/0"
    api_jwt_secret: str = "change-me-in-production"
    api_jwt_algorithm: str = "HS256"
    api_access_token_minutes: int = 15
    api_refresh_token_days: int = 30
    otp_ttl_seconds: int = 600
    otp_max_attempts: int = 5
    otp_request_limit_per_hour: int = 5
    google_web_client_id: str = ""
    telegram_bot_username: str = ""
    telegram_link_ttl_seconds: int = 600
    social_credentials_key: str = ""
    social_oauth_callback_base_url: str = ""
    social_oauth_state_ttl_seconds: int = 600
    youtube_client_secrets_file: Path = Path("credentials/client_secret.json")
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_sandbox_mode: bool = True
    r2_signed_url_ttl_seconds: int = 900
    video_upload_max_bytes: int = 500 * 1024 * 1024
    api_rate_limit_enabled: bool = True
    api_rate_limit_per_minute: int = 120
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_graph_api_version: str = "v23.0"
    worker_poll_interval_seconds: float = 2.0
    worker_stale_after_seconds: int = 300
    worker_heartbeat_interval_seconds: int = 30
    worker_recovery_interval_seconds: int = 60
    worker_retry_delay_seconds: int = 30
    frontend_origins: str = "http://localhost:3000"
    expose_dev_otp: bool = False

    @field_validator("api_jwt_secret")
    @classmethod
    def secure_production_secret(cls, value: str, info):
        if info.data.get("api_environment") == "production" and len(value) < 32:
            raise ValueError("API_JWT_SECRET doit contenir au moins 32 caractères en production.")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @field_validator("telegram_bot_username")
    @classmethod
    def normalize_bot_username(cls, value: str) -> str:
        return value.strip().lstrip("@")


@lru_cache
def get_settings() -> APISettings:
    return APISettings()
