"""Synchronization queue: retry after network failure, idempotency, permanent rejection."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.config import Settings
from app.jobs.store import JobRecord, JobStore
from app.sync.sync_worker import SyncWorker
from tests.conftest import FakeCentral, write_wav


def _completed_job(settings: Settings, store: JobStore, tmp_path, job_id="11111111-1111-1111-1111-111111111111") -> JobRecord:
    d = tmp_path / "job"
    d.mkdir(exist_ok=True)
    original = write_wav(d / "original.wav", 1.0)
    result = {"idempotency_key": "k" * 16, "segments": [], "stt_model": "x", "diarization_model": "y"}
    (d / "result.json").write_text(json.dumps(result), encoding="utf-8")
    job = JobRecord(
        job_id=job_id,
        session_id="s",
        recording_id="r",
        user_id="u",
        state="COMPLETED",
        sync_state="WAITING_TO_SYNC",
        original_filename="original.wav",
        original_path=str(original),
        result_path=str(d / "result.json"),
        idempotency_key=result["idempotency_key"],
        audio_metadata={"original_filename": "original.wav", "mime_type": "audio/wav"},
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    store.save(job)
    store.save_token(job.job_id, "token", datetime(2999, 1, 1, tzinfo=timezone.utc))
    return job


def test_retry_after_network_failure(settings: Settings, tmp_path):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = JobStore(settings.db_path)
    central = FakeCentral(fail_times=2)
    worker = SyncWorker(settings, store, central, lambda: {"agent_id": "a"})
    job = _completed_job(settings, store, tmp_path)

    assert worker.sync_job(store.get(job.job_id)) is False
    j = store.get(job.job_id)
    assert j.sync_state == "WAITING_TO_SYNC" and j.sync_attempts == 1 and j.next_sync_at
    assert worker.sync_job(store.get(job.job_id)) is False
    assert worker.sync_job(store.get(job.job_id)) is True
    j = store.get(job.job_id)
    assert j.sync_state == "SYNCED" and j.sync_attempts == 3 and j.result_synced and j.audio_synced
    assert central.result_calls == 3 and job.job_id in central.audio
    store.close()


def test_duplicate_submission_is_idempotent(settings: Settings, tmp_path):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = JobStore(settings.db_path)
    central = FakeCentral()
    worker = SyncWorker(settings, store, central, lambda: {"agent_id": "a"})
    job = _completed_job(settings, store, tmp_path)
    assert worker.sync_job(store.get(job.job_id)) is True
    # Simulate a lost acknowledgement: the agent retries the same result.
    j = store.get(job.job_id)
    j.sync_state = "WAITING_TO_SYNC"
    j.result_synced = False
    store.save(j)
    store.save_token(job.job_id, "token", datetime(2999, 1, 1, tzinfo=timezone.utc))
    assert worker.sync_job(store.get(job.job_id)) is True
    assert central.result_calls == 2 and len(central.results) == 1
    store.close()


def test_permanent_rejection_stops_retries(settings: Settings, tmp_path):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = JobStore(settings.db_path)
    central = FakeCentral(permanent_error="job_cancelled")
    worker = SyncWorker(settings, store, central, lambda: {"agent_id": "a"})
    job = _completed_job(settings, store, tmp_path)
    assert worker.sync_job(store.get(job.job_id)) is False
    j = store.get(job.job_id)
    assert j.sync_state == "SYNC_FAILED" and j.next_sync_at is None
    assert worker.run_once() == 0  # not retried automatically
    store.close()


def test_run_once_respects_backoff(settings: Settings, tmp_path):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.sync_backoff_base_seconds = 3600
    store = JobStore(settings.db_path)
    central = FakeCentral(fail_times=1)
    worker = SyncWorker(settings, store, central, lambda: {"agent_id": "a"})
    _completed_job(settings, store, tmp_path)
    assert worker.run_once() == 0  # first attempt fails
    assert worker.run_once() == 0  # backoff not elapsed -> not attempted
    assert central.result_calls == 1
    store.close()


def test_store_survives_reopen(settings: Settings, tmp_path):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = JobStore(settings.db_path)
    job = _completed_job(settings, store, tmp_path)
    store.close()
    store2 = JobStore(settings.db_path)
    assert store2.get(job.job_id).sync_state == "WAITING_TO_SYNC"
    assert store2.get_token(job.job_id) == "token"
    assert len(store2.pending_sync()) == 1
    store2.close()
