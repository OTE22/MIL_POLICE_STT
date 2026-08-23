"""Local AI Agent configuration (environment / .env driven, prefix AGENT_)."""

from __future__ import annotations

import os
import platform
import socket
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Pinned, approved model revisions. Do not auto-upgrade production models.
COHERE_STT_MODEL = "CohereLabs/cohere-transcribe-arabic-07-2026"
COHERE_STT_REVISION = "c3e911b42149bf7a1e53d5cef9878aee87515a23"
NVIDIA_DIARIZATION_MODEL = "nvidia/diar_streaming_sortformer_4spk-v2.1"
NVIDIA_DIARIZATION_REVISION = "fafaab5faa1617a0ca52d38dd3dc4bd636800d3d"
SILERO_VAD_MODEL = "snakers4/silero-vad"

# The Sortformer 4spk model supports at most four speakers.
MAX_SUPPORTED_SPEAKERS = 4


def _default_base_dir() -> Path:
    if platform.system() == "Windows":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "InvestigationAI"
    if Path("/models").exists() or Path("/.dockerenv").exists():
        return Path("/opt/investigation-ai")
    return Path("/opt/investigation-ai")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=".env", extra="ignore")

    # ---- service -----------------------------------------------------------
    bind_host: str = "127.0.0.1"
    port: int = 17117
    # Binding to anything except loopback is refused unless an administrator sets this.
    allow_non_loopback_bind: bool = False
    device_name: str = Field(default_factory=socket.gethostname)
    agent_id: str | None = None  # generated + persisted if missing
    log_level: str = "INFO"

    # Browser origins allowed to call this agent (the central frontend).
    allowed_origins: str = "http://localhost:8080,http://127.0.0.1:8080,https://localhost:8443,https://127.0.0.1:8443"

    # ---- storage -----------------------------------------------------------
    data_dir: Path = Field(default_factory=lambda: _default_base_dir() / "agent")
    model_dir: Path = Field(default_factory=lambda: _default_base_dir() / "models")
    temp_retention_hours: int = 72
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024
    min_duration_seconds: float = 0.5
    max_duration_seconds: float = 6 * 3600

    # ---- STT (Cohere, local) ------------------------------------------------
    stt_provider: str = "cohere_local"
    stt_model: str = COHERE_STT_MODEL
    stt_model_revision: str = COHERE_STT_REVISION
    stt_language: str = "ar"
    stt_device: str = "auto"  # auto | cuda | cpu
    stt_dtype: str = "auto"  # auto | float16 | bfloat16 | float32
    stt_max_new_tokens: int = 448
    stt_num_beams: int = 1

    # ---- diarization (NVIDIA Sortformer, local) -----------------------------
    diarization_provider: str = "nvidia_sortformer"
    diarization_model: str = NVIDIA_DIARIZATION_MODEL
    diarization_model_revision: str = NVIDIA_DIARIZATION_REVISION
    diarization_device: str = "auto"
    # Streaming configuration (80 ms frames). Defaults = "very high latency" preset,
    # the most accurate offline setting from the model card.
    diarization_chunk_len: int = 340
    diarization_right_context: int = 40
    diarization_fifo_len: int = 40
    diarization_update_period: int = 300
    diarization_speaker_cache_len: int = 188
    diarization_min_overlap_seconds: float = 0.2

    # ---- VAD (Silero) ------------------------------------------------------
    vad_enabled: bool = True
    vad_threshold: float = 0.5
    vad_min_speech_ms: int = 250
    vad_min_silence_ms: int = 300
    vad_speech_pad_ms: int = 60

    # ---- segment post-processing -------------------------------------------
    segment_min_turn_seconds: float = 0.3
    segment_merge_gap_seconds: float = 0.7
    segment_max_seconds: float = 28.0
    segment_context_padding_seconds: float = 0.3

    # ---- models lifecycle --------------------------------------------------
    preload_models: bool = False
    verify_model_integrity: str = "size"  # none | size | full

    # ---- central server ------------------------------------------------------
    central_url: str = "http://localhost:8080"
    central_sync_enabled: bool = True
    central_upload_audio: bool = True
    central_verify_tls: bool = True
    central_ca_bundle: Path | None = None
    central_public_key_path: Path | None = None  # defaults to data_dir/central_public_key.pem
    central_public_key_auto_fetch: bool = False  # TOFU convenience for pilots only
    central_timeout_seconds: float = 60.0
    sync_max_attempts: int = 0  # 0 = retry forever (with capped backoff)
    sync_backoff_base_seconds: float = 5.0
    sync_backoff_max_seconds: float = 600.0
    token_issuer: str = "military-stt-central"
    token_audience: str = "military-stt-agent"
    clock_skew_seconds: int = 60

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "agent.sqlite3"

    @property
    def public_key_path(self) -> Path:
        return self.central_public_key_path or (self.data_dir / "central_public_key.pem")

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def stt_model_dir(self) -> Path:
        return self.model_dir / self.stt_model.split("/")[-1]

    @property
    def diarization_model_dir(self) -> Path:
        return self.model_dir / self.diarization_model.split("/")[-1]

    @property
    def diarization_nemo_path(self) -> Path:
        return self.diarization_model_dir / f"{self.diarization_model.split('/')[-1]}.nemo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
