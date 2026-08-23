"""Central server configuration (environment driven)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CENTRAL_", env_file=".env", extra="ignore")

    app_name: str = "Military STT AI - Central"
    environment: str = "development"
    debug: bool = False

    database_url: str = "postgresql+psycopg://stt:stt@postgres:5432/military_stt"

    # JWT (user sessions) - HS256 symmetric secret, never shared with workstations.
    jwt_secret: str = Field(default="CHANGE_ME_IN_PRODUCTION_min_32_chars____")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # Processing tokens (asymmetric, ES256). Private key stays on the central server;
    # workstations only receive the public key.
    processing_token_private_key_path: Path = Path("/run/secrets/processing_token_private.pem")
    processing_token_public_key_path: Path = Path("/run/secrets/processing_token_public.pem")
    processing_token_issuer: str = "military-stt-central"
    processing_token_audience: str = "military-stt-agent"
    # Window in which the Local Agent must accept the job (short-lived authorization).
    processing_token_accept_ttl_seconds: int = 600
    # Window in which results / audio may still be synchronized for that job.
    processing_token_submit_ttl_seconds: int = 86400

    # Storage
    storage_root: Path = Path("/storage")
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB
    allowed_audio_extensions: tuple[str, ...] = ("wav", "mp3", "m4a", "webm")
    allowed_audio_mime_types: tuple[str, ...] = (
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/vnd.wave",
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/x-m4a",
        "audio/m4a",
        "audio/aac",
        "audio/webm",
        "video/webm",
        "application/octet-stream",
    )

    # CORS - the frontend is normally served by nginx on the same origin; extra
    # origins are only needed for local development (vite dev server).
    cors_allowed_origins: str = ""

    # Bootstrap admin (created on first start if no users exist).
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "ChangeMe!2026"
    bootstrap_admin_full_name: str = "مدير النظام"

    @property
    def cors_origins(self) -> list[str]:
        return [v.strip() for v in self.cors_allowed_origins.split(",") if v.strip()]

    @property
    def recordings_dir(self) -> Path:
        return self.storage_root / "recordings"


@lru_cache
def get_settings() -> Settings:
    return Settings()
