"""Model runtime: keeps the models resident for the lifetime of the agent.

Lifecycle: agent starts -> (optional preload) -> first job loads what is missing
-> models stay in memory and are reused by every following job.
"""

from __future__ import annotations

import logging
import threading

from app.ai.device import detect_device, resolve_device
from app.ai.diarization_service import DiarizationService, build_diarization_service
from app.ai.speaker_id_service import SpeakerIdentificationService, build_speaker_id_service
from app.ai.transcription_service import TranscriptionService, build_transcription_service
from app.ai.vad_service import VadService
from app.config import MAX_SUPPORTED_SPEAKERS, Settings

log = logging.getLogger(__name__)


class ModelRuntime:
    def __init__(self, settings: Settings):
        self._settings = settings
        self.vad = VadService(settings)
        self.diarization: DiarizationService = build_diarization_service(settings)
        self.transcription: TranscriptionService = build_transcription_service(settings)
        self.speaker_id: SpeakerIdentificationService = build_speaker_id_service(settings)
        self._load_lock = threading.Lock()
        self._loading = False
        self.max_speakers = MAX_SUPPORTED_SPEAKERS

    @property
    def processing_device(self) -> str:
        return resolve_device(self._settings.stt_device)

    def status(self) -> dict:
        dev = detect_device()
        stt = self.transcription.info()
        dia = self.diarization.info()
        vad = self.vad.info()
        spk = self.speaker_id.info()
        return {
            "processing_device": self.processing_device,
            "cuda_available": dev.cuda_available,
            "gpu_name": dev.gpu_name,
            "torch_version": dev.torch_version,
            "cuda_version": dev.cuda_version,
            "stt": stt.__dict__,
            "diarization": dia.__dict__,
            "vad": vad.__dict__,
            "speaker_id": spk.__dict__,
            "ready": stt.state == "READY" and dia.state == "READY",
            "loadable": stt.state in ("READY", "PROVISIONED") and dia.state in ("READY", "PROVISIONED"),
            "loading": self._loading,
            "max_speakers": self.max_speakers,
        }

    def load_all(self) -> None:
        """Load every model (blocking). Raises the first error encountered."""
        with self._load_lock:
            self._loading = True
            try:
                if self._settings.vad_enabled:
                    self.vad.load()
                self.diarization.load()
                self.transcription.load()
                # Optional capability: a failure here must not block transcription.
                if self._settings.speaker_id_enabled:
                    try:
                        self.speaker_id.load()
                    except Exception as exc:  # noqa: BLE001
                        log.warning("speaker identification unavailable: %s", exc)
            finally:
                self._loading = False

    def load_in_background(self) -> bool:
        if self._loading:
            return False

        def _run() -> None:
            try:
                self.load_all()
            except Exception as exc:  # noqa: BLE001
                log.error("Background model loading failed: %s", exc)

        threading.Thread(target=_run, name="model-loader", daemon=True).start()
        return True
