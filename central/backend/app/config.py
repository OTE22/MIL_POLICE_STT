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

    # Voice identification (suggestions only; a human confirms every one).
    # Calibrated on the reference recordings: same speaker 0.76-0.90, different 0.34-0.52.
    voice_match_threshold: float = 0.65
    # Refuse to choose when the two best candidates are closer than this.
    voice_match_margin: float = 0.05
    # Used by the manual فحص البصمات الصوتية review: two of one person's prints at or
    # above this similarity are flagged near-duplicates (zero added coverage under
    # best-print-per-person scoring). Advisory only - nothing is refused or removed.
    voice_near_duplicate_threshold: float = 0.98

    # Arabic formalization (الصياغة بالفصحى). Entirely OPTIONAL: the محضر workflow works
    # without any model, and the investigator writes the Fusha wording by hand.
    report_fusha_enabled: bool = True
    report_fusha_temperature: float = 0.1
    # Measured: the 550B development model answers one Q&A block in ~38s, so 60s left
    # almost no headroom for a long answer. Tunable in إعدادات النظام.
    report_fusha_timeout_seconds: int = 120
    report_fusha_max_input_chars: int = 4000
    report_max_qa_blocks: int = 500
    report_template_upload_max_mb: int = 20

    # Which runtime may serve it. "auto" resolves by environment: development may use the
    # hosted NVIDIA NIM catalogue, production is LOCAL ONLY and never falls back to a cloud
    # provider - that is an invariant in code, not a setting anyone can flip.
    llm_runtime_mode: str = "auto"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    development_llm_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    # The key is a SECRET: read from a file the operator provisions (docker secret or
    # bind-mounted), never from the settings table, never from a request, never logged.
    nvidia_api_key_file: Path = Path("/run/secrets/nvidia_api_key")

    # Local runtime (production). APPROVED profiles only: the resolver picks the strongest
    # profile this hardware supports AND whose model is already provisioned - it never
    # downloads, and never picks a model just because the VRAM would fit.
    ollama_base_url: str = "http://host.docker.internal:11434"
    llm_cpu_model: str = "qwen3:8b"
    llm_gpu_small_model: str = "qwen3:8b"
    llm_gpu_medium_model: str = "qwen3:14b"
    llm_gpu_large_model: str = "qwen3:32b"
    llm_gpu_small_min_vram_gb: float = 6.0
    llm_gpu_medium_min_vram_gb: float = 12.0
    llm_gpu_large_min_vram_gb: float = 22.0
    llm_cpu_min_ram_gb: float = 12.0

    # Logging. The JSON file sink lives under /storage so it SURVIVES container
    # recreation and travels with the existing /storage backups. This is the engineering
    # record of what the system did; the audit_logs table remains the legal record of
    # who did what - deliberately separate.
    log_level: str = "INFO"
    # Per-logger overrides, e.g. "sqlalchemy.engine=WARNING,app.services.voice_matching=DEBUG"
    log_levels: str = ""
    # None -> <storage>/logs. Empty string -> file sink disabled (the test default: the
    # suite must not write into /storage, and `docker compose run` has no such volume).
    log_dir: str | None = None
    slow_query_ms: int = 200

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

    @property
    def resolved_log_dir(self) -> Path | None:
        """Where the JSON sink writes; None disables it (CENTRAL_LOG_DIR="")."""
        if self.log_dir is None:
            return self.storage_root / "logs"
        if not self.log_dir.strip():
            return None
        return Path(self.log_dir)


@lru_cache
def get_settings() -> Settings:
    return Settings()
