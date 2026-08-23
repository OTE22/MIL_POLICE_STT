"""Voice Activity Detection (Silero VAD, bundled with the `silero-vad` package).

Purpose: find speech regions so that silence is never sent to the STT model
(fewer hallucinations, faster processing) and diarization turns are trimmed to
actual speech. Thresholds are configurable through AGENT_VAD_* settings.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.ai.types import ModelInfo, SpeechRegion
from app.config import SILERO_VAD_MODEL, Settings

log = logging.getLogger(__name__)


class VadService:
    provider = "silero_vad"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model = None
        self._lock = threading.Lock()
        self._state = "PROVISIONED"
        self._error: str | None = None
        self._loaded_at: str | None = None
        self._version: str | None = None

    # ------------------------------------------------------------ lifecycle
    def info(self) -> ModelInfo:
        return ModelInfo(
            name="vad",
            provider=self.provider,
            model=SILERO_VAD_MODEL,
            revision=self._version,
            state=self._state if self._settings.vad_enabled else "READY",
            error=self._error,
            loaded_at=self._loaded_at,
            extra={"enabled": self._settings.vad_enabled},
        )

    @property
    def model_name(self) -> str:
        return f"{SILERO_VAD_MODEL}@{self._version}" if self._version else SILERO_VAD_MODEL

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            self._state = "LOADING"
            try:
                from importlib.metadata import version as pkg_version

                from silero_vad import load_silero_vad

                self._model = load_silero_vad(onnx=False)
                try:
                    self._version = f"silero-vad {pkg_version('silero-vad')}"
                except Exception:  # noqa: BLE001
                    self._version = "silero-vad"
                self._state = "READY"
                self._loaded_at = datetime.now(timezone.utc).isoformat()
                log.info("VAD model loaded (%s)", self._version)
            except Exception as exc:  # noqa: BLE001
                self._state = "ERROR"
                self._error = str(exc)[:300]
                log.exception("VAD load failed")
                raise

    # ------------------------------------------------------------ inference
    def detect(self, wav_path: Path, duration_seconds: float) -> list[SpeechRegion]:
        """Return speech regions (seconds) for a 16 kHz mono WAV file."""
        if not self._settings.vad_enabled:
            return [SpeechRegion(0.0, duration_seconds)]
        self.load()
        from silero_vad import get_speech_timestamps, read_audio

        wav = read_audio(str(wav_path), sampling_rate=16000)
        s = self._settings
        stamps = get_speech_timestamps(
            wav,
            self._model,
            threshold=s.vad_threshold,
            sampling_rate=16000,
            min_speech_duration_ms=s.vad_min_speech_ms,
            min_silence_duration_ms=s.vad_min_silence_ms,
            speech_pad_ms=s.vad_speech_pad_ms,
            return_seconds=True,
        )
        regions = [SpeechRegion(float(t["start"]), min(float(t["end"]), duration_seconds)) for t in stamps]
        return [r for r in regions if r.end_seconds > r.start_seconds]
