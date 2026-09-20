"""The local processing pipeline for one job.

Original Audio -> validation -> FFmpeg 16 kHz mono copy -> VAD ->
NVIDIA diarization (who spoke when) -> segment post-processing ->
Cohere Arabic STT per segment (what was said) -> structured result -> sync.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app import __version__
from app.ai.diarization_service import DiarizationError
from app.ai.runtime import ModelRuntime
from app.ai.segment_service import SegmentSettings, plan_segments
from app.ai.transcription_service import TranscriptionError
from app.ai.types import TranscriptSegment
from app.audio.preprocessing import AudioValidationError, make_processing_copy, validate_original
from app.config import Settings
from app.jobs.store import JobRecord, JobStore
from app.sync.central_client import CentralClient

log = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


class PipelineFailure(Exception):
    def __init__(self, code: str, message: str, stage: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage


class JobPipeline:
    def __init__(self, settings: Settings, store: JobStore, runtime: ModelRuntime, client: CentralClient, workstation_info_provider):
        self._settings = settings
        self._store = store
        self._runtime = runtime
        self._client = client
        self._ws_info = workstation_info_provider

    # ------------------------------------------------------------ helpers
    def _token(self, job: JobRecord) -> str | None:
        return self._store.get_token(job.job_id)

    def _set_state(self, job: JobRecord, state: str, progress: float, message: str | None = None, *, report: bool = True) -> None:
        self._check_cancel(job)
        job.state = state
        job.progress = progress
        job.message = message
        self._store.save(job)
        token = self._token(job)
        if report and token:
            self._client.report_state(job.job_id, token, state, progress=progress, message=message, workstation=self._ws_info())

    def _progress(self, job: JobRecord, progress: float, message: str | None = None) -> None:
        self._check_cancel(job)
        job.progress = progress
        if message:
            job.message = message
        self._store.save(job)

    def _check_cancel(self, job: JobRecord) -> None:
        if self._store.is_cancel_requested(job.job_id):
            raise JobCancelled()

    # ------------------------------------------------------------ stages
    def run(self, job: JobRecord) -> JobRecord:
        started = time.time()
        try:
            audio_meta, processing_path, duration = self._stage_preprocess(job)
            turns, speech = self._stage_diarize(job, processing_path, duration)
            segments, timings = self._stage_transcribe(job, processing_path, turns, speech, duration)
            voice = self._stage_identify_speakers(job, processing_path, segments)
            self._stage_finalize(job, audio_meta, duration, turns, segments, timings, started, voice)
            self._stage_sync(job)
        except JobCancelled:
            job.state = "CANCELLED"
            job.completed_at = datetime.now(timezone.utc).isoformat()
            job.message = "cancelled"
            self._store.save(job)
            token = self._token(job)
            if token:
                self._client.report_state(job.job_id, token, "CANCELLED", message="cancelled by user")
            self._cleanup_processing(job)
        except PipelineFailure as exc:
            self._fail(job, exc.code, exc.message, exc.stage)
        except Exception as exc:  # noqa: BLE001
            log.exception("unexpected pipeline error for %s", job.job_id)
            self._fail(job, "agent_processing", str(exc)[:300], job.state)
        return job

    def _fail(self, job: JobRecord, code: str, message: str, stage: str) -> None:
        job.state = "FAILED"
        job.error_code = code
        job.error_message = message
        job.failure_stage = stage
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.message = message
        self._store.save(job)
        token = self._token(job)
        if token:
            self._client.report_state(job.job_id, token, "FAILED", message=f"{code}: {message}", failure_stage=stage, workstation=self._ws_info())
        self._cleanup_processing(job)
        log.error("job %s failed at %s: %s (%s)", job.job_id, stage, code, message)

    def _stage_preprocess(self, job: JobRecord):
        self._set_state(job, "PREPROCESSING", 0.12, "validating audio")
        original = Path(job.original_path)
        try:
            meta = validate_original(original, job.original_filename, job.audio_metadata.get("mime_type", ""), self._settings)
        except AudioValidationError as exc:
            raise PipelineFailure(exc.code, exc.message, "PREPROCESSING") from exc
        job.audio_metadata = asdict(meta)
        self._store.save(job)
        processing_path = original.parent / "processing_16k_mono.wav"
        self._progress(job, 0.16, "creating 16 kHz mono processing copy")
        try:
            duration = make_processing_copy(original, processing_path)
        except Exception as exc:  # noqa: BLE001
            raise PipelineFailure("malformed_audio", str(exc)[:300], "PREPROCESSING") from exc
        if duration < self._settings.min_duration_seconds:
            raise PipelineFailure("audio_too_short", f"duration {duration:.2f}s", "PREPROCESSING")
        job.audio_metadata["duration_seconds"] = round(duration, 3)
        job.processing_path = str(processing_path)
        self._store.save(job)
        return meta, processing_path, duration

    def _stage_diarize(self, job: JobRecord, wav: Path, duration: float):
        self._set_state(job, "DIARIZING", 0.22, "loading diarization model")
        try:
            self._runtime.diarization.load()
            if self._settings.vad_enabled:
                self._runtime.vad.load()
        except DiarizationError as exc:
            raise PipelineFailure(exc.code, exc.message, "DIARIZING") from exc
        except Exception as exc:  # noqa: BLE001
            raise PipelineFailure("diarization_model_load_failed", str(exc)[:300], "DIARIZING") from exc
        self._progress(job, 0.26, "voice activity detection")
        try:
            speech = self._runtime.vad.detect(wav, duration)
        except Exception as exc:  # noqa: BLE001
            raise PipelineFailure("vad_failed", str(exc)[:300], "DIARIZING") from exc
        if not speech:
            raise PipelineFailure("no_speech_detected", "no speech regions found by VAD", "DIARIZING")
        self._progress(job, 0.3, "speaker diarization (who spoke when)")
        try:
            turns = self._runtime.diarization.diarize(wav)
        except DiarizationError as exc:
            raise PipelineFailure(exc.code, exc.message, "DIARIZING") from exc
        if not turns:
            raise PipelineFailure("no_speakers_detected", "diarization produced no speaker turns", "DIARIZING")
        self._progress(job, 0.45, f"{len({t.speaker_label for t in turns})} speaker(s) detected")
        return turns, speech

    def _stage_transcribe(self, job: JobRecord, wav: Path, turns, speech, duration: float):
        self._set_state(job, "TRANSCRIBING", 0.48, "loading Arabic speech-to-text model")
        try:
            self._runtime.transcription.load()
        except TranscriptionError as exc:
            raise PipelineFailure(exc.code, exc.message, "TRANSCRIBING") from exc
        except Exception as exc:  # noqa: BLE001
            raise PipelineFailure("stt_model_load_failed", str(exc)[:300], "TRANSCRIBING") from exc
        s = self._settings
        plans = plan_segments(
            turns,
            speech,
            duration,
            SegmentSettings(
                min_turn_seconds=s.segment_min_turn_seconds,
                merge_gap_seconds=s.segment_merge_gap_seconds,
                max_seconds=s.segment_max_seconds,
                context_padding_seconds=s.segment_context_padding_seconds,
            ),
            vad_enabled=s.vad_enabled,
        )
        if not plans:
            raise PipelineFailure("no_speech_detected", "no speech segments after post-processing", "TRANSCRIBING")
        import soundfile as sf

        audio, sr = sf.read(str(wav), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        segments: list[TranscriptSegment] = []
        t0 = time.time()
        empty = 0
        for index, plan in enumerate(plans):
            self._progress(job, 0.5 + 0.4 * (index / len(plans)), f"transcribing segment {index + 1}/{len(plans)}")
            a = int(plan.window_start * sr)
            b = int(plan.window_end * sr)
            clip = audio[a:b]
            if clip.size < int(0.1 * sr):
                continue
            try:
                result = self._runtime.transcription.transcribe(clip, sr)
            except TranscriptionError as exc:
                raise PipelineFailure(exc.code, exc.message, "TRANSCRIBING") from exc
            if not result.text:
                empty += 1
                continue
            segments.append(
                TranscriptSegment(
                    speaker_label=plan.speaker_label,
                    start_seconds=plan.start_seconds,
                    end_seconds=plan.end_seconds,
                    text=result.text,
                    is_overlap=plan.is_overlap,
                    confidence=result.confidence,
                    window_start_seconds=plan.window_start,
                    window_end_seconds=plan.window_end,
                )
            )
        timings = {"stt_seconds": round(time.time() - t0, 2), "planned_segments": len(plans), "empty_segments": empty}
        if not segments:
            raise PipelineFailure("transcription_empty", "the STT model returned no text for any segment", "TRANSCRIBING")
        return segments, timings

    def _stage_identify_speakers(self, job: JobRecord, wav: Path, segments: list[TranscriptSegment]) -> dict:
        """One voice embedding per anonymous speaker (optional, never fatal).

        The embedding is sent to the central server, which compares it against the
        enrolled voices and records a *suggestion*. No name is decided here.
        """
        if not self._settings.speaker_id_enabled:
            return {}
        self._check_cancel(job)
        try:
            self._runtime.speaker_id.load()
        except Exception as exc:  # noqa: BLE001
            log.warning("job %s: speaker identification unavailable: %s", job.job_id, exc)
            return {}

        import soundfile as sf

        from app.ai.speaker_id_service import SpeakerIdentificationError, collect_speaker_audio, clean_speaker_spans

        spans = clean_speaker_spans(segments)

        audio, sr = sf.read(str(wav), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        embeddings: dict[str, dict] = {}
        for label, label_spans in sorted(spans.items()):
            raw_seconds = sum(end - start for start, end in label_spans)
            clip = collect_speaker_audio(audio, sr, label_spans, self._settings.speaker_id_max_seconds)
            seconds = len(clip) / float(sr)
            embed_started = time.perf_counter()
            try:
                vec = self._runtime.speaker_id.embed(clip, sr)
            except SpeakerIdentificationError as exc:
                log.info(
                    "job %s: no embedding for %s (%s) - %d span(s), %.1fs of speech",
                    job.job_id, label, exc.code, len(label_spans), raw_seconds,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                log.warning("job %s: embedding failed for %s: %s", job.job_id, label, exc)
                continue
            # The full story of this voiceprint, WITHOUT the vector itself: how much speech
            # existed, how much of it was used (longest turns first, capped), and that the
            # result is unit-length - the property cosine similarity depends on.
            norm = float((vec * vec).sum()) ** 0.5
            log.info(
                "job %s: speaker %s embedded: %d span(s), %.1fs speech, %.1fs used (cap %.0fs) "
                "-> dim=%d norm=%.4f in %dms",
                job.job_id, label, len(label_spans), raw_seconds, seconds,
                self._settings.speaker_id_max_seconds, len(vec), norm,
                int((time.perf_counter() - embed_started) * 1000),
            )
            embeddings[label] = {"embedding": [round(float(x), 6) for x in vec], "seconds": round(seconds, 2)}
        if embeddings:
            info = self._runtime.speaker_id.info()
            log.info("job %s: %d speaker embedding(s) computed", job.job_id, len(embeddings))
            return {
                "provider": info.provider,
                "model": info.model,
                "model_revision": info.revision,
                "embedding_dim": self._runtime.speaker_id.embedding_dim,
                "device": self._runtime.speaker_id.device,
                "speakers": embeddings,
            }
        return {}

    def _stage_finalize(self, job: JobRecord, audio_meta, duration: float, turns, segments: list[TranscriptSegment], timings: dict, started: float, voice: dict | None = None) -> None:
        self._set_state(job, "FINALIZING", 0.92, "building structured transcript")
        labels = sorted({seg.speaker_label for seg in segments})
        warnings: list[str] = []
        if len(labels) >= self._runtime.max_speakers:
            warnings.append(
                f"The diarization model supports at most {self._runtime.max_speakers} speakers; "
                f"{len(labels)} were detected. Additional speakers may be merged."
            )
        if timings.get("empty_segments"):
            warnings.append(f"{timings['empty_segments']} speech segment(s) produced no text and were dropped.")
        if self._runtime.transcription.device == "cpu":
            warnings.append("Processed on CPU.")
        stt_info = self._runtime.transcription.info()
        dia_info = self._runtime.diarization.info()
        result = {
            "idempotency_key": job.idempotency_key or uuid.uuid4().hex,
            "language": self._settings.stt_language,
            "stt_provider": stt_info.provider,
            "stt_model": stt_info.model,
            "stt_model_revision": stt_info.revision,
            "diarization_provider": dia_info.provider,
            "diarization_model": dia_info.model,
            "diarization_model_revision": dia_info.revision,
            "vad_model": self._runtime.vad.model_name if self._settings.vad_enabled else None,
            "agent_version": __version__,
            "processing_device": self._runtime.transcription.device,
            "speaker_count": len(labels),
            "warnings": warnings,
            "processing_metadata": {
                "agent_id": self._ws_info().get("agent_id"),
                "device_name": self._settings.device_name,
                "duration_seconds": round(duration, 3),
                "diarization_turns": len(turns),
                "overlap_turns": sum(1 for t in turns if t.is_overlap),
                "segments": len(segments),
                "timings": {**timings, "total_seconds": round(time.time() - started, 2)},
                "vad": {
                    "enabled": self._settings.vad_enabled,
                    "threshold": self._settings.vad_threshold,
                    "min_speech_ms": self._settings.vad_min_speech_ms,
                    "min_silence_ms": self._settings.vad_min_silence_ms,
                },
                "segmenting": {
                    "min_turn_seconds": self._settings.segment_min_turn_seconds,
                    "merge_gap_seconds": self._settings.segment_merge_gap_seconds,
                    "max_seconds": self._settings.segment_max_seconds,
                    "context_padding_seconds": self._settings.segment_context_padding_seconds,
                },
                "diarization_streaming": dia_info.extra.get("streaming"),
                "speaker_identification": {
                    "enabled": self._settings.speaker_id_enabled,
                    "embeddings": len((voice or {}).get("speakers", {})),
                    "model": (voice or {}).get("model"),
                },
            },
            "audio": {
                "original_filename": audio_meta.original_filename,
                "mime_type": audio_meta.mime_type,
                "size_bytes": audio_meta.size_bytes,
                "duration_seconds": round(duration, 3),
                "sha256": audio_meta.sha256,
            },
            "voice_identification": voice or None,
            "segments": [
                {
                    "speaker_label": seg.speaker_label,
                    "start_seconds": seg.start_seconds,
                    "end_seconds": seg.end_seconds,
                    "text": seg.text,
                    "confidence": seg.confidence,
                    "is_overlap": seg.is_overlap,
                }
                for seg in segments
            ],
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        job.idempotency_key = result["idempotency_key"]
        result_path = Path(job.original_path).parent / "result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        job.result_path = str(result_path)
        job.speaker_count = len(labels)
        job.segment_count = len(segments)
        job.warnings = warnings
        job.completed_at = datetime.now(timezone.utc).isoformat()
        self._store.save(job)
        self._cleanup_processing(job)

    def _stage_sync(self, job: JobRecord) -> None:
        job.state = "SYNCING"
        job.progress = 0.96
        job.message = "sending results to central server"
        job.sync_state = "WAITING_TO_SYNC" if self._client.enabled else "NOT_STARTED"
        self._store.save(job)
        # The sync worker performs the actual upload (with retries). Mark the
        # processing itself as completed; the UI shows sync_state separately.
        job.state = "COMPLETED"
        job.progress = 1.0
        self._store.save(job)

    def _cleanup_processing(self, job: JobRecord) -> None:
        if job.processing_path:
            try:
                Path(job.processing_path).unlink(missing_ok=True)
            except OSError:
                pass


def load_audio_clip(path: Path, start: float, end: float) -> tuple[np.ndarray, int]:
    import soundfile as sf

    info = sf.info(str(path))
    sr = info.samplerate
    a = max(0, int(start * sr))
    b = min(info.frames, int(end * sr))
    data, _ = sf.read(str(path), start=a, stop=b, dtype="float32", always_2d=False)
    return data, sr
