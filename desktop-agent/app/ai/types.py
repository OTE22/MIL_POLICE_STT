"""Normalized AI data types. Vendor objects (NeMo, torch, transformers) never leave the adapters."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SpeechRegion:
    """A region of speech detected by VAD (seconds)."""

    start_seconds: float
    end_seconds: float


@dataclass
class SpeakerTurn:
    """WHO SPOKE WHEN - output of the diarization provider."""

    speaker_label: str  # SPEAKER_00 ... SPEAKER_03
    start_seconds: float
    end_seconds: float
    is_overlap: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


@dataclass
class TranscriptSegment:
    """Speaker turn + text = the final structured result row."""

    speaker_label: str
    start_seconds: float
    end_seconds: float
    text: str
    is_overlap: bool = False
    confidence: float | None = None
    # Audio window actually sent to STT (includes context padding).
    window_start_seconds: float | None = None
    window_end_seconds: float | None = None


@dataclass
class TranscriptionResult:
    text: str
    confidence: float | None = None


@dataclass
class ModelInfo:
    name: str  # logical name: stt / diarization / vad
    provider: str
    model: str
    revision: str | None
    state: str  # NOT_PROVISIONED | PROVISIONED | LOADING | READY | ERROR
    error: str | None = None
    loaded_at: str | None = None
    extra: dict = field(default_factory=dict)
