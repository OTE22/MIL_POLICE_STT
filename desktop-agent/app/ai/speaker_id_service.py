"""Speaker identification support: a voice embedding per anonymous speaker.

Scope, deliberately narrow:

* This service ONLY turns a speaker's audio into a fixed-length vector. It does not
  decide who the person is, it does not know any names, and it never writes a name
  anywhere. Matching an embedding against enrolled voices happens on the central
  server, and the resulting name is a **suggestion that an investigator must confirm**.
* It does not replace diarization. Sortformer still answers "who spoke when"; this
  service only answers "how does that anonymous voice sound".
* If the model is missing or fails, the job still completes with anonymous labels -
  identification is strictly optional (see `pipeline._stage_identify_speakers`).

Provider: NVIDIA SpeakerNet-M (`nvidia/speakerverification_speakernet`) through NeMo's
`EncDecSpeakerLabelModel`, producing 256-dimension embeddings.
"""

from __future__ import annotations

import logging
import tempfile
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.ai.device import resolve_device
from app.ai.model_files import model_files_status
from app.ai.types import ModelInfo
from app.config import SPEAKER_EMBEDDING_DIM, Settings

log = logging.getLogger(__name__)


class SpeakerIdentificationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class SpeakerIdentificationService(ABC):
    """Interface every voice-embedding provider implements."""

    provider: str = "abstract"
    embedding_dim: int = SPEAKER_EMBEDDING_DIM

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def embed(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray: ...

    @abstractmethod
    def info(self) -> ModelInfo: ...

    @property
    def device(self) -> str:
        return "cpu"


class NemoSpeakerNetService(SpeakerIdentificationService):
    provider = "nemo_speakernet"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model = None
        self._lock = threading.Lock()
        self._state = "PROVISIONED" if self._files_present() else "NOT_PROVISIONED"
        self._error: str | None = None
        self._loaded_at: str | None = None
        self._device = "cpu"

    def _files_present(self) -> bool:
        return self._settings.speaker_id_nemo_path.exists()

    @property
    def device(self) -> str:
        return self._device

    def info(self) -> ModelInfo:
        if self._state == "NOT_PROVISIONED" and self._files_present():
            self._state = "PROVISIONED"
            self._error = None
        return ModelInfo(
            name="speaker_id",
            provider=self.provider,
            model=self._settings.speaker_id_model,
            revision=self._settings.speaker_id_model_revision,
            state=self._state,
            error=self._error,
            loaded_at=self._loaded_at,
            extra={
                "device": self._device,
                "embedding_dim": self.embedding_dim,
                "enabled": self._settings.speaker_id_enabled,
                "min_seconds": self._settings.speaker_id_min_seconds,
            },
        )

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            path = self._settings.speaker_id_nemo_path
            if not path.exists():
                self._state = "NOT_PROVISIONED"
                self._error = f"model file missing: {path}"
                raise SpeakerIdentificationError("speaker_id_model_missing", self._error)
            ok, problem = model_files_status(
                self._settings.speaker_id_model_dir, self._settings.verify_model_integrity
            )
            if not ok:
                self._state = "ERROR"
                self._error = f"integrity check failed: {problem}"
                raise SpeakerIdentificationError("speaker_id_model_integrity", self._error)
            self._state = "LOADING"
            try:
                import torch
                from nemo.collections.asr.models import EncDecSpeakerLabelModel

                self._device = resolve_device(self._settings.speaker_id_device)
                model = EncDecSpeakerLabelModel.restore_from(
                    restore_path=str(path), map_location=torch.device(self._device)
                )
                model.eval()
                self._model = model
                self._state = "READY"
                self._error = None
                self._loaded_at = datetime.now(timezone.utc).isoformat()
                log.info("SpeakerNet-M loaded on %s", self._device)
            except Exception as exc:  # noqa: BLE001
                self._state = "ERROR"
                self._error = str(exc)[:300]
                log.exception("SpeakerNet load failed")
                raise SpeakerIdentificationError("speaker_id_model_load_failed", self._error) from exc

    def embed(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        """Return an L2-normalized embedding for one speaker's concatenated audio."""
        self.load()
        import soundfile as sf
        import torch

        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        duration = len(audio) / float(sample_rate)
        if duration < self._settings.speaker_id_min_seconds:
            raise SpeakerIdentificationError(
                "speaker_id_audio_too_short", f"{duration:.2f}s < {self._settings.speaker_id_min_seconds}s"
            )
        # NeMo's public API reads from a file, so use a private temporary one.
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "speaker.wav"
            sf.write(str(wav), audio, sample_rate)
            try:
                with torch.inference_mode():
                    emb = self._model.get_embedding(str(wav)).squeeze()
            except Exception as exc:  # noqa: BLE001
                raise SpeakerIdentificationError("speaker_id_failed", str(exc)[:300]) from exc
        vec = emb.detach().cpu().numpy().astype(np.float32).reshape(-1)
        norm = float(np.linalg.norm(vec))
        if norm == 0.0 or not np.isfinite(norm):
            raise SpeakerIdentificationError("speaker_id_failed", "degenerate embedding")
        return vec / norm


def build_speaker_id_service(settings: Settings) -> SpeakerIdentificationService:
    provider = settings.speaker_id_provider.lower()
    if provider == "nemo_speakernet":
        return NemoSpeakerNetService(settings)
    raise ValueError(f"unsupported speaker identification provider: {provider}")


def collect_speaker_audio(
    audio: np.ndarray,
    sample_rate: int,
    spans: list[tuple[float, float]],
    max_seconds: float,
) -> np.ndarray:
    """Concatenate a speaker's turns, longest first, up to `max_seconds`.

    Longest-first keeps the most informative speech when the cap is hit, and the
    concatenation order does not matter to the encoder.
    """
    ordered = sorted(spans, key=lambda s: s[1] - s[0], reverse=True)
    chunks: list[np.ndarray] = []
    total = 0.0
    for start, end in ordered:
        if total >= max_seconds:
            break
        take = min(end - start, max_seconds - total)
        a = int(start * sample_rate)
        b = int((start + take) * sample_rate)
        if b > a:
            chunks.append(audio[a:b])
            total += take
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two embeddings (they are stored L2-normalized)."""
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))
