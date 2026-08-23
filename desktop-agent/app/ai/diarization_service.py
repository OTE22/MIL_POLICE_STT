"""Speaker diarization: WHO SPOKE WHEN.

Provider abstraction + the default NVIDIA Streaming Sortformer adapter
(nvidia/diar_streaming_sortformer_4spk-v2.1 through NVIDIA NeMo).

The diarization model is used ONLY for speaker activity / speaker change
detection, grouping of repeated anonymous speakers and timestamps. It never
produces text. NVIDIA ASR is deliberately not used anywhere in this agent.
"""

from __future__ import annotations

import logging
import re
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from app.ai.device import resolve_device
from app.ai.model_files import model_files_status
from app.ai.types import ModelInfo, SpeakerTurn
from app.config import MAX_SUPPORTED_SPEAKERS, Settings

log = logging.getLogger(__name__)


class DiarizationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class DiarizationService(ABC):
    """Interface every diarization provider implements."""

    provider: str = "abstract"
    max_speakers: int = MAX_SUPPORTED_SPEAKERS

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def diarize(self, audio_path: str | Path) -> list[SpeakerTurn]: ...

    @abstractmethod
    def info(self) -> ModelInfo: ...

    @property
    def device(self) -> str:
        return "cpu"


def normalize_label(raw: str | int) -> str:
    """speaker_0 / spk1 / 2 -> SPEAKER_00 / SPEAKER_01 / SPEAKER_02."""
    if isinstance(raw, int):
        return f"SPEAKER_{raw:02d}"
    m = re.search(r"(\d+)\s*$", str(raw))
    idx = int(m.group(1)) if m else 0
    return f"SPEAKER_{idx:02d}"


def parse_nemo_segments(items: list) -> list[SpeakerTurn]:
    """Parse NeMo diarize() output for one file.

    NeMo returns strings such as "0.000 5.120 speaker_0"; newer versions may
    return dicts or tuples. All forms are normalized here.
    """
    turns: list[SpeakerTurn] = []
    for item in items:
        start = end = None
        label = None
        if isinstance(item, str):
            parts = item.strip().split()
            if len(parts) >= 3:
                start, end, label = float(parts[0]), float(parts[1]), parts[2]
        elif isinstance(item, dict):
            start = float(item.get("start", item.get("start_time", 0.0)))
            end = float(item.get("end", item.get("end_time", 0.0)))
            label = item.get("speaker", item.get("label", 0))
        elif isinstance(item, (list, tuple)) and len(item) >= 3:
            start, end, label = float(item[0]), float(item[1]), item[2]
        if start is None or end is None or label is None or end <= start:
            continue
        turns.append(SpeakerTurn(normalize_label(label), round(start, 3), round(end, 3)))
    turns.sort(key=lambda t: (t.start_seconds, t.end_seconds))
    return turns


def mark_overlaps(turns: list[SpeakerTurn], min_overlap: float) -> list[SpeakerTurn]:
    """Flag turns that overlap in time with a turn of a different speaker."""
    for i, a in enumerate(turns):
        for b in turns[i + 1 :]:
            if b.start_seconds >= a.end_seconds:
                break
            if b.speaker_label == a.speaker_label:
                continue
            overlap = min(a.end_seconds, b.end_seconds) - max(a.start_seconds, b.start_seconds)
            if overlap >= min_overlap:
                a.is_overlap = True
                b.is_overlap = True
    return turns


def relabel_by_first_appearance(turns: list[SpeakerTurn]) -> list[SpeakerTurn]:
    """Ensure SPEAKER_00 is whoever speaks first, SPEAKER_01 the next new voice, etc."""
    mapping: dict[str, str] = {}
    for t in turns:
        if t.speaker_label not in mapping:
            mapping[t.speaker_label] = f"SPEAKER_{len(mapping):02d}"
    for t in turns:
        t.speaker_label = mapping[t.speaker_label]
    return turns


