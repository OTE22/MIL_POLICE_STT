"""Durable synchronization: local result -> central FastAPI -> PostgreSQL.

Every completed job has a JSON result on disk and a row in SQLite. The worker
retries failed submissions with exponential backoff; `idempotency_key` makes a
retried submission safe on the central side (duplicate -> same answer).
States: WAITING_TO_SYNC -> SYNCING -> SYNCED | SYNC_FAILED (retry later).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings
from app.jobs.store import JobRecord, JobStore, utcnow
from app.sync.central_client import CentralClient, CentralError

log = logging.getLogger(__name__)


class SyncWorker:
    def __init__(self, settings: Settings, store: JobStore, client: CentralClient, workstation_info_provider):
        self._settings = settings
        self._store = store
        self._client = client
        self._ws_info = workstation_info_provider
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="sync-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("sync loop error")
            self._wake.wait(timeout=10.0)
            self._wake.clear()

    # ------------------------------------------------------------ core
    def run_once(self) -> int:
        """Try every job that is due. Returns the number of jobs fully synced."""
        if not self._client.enabled:
            return 0
        synced = 0
        now = datetime.now(timezone.utc)
        for job in self._store.pending_sync():
            if job.next_sync_at and datetime.fromisoformat(job.next_sync_at) > now:
                continue
            if self.sync_job(job):
                synced += 1
        return synced

    def _backoff(self, attempts: int) -> float:
        base = self._settings.sync_backoff_base_seconds * (2 ** max(0, attempts - 1))
        return min(base, self._settings.sync_backoff_max_seconds)

    def sync_job(self, job: JobRecord) -> bool:
        token = self._store.get_token(job.job_id)
        if token is None:
            job.sync_state = "SYNC_FAILED"
            job.last_sync_error = "processing token missing locally"
            self._store.save(job)
            return False
        job.sync_state = "SYNCING"
        job.sync_attempts += 1
        self._store.save(job)
        try:
            if not job.result_synced:
                result = json.loads(Path(job.result_path).read_text(encoding="utf-8"))
                result["workstation"] = self._ws_info()
                resp = self._client.submit_result(job.job_id, token, result)
                job.result_synced = True
                if resp.get("duplicate"):
                    log.info("job %s result already known centrally (idempotent)", job.job_id)
                self._store.save(job)
            if self._settings.central_upload_audio and not job.audio_synced:
                if job.original_path and Path(job.original_path).exists():
                    meta = job.audio_metadata or {}
                    self._client.upload_audio(
                        job.job_id,
                        token,
                        Path(job.original_path),
                        meta.get("original_filename") or job.original_filename or "recording.wav",
                        meta.get("mime_type") or "application/octet-stream",
                    )
                    job.audio_synced = True
                else:
                    job.warnings = list(job.warnings) + ["original audio no longer available locally; upload skipped"]
                    job.audio_synced = True
            job.sync_state = "SYNCED"
            job.last_sync_error = None
            job.next_sync_at = None
            job.message = "synced"
            self._store.save(job)
            self._store.delete_token(job.job_id)
            log.info("job %s synchronized with central", job.job_id)
            return True
        except CentralError as exc:
            job.last_sync_error = exc.message[:500]
            if exc.permanent and exc.code not in ("network",):
                # e.g. token expired / job cancelled centrally: retrying will never help.
                job.sync_state = "SYNC_FAILED"
                job.next_sync_at = None
                job.message = f"sync rejected: {exc.code}"
                log.error("job %s sync permanently rejected: %s", job.job_id, exc.message)
            else:
                max_attempts = self._settings.sync_max_attempts
                if max_attempts and job.sync_attempts >= max_attempts:
                    job.sync_state = "SYNC_FAILED"
                    job.next_sync_at = None
                else:
                    job.sync_state = "WAITING_TO_SYNC"
                    delay = self._backoff(job.sync_attempts)
                    job.next_sync_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                    job.message = f"retrying sync in {int(delay)}s"
                log.warning("job %s sync failed (attempt %s): %s", job.job_id, job.sync_attempts, exc.message)
            self._store.save(job)
            return False
        except Exception as exc:  # noqa: BLE001
            job.sync_state = "WAITING_TO_SYNC"
            job.last_sync_error = str(exc)[:500]
            job.next_sync_at = (datetime.now(timezone.utc) + timedelta(seconds=self._backoff(job.sync_attempts))).isoformat()
            self._store.save(job)
            log.exception("unexpected sync error for %s", job.job_id)
            return False

    def wait_until_idle(self, timeout: float = 5.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline and any(j.sync_state == "SYNCING" for j in self._store.pending_sync()):
            time.sleep(0.1)


__all__ = ["SyncWorker", "utcnow"]
