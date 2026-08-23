"""Arabic speech-to-text: WHAT WAS SAID.

Provider abstraction + the default local Cohere adapter
(CohereLabs/cohere-transcribe-arabic-07-2026 through Hugging Face Transformers,
loaded from the offline model directory with local_files_only=True).

No cloud API is used. If the model is not provisioned or fails to load, the
job fails with an explicit error - there is no fallback engine.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import numpy as np

from app.ai.device import resolve_device, resolve_dtype
from app.ai.model_files import model_files_status
from app.ai.types import ModelInfo, TranscriptionResult
from app.config import Settings

log = logging.getLogger(__name__)


class TranscriptionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class TranscriptionService(ABC):
    provider: str = "abstract"

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> TranscriptionResult: ...

    @abstractmethod
    def info(self) -> ModelInfo: ...

    @property
    def device(self) -> str:
        return "cpu"


class CohereLocalTranscriptionService(TranscriptionService):
    provider = "cohere_local"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model = None
        self._processor = None
        self._lock = threading.Lock()
        self._state = "PROVISIONED" if self._files_present() else "NOT_PROVISIONED"
        self._error: str | None = None
        self._loaded_at: str | None = None
        self._device = "cpu"
        self._dtype_name = "float32"

    def _files_present(self) -> bool:
        d = self._settings.stt_model_dir
        return (d / "config.json").exists() and any(d.glob("*.safetensors"))

    @property
    def device(self) -> str:
        return self._device

    def info(self) -> ModelInfo:
        if self._state == "NOT_PROVISIONED" and self._files_present():
            self._state = "PROVISIONED"
        return ModelInfo(
            name="stt",
            provider=self.provider,
            model=self._settings.stt_model,
            revision=self._settings.stt_model_revision,
            state=self._state,
            error=self._error,
            loaded_at=self._loaded_at,
            extra={"device": self._device, "dtype": self._dtype_name, "language": self._settings.stt_language},
        )

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            model_dir = self._settings.stt_model_dir
            if not self._files_present():
                self._state = "NOT_PROVISIONED"
                self._error = f"model files missing in {model_dir}"
                raise TranscriptionError("stt_model_missing", self._error)
            ok, problem = model_files_status(model_dir, self._settings.verify_model_integrity)
            if not ok:
                self._state = "ERROR"
                self._error = f"integrity check failed: {problem}"
                raise TranscriptionError("stt_model_integrity", self._error)
            self._state = "LOADING"
            try:
                import torch
                from transformers import AutoProcessor, CohereAsrForConditionalGeneration

                self._device = resolve_device(self._settings.stt_device)
                dtype = resolve_dtype(self._settings.stt_dtype, self._device)
                self._dtype_name = str(dtype).replace("torch.", "")
                self._processor = AutoProcessor.from_pretrained(str(model_dir), local_files_only=True)
                model = CohereAsrForConditionalGeneration.from_pretrained(
                    str(model_dir), local_files_only=True, dtype=dtype
                )
                model.to(torch.device(self._device))
                model.eval()
                self._model = model
                self._state = "READY"
                self._error = None
                self._loaded_at = datetime.now(timezone.utc).isoformat()
                log.info("Cohere STT model loaded on %s (%s)", self._device, self._dtype_name)
            except Exception as exc:  # noqa: BLE001
                self._state = "ERROR"
                self._error = str(exc)[:300]
                log.exception("Cohere STT load failed")
                raise TranscriptionError("stt_model_load_failed", self._error) from exc

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> TranscriptionResult:
        self.load()
        import torch

        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = audio.astype(np.float32)
        lang = self._settings.stt_language
        try:
            inputs = self._processor(audio=audio, sampling_rate=sample_rate, return_tensors="pt", language=lang)
            chunk_index = inputs.get("audio_chunk_index") if hasattr(inputs, "get") else None
            inputs = inputs.to(self._model.device, dtype=self._model.dtype)
            with torch.inference_mode():
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=self._settings.stt_max_new_tokens,
                    num_beams=self._settings.stt_num_beams,
                )
            decode_kwargs = {"skip_special_tokens": True}
            if chunk_index is not None:
                decode_kwargs["audio_chunk_index"] = chunk_index
                decode_kwargs["language"] = lang
            text = self._processor.decode(outputs, **decode_kwargs)
        except Exception as exc:  # noqa: BLE001
            log.exception("Cohere STT inference failed")
            raise TranscriptionError("transcription_failed", str(exc)[:300]) from exc
        if isinstance(text, (list, tuple)):
            text = " ".join(str(t) for t in text if t)
        return TranscriptionResult(text=str(text).strip(), confidence=None)


def build_transcription_service(settings: Settings) -> TranscriptionService:
    provider = settings.stt_provider.lower()
    if provider == "cohere_local":
        return CohereLocalTranscriptionService(settings)
    raise ValueError(f"unsupported STT provider: {provider}")
