"""Durable local job store (SQLite).

Keeps job state, the synchronization outbox and the set of consumed token
nonces. Survives agent restarts and network interruptions.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

JOB_STATES = (
    "CREATED",
    "RECEIVING_AUDIO",
    "PREPROCESSING",
    "DIARIZING",
    "TRANSCRIBING",
    "FINALIZING",
    "SYNCING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)
TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED"}
SYNC_STATES = ("NOT_STARTED", "WAITING_TO_SYNC", "SYNCING", "SYNCED", "SYNC_FAILED")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobRecord:
    job_id: str
    session_id: str
    recording_id: str
    user_id: str
    state: str = "CREATED"
    sync_state: str = "NOT_STARTED"
    progress: float = 0.0
    message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    failure_stage: str | None = None
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)
    completed_at: str | None = None
    original_filename: str = ""
    original_path: str | None = None
    processing_path: str | None = None
    result_path: str | None = None
    idempotency_key: str | None = None
    sync_attempts: int = 0
    last_sync_error: str | None = None
    next_sync_at: str | None = None
    result_synced: bool = False
    audio_synced: bool = False
    speaker_count: int | None = None
    segment_count: int | None = None
    warnings: list[str] = field(default_factory=list)
    audio_metadata: dict[str, Any] = field(default_factory=dict)
    cancel_requested: bool = False

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("original_path", None)
        d.pop("processing_path", None)
        d.pop("result_path", None)
        return d


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    recording_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    state TEXT NOT NULL,
    sync_state TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    message TEXT,
    error_code TEXT,
    error_message TEXT,
    failure_stage TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    original_filename TEXT NOT NULL DEFAULT '',
    original_path TEXT,
    processing_path TEXT,
    result_path TEXT,
    idempotency_key TEXT,
    sync_attempts INTEGER NOT NULL DEFAULT 0,
    last_sync_error TEXT,
    next_sync_at TEXT,
    result_synced INTEGER NOT NULL DEFAULT 0,
    audio_synced INTEGER NOT NULL DEFAULT 0,
    speaker_count INTEGER,
    segment_count INTEGER,
    warnings TEXT NOT NULL DEFAULT '[]',
    audio_metadata TEXT NOT NULL DEFAULT '{}',
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS job_tokens (
    job_id TEXT PRIMARY KEY,
    token TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nonces (
    nonce TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_jobs_sync ON jobs(sync_state, next_sync_at);
"""


class JobStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self._conn.executescript(_SCHEMA)

    # ---------------------------------------------------------------- settings
    def get_setting(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, value))

    # ------------------------------------------------------------------ nonces
    def consume_nonce(self, nonce: str, job_id: str, expires_at: datetime) -> bool:
        """Atomically record a token nonce. Returns False if it was already used."""
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO nonces(nonce, job_id, seen_at, expires_at) VALUES (?, ?, ?, ?)",
                    (nonce, job_id, utcnow(), expires_at.isoformat()),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def purge_nonces(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM nonces WHERE expires_at < ?", (utcnow(),))

    # ------------------------------------------------------------------ tokens
    def save_token(self, job_id: str, token: str, expires_at: datetime) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO job_tokens(job_id, token, expires_at) VALUES (?, ?, ?)",
                (job_id, token, expires_at.isoformat()),
            )

    def get_token(self, job_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT token FROM job_tokens WHERE job_id=?", (job_id,)).fetchone()
        return row["token"] if row else None

    def delete_token(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM job_tokens WHERE job_id=?", (job_id,))

    # -------------------------------------------------------------------- jobs
    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobRecord:
        d = dict(row)
        d["warnings"] = json.loads(d.get("warnings") or "[]")
        d["audio_metadata"] = json.loads(d.get("audio_metadata") or "{}")
        d["result_synced"] = bool(d["result_synced"])
        d["audio_synced"] = bool(d["audio_synced"])
        d["cancel_requested"] = bool(d["cancel_requested"])
        return JobRecord(**d)

    def create(self, job: JobRecord) -> None:
        self.save(job)

    def save(self, job: JobRecord) -> None:
        job.updated_at = utcnow()
        d = asdict(job)
        d["warnings"] = json.dumps(d["warnings"], ensure_ascii=False)
        d["audio_metadata"] = json.dumps(d["audio_metadata"], ensure_ascii=False)
        d["result_synced"] = int(d["result_synced"])
        d["audio_synced"] = int(d["audio_synced"])
        with self._lock:
            # The cancel flag is owned by request_cancel(); never let a stale
            # in-memory copy clear it.
            row = self._conn.execute("SELECT cancel_requested FROM jobs WHERE job_id=?", (job.job_id,)).fetchone()
            if row and row["cancel_requested"]:
                job.cancel_requested = True
            d["cancel_requested"] = int(job.cancel_requested)
            cols = ", ".join(d.keys())
            marks = ", ".join("?" for _ in d)
            self._conn.execute(f"INSERT OR REPLACE INTO jobs({cols}) VALUES ({marks})", tuple(d.values()))

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list(self, limit: int = 100) -> list[JobRecord]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_job(r) for r in rows]

    def active(self) -> list[JobRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE state NOT IN ('COMPLETED','FAILED','CANCELLED') ORDER BY created_at"
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def pending_sync(self) -> list[JobRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE sync_state IN ('WAITING_TO_SYNC','SYNC_FAILED','SYNCING') "
                "AND state = 'COMPLETED' ORDER BY created_at"
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def request_cancel(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE jobs SET cancel_requested=1, updated_at=? WHERE job_id=?", (utcnow(), job_id))

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT cancel_requested FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
            self._conn.execute("DELETE FROM job_tokens WHERE job_id=?", (job_id,))

    def close(self) -> None:
        with self._lock:
            self._conn.close()