class NvidiaSortformerDiarizationService(DiarizationService):
    provider = "nvidia_sortformer"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model = None
        self._lock = threading.Lock()
        self._state = "PROVISIONED" if self._files_present() else "NOT_PROVISIONED"
        self._error: str | None = None
        self._loaded_at: str | None = None
        self._device = "cpu"

    def _files_present(self) -> bool:
        return self._settings.diarization_nemo_path.exists()

    @property
    def device(self) -> str:
        return self._device

    def info(self) -> ModelInfo:
        if self._state == "NOT_PROVISIONED" and self._files_present():
            self._state = "PROVISIONED"
        return ModelInfo(
            name="diarization",
            provider=self.provider,
            model=self._settings.diarization_model,
            revision=self._settings.diarization_model_revision,
            state=self._state,
            error=self._error,
            loaded_at=self._loaded_at,
            extra={
                "device": self._device,
                "max_speakers": self.max_speakers,
                "streaming": {
                    "chunk_len": self._settings.diarization_chunk_len,
                    "chunk_right_context": self._settings.diarization_right_context,
                    "fifo_len": self._settings.diarization_fifo_len,
                    "spkcache_update_period": self._settings.diarization_update_period,
                    "spkcache_len": self._settings.diarization_speaker_cache_len,
                },
            },
        )

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            path = self._settings.diarization_nemo_path
            ok, problem = model_files_status(self._settings.diarization_model_dir, self._settings.verify_model_integrity)
            if not path.exists():
                self._state = "NOT_PROVISIONED"
                self._error = f"model file missing: {path}"
                raise DiarizationError("diarization_model_missing", self._error)
            if not ok:
                self._state = "ERROR"
                self._error = f"integrity check failed: {problem}"
                raise DiarizationError("diarization_model_integrity", self._error)
            self._state = "LOADING"
            try:
                import torch
                from nemo.collections.asr.models import SortformerEncLabelModel

                self._device = resolve_device(self._settings.diarization_device)
                model = SortformerEncLabelModel.restore_from(
                    restore_path=str(path), map_location=torch.device(self._device), strict=False
                )
                model.eval()
                s = self._settings
                mods = model.sortformer_modules
                mods.chunk_len = s.diarization_chunk_len
                mods.chunk_right_context = s.diarization_right_context
                mods.fifo_len = s.diarization_fifo_len
                mods.spkcache_update_period = s.diarization_update_period
                mods.spkcache_len = s.diarization_speaker_cache_len
                if hasattr(mods, "_check_streaming_parameters"):
                    mods._check_streaming_parameters()
                self._model = model
                self._state = "READY"
                self._error = None
                self._loaded_at = datetime.now(timezone.utc).isoformat()
                log.info("Sortformer diarization model loaded on %s", self._device)
            except Exception as exc:  # noqa: BLE001
                self._state = "ERROR"
                self._error = str(exc)[:300]
                log.exception("Sortformer load failed")
                raise DiarizationError("diarization_model_load_failed", self._error) from exc

    def diarize(self, audio_path: str | Path) -> list[SpeakerTurn]:
        self.load()
        try:
            import torch

            with torch.inference_mode():
                output = self._model.diarize(audio=[str(audio_path)], batch_size=1)
        except Exception as exc:  # noqa: BLE001
            log.exception("Sortformer inference failed")
            raise DiarizationError("diarization_failed", str(exc)[:300]) from exc
        if isinstance(output, tuple):  # include_tensor_outputs=True variant
            output = output[0]
        per_file = output[0] if output and isinstance(output[0], (list, tuple)) else output
        turns = parse_nemo_segments(list(per_file or []))
        turns = relabel_by_first_appearance(turns)
        return mark_overlaps(turns, self._settings.diarization_min_overlap_seconds)


def build_diarization_service(settings: Settings) -> DiarizationService:
    provider = settings.diarization_provider.lower()
    if provider == "nvidia_sortformer":
        return NvidiaSortformerDiarizationService(settings)
    raise ValueError(f"unsupported diarization provider: {provider}")
