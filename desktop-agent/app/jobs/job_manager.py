"""Job manager: accepts authorized jobs, runs them one at a time, cleans up temp files."""

from __future__ import annotations

import logging
import queue
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import __version__
from app.ai.runtime import ModelRuntime
from app.audio.preprocessing import extension_of, sanitize_filename
from app.config import Settings
from app.jobs.pipeline import JobPipeline
from app.jobs.store import TERMINAL_STATES, JobRecord, JobStore
from app.security.token_validation import ProcessingClaims
from app.sync.central_client import CentralClient
from app.sync.sync_worker import SyncWorker

log = logging.getLogger(__name__)


class JobManager:
    def __init__(self, settings: Settings, store: JobStore, runtime: ModelRuntime, client: CentralClient):
        self._settings = settings
        self._store = store
        self._runtime = runtime
        self._client = client
        self._queue: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._current: str | None = None
        self._agent_id = self._load_agent_id()
        self.sync = SyncWorker(settings, store, client, self.workstation_info)
        self._pipeline = JobPipeline(settings, store, runtime, client, self.workstation_info)
        self._started_at = time.time()

    # ---------------------------------------------------------------- identity
    def _load_agent_id(self) -> str:
        if self._settings.agent_id:
            return self._settings.agent_id
        existing = self._store.get_setting("agent_id")
        if existing:
            return existing
        new_id = f"agent-{uuid.uuid4().hex[:16]}"
        self._store.set_setting("agent_id", new_id)
        return new_id

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._started_at

    def workstation_info(self) -> dict:
        status = self._runtime.status()
        return {
            "agent_id": self._agent_id,
            "device_name": self._settings.device_name,
            "agent_version": __version__,
            "stt_provider": status["stt"]["provider"],
            "stt_model": status["stt"]["model"],
            "stt_model_revision": status["stt"]["revision"],
            "diarization_provider": status["diarization"]["provider"],
            "diarization_model": status["diarization"]["model"],
            "diarization_model_revision": status["diarization"]["revision"],
            "processing_device": status["processing_device"],
            "gpu_name": status["gpu_name"],
            "stt_ready": status["stt"]["state"] == "READY",
            "diarization_ready": status["diarization"]["state"] == "READY",
        }

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        # Jobs interrupted by a restart cannot be resumed safely: mark them failed.
        for job in self._store.active():
            if job.state not in ("COMPLETED",):
                job.state = "FAILED"
                job.error_code = "agent_restarted"
                job.error_message = "the local agent was restarted during processing"
                job.failure_stage = job.state
                job.completed_at = datetime.now(timezone.utc).isoformat()
                self._store.save(job)
        self._worker = threading.Thread(target=self._run, name="job-worker", daemon=True)
        self._worker.start()
        self.sync.start()
        threading.Thread(target=self._cleanup_loop, name="cleanup", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.sync.stop()

    @property
    def busy(self) -> bool:
        return self._current is not None or not self._queue.empty()

    @property
    def current_job_id(self) -> str | None:
        return self._current

    # ---------------------------------------------------------------- jobs
    def job_dir(self, job_id: str) -> Path:
        safe = str(uuid.UUID(job_id))  # raises on tampering
        path = (self._settings.jobs_dir / safe).resolve()
        if self._settings.jobs_dir.resolve() not in path.parents:
            raise ValueError("invalid job path")
        return path

    def create_job(self, claims: ProcessingClaims, filename: str, mime_type: str) -> JobRecord:
        if self._store.get(claims.job_id) is not None:
            raise ValueError("job_exists")
        ext = extension_of(filename) or "bin"
        job_dir = self.job_dir(claims.job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        original = job_dir / f"original.{ext}"
        job = JobRecord(
            job_id=claims.job_id,
            session_id=claims.session_id,
            recording_id=claims.recording_id,
            user_id=claims.user_id,
            state="CREATED",
            original_filename=sanitize_filename(filename),
            original_path=str(original),
            audio_metadata={"mime_type": mime_type, "original_filename": sanitize_filename(filename)},
            idempotency_key=uuid.uuid4().hex,
        )
        self._store.create(job)
        self._store.save_token(job.job_id, claims.raw, claims.expires_at)
        return job

    def mark_receiving(self, job: JobRecord) -> None:
        job.state = "RECEIVING_AUDIO"
        job.progress = 0.02
        job.message = "receiving audio"
        self._store.save(job)
        token = self._store.get_token(job.job_id)
        if token:
            self._client.report_state(job.job_id, token, "CREATED", progress=0.0, workstation=self.workstation_info())
            self._client.report_state(job.job_id, token, "RECEIVING_AUDIO", progress=0.02, workstation=self.workstation_info())

    def enqueue(self, job: JobRecord) -> None:
        job.progress = 0.08
        job.message = "queued for processing"
        self._store.save(job)
        self._queue.put(job.job_id)

    def discard(self, job: JobRecord, code: str, message: str) -> None:
        job.state = "FAILED"
        job.error_code = code
        job.error_message = message
        job.failure_stage = "RECEIVING_AUDIO"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        self._store.save(job)
        token = self._store.get_token(job.job_id)
        if token:
            self._client.report_state(job.job_id, token, "FAILED", message=f"{code}: {message}", failure_stage="RECEIVING_AUDIO")
        shutil.rmtree(self.job_dir(job.job_id), ignore_errors=True)

    def cancel(self, job_id: str) -> JobRecord | None:
        job = self._store.get(job_id)
        if job is None:
            return None
        if job.state in TERMINAL_STATES:
            return job
        self._store.request_cancel(job_id)
        if self._current != job_id:
            # Not running yet: cancel immediately.
            job = self._store.get(job_id)
            job.state = "CANCELLED"
            job.completed_at = datetime.now(timezone.utc).isoformat()
            job.message = "cancelled"
            self._store.save(job)
            token = self._store.get_token(job_id)
            if token:
                self._client.report_state(job_id, token, "CANCELLED", message="cancelled by user")
        return self._store.get(job_id)

    def get(self, job_id: str) -> JobRecord | None:
        return self._store.get(job_id)

    def list(self) -> list[JobRecord]:
        return self._store.list()

    # ---------------------------------------------------------------- worker
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            job = self._store.get(job_id)
            if job is None or job.state in TERMINAL_STATES:
                continue
            self._current = job_id
            try:
                self._pipeline.run(job)
            finally:
                self._current = None
                self.sync.wake()

    def _cleanup_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.cleanup_once()
            except Exception:  # noqa: BLE001
                log.exception("cleanup error")
            self._stop.wait(1800)

    def cleanup_once(self) -> int:
        """Remove temporary files of finished, synchronized jobs older than the retention."""
        removed = 0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._settings.temp_retention_hours)
        self._store.purge_nonces()
        for job in self._store.list(limit=1000):
            if job.state not in TERMINAL_STATES:
                continue
            if job.state == "COMPLETED" and job.sync_state not in ("SYNCED", "NOT_STARTED"):
                continue  # keep files until synced
            finished = datetime.fromisoformat(job.completed_at or job.updated_at)
            if finished > cutoff:
                continue
            try:
                d = self.job_dir(job.job_id)
            except ValueError:
                continue
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
            job.original_path = None
            job.processing_path = None
            job.result_path = None
            self._store.save(job)
        return removed
