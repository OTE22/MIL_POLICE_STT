"""Shared fixtures for the Local AI Agent test-suite.

Model inference is replaced by deterministic test doubles so that the pipeline,
state machine, security and synchronization logic can be tested without the
multi-GB models. Real-model tests live in tests/test_real_models.py and are
skipped unless the models are provisioned.
"""

from __future__ import annotations

import json
import math
import os
import struct
import sys
import uuid
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import numpy as np
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.types import ModelInfo, SpeakerTurn, TranscriptionResult  # noqa: E402
from app.config import Settings  # noqa: E402


@pytest.fixture
def keypair(tmp_path: Path):
    key = ec.generate_private_key(ec.SECP256R1())
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    pub_path = tmp_path / "central_public_key.pem"
    pub_path.write_text(public_pem)
    return {"private": private_pem, "public": public_pem, "public_path": pub_path}


@pytest.fixture
def settings(tmp_path: Path, keypair) -> Settings:
    os.environ.pop("AGENT_CENTRAL_URL", None)
    return Settings(
        data_dir=tmp_path / "data",
        model_dir=tmp_path / "models",
        central_public_key_path=keypair["public_path"],
        central_url="http://central.test",
        central_sync_enabled=True,
        central_upload_audio=True,
        sync_backoff_base_seconds=0.01,
        sync_backoff_max_seconds=0.02,
        allowed_origins="http://localhost:8080",
        device_name="test-desktop",
        _env_file=None,
    )


def make_token(private_pem: str, *, job_id: str | None = None, accept_seconds: int = 600, exp_seconds: int = 3600, action: str = "process_recording", issuer: str = "military-stt-central", audience: str = "military-stt-agent", nonce: str | None = None, session_id: str | None = None) -> tuple[str, dict]:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": str(uuid.uuid4()),
        "jti": nonce or uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()) - 30,
        "exp": int((now + timedelta(seconds=exp_seconds)).timestamp()),
        "accept_by": int((now + timedelta(seconds=accept_seconds)).timestamp()),
        "job_id": job_id or str(uuid.uuid4()),
        "session_id": session_id or str(uuid.uuid4()),
        "recording_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "session_number": "INV-2026-00001",
        "allowed_action": action,
    }
    return jwt.encode(claims, private_pem, algorithm="ES256"), claims


def write_wav(path: Path, seconds: float = 3.0, sample_rate: int = 16000, tone_hz: float = 220.0, silence: bool = False) -> Path:
    frames = int(seconds * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        data = bytearray()
        for i in range(frames):
            v = 0 if silence else int(12000 * math.sin(2 * math.pi * tone_hz * i / sample_rate))
            data += struct.pack("<h", v)
        wf.writeframes(bytes(data))
    return path


class FakeVad:
    provider = "fake_vad"
    model_name = "fake-vad"

    def __init__(self, regions=None):
        self._regions = regions

    def info(self):
        return ModelInfo("vad", self.provider, "fake-vad", "0", "READY")

    def load(self):
        pass

    def detect(self, wav_path, duration):
        from app.ai.types import SpeechRegion

        if self._regions is not None:
            return [SpeechRegion(*r) for r in self._regions]
        return [SpeechRegion(0.0, duration)]


class FakeDiarization:
    provider = "fake_diarization"
    max_speakers = 4
    device = "cpu"

    def __init__(self, turns=None, fail: str | None = None):
        self._turns = turns
        self._fail = fail
        self.calls = 0

    def info(self):
        return ModelInfo("diarization", self.provider, "fake/diarizer", "rev-d", "READY", extra={"streaming": {}})

    def load(self):
        if self._fail == "load":
            from app.ai.diarization_service import DiarizationError

            raise DiarizationError("diarization_model_missing", "not provisioned")

    def diarize(self, path):
        self.calls += 1
        if self._fail == "infer":
            from app.ai.diarization_service import DiarizationError

            raise DiarizationError("diarization_failed", "boom")
        if self._turns is not None:
            return [SpeakerTurn(*t) for t in self._turns]
        return [SpeakerTurn("SPEAKER_00", 0.0, 1.0), SpeakerTurn("SPEAKER_01", 1.0, 2.0), SpeakerTurn("SPEAKER_00", 2.0, 3.0)]


class FakeTranscription:
    provider = "fake_stt"
    device = "cpu"

    def __init__(self, texts=None, fail: str | None = None):
        self._texts = texts or ["أين كنت مساء أمس؟", "كنت في المنزل.", "هل كان معك أحد؟"]
        self._fail = fail
        self.calls: list[int] = []

    def info(self):
        return ModelInfo("stt", self.provider, "fake/stt-ar", "rev-s", "READY", extra={"device": "cpu"})

    def load(self):
        if self._fail == "load":
            from app.ai.transcription_service import TranscriptionError

            raise TranscriptionError("stt_model_missing", "not provisioned")

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> TranscriptionResult:
        self.calls.append(len(audio))
        if self._fail == "infer":
            from app.ai.transcription_service import TranscriptionError

            raise TranscriptionError("transcription_failed", "boom")
        idx = len(self.calls) - 1
        return TranscriptionResult(self._texts[idx % len(self._texts)])


class FakeCentral:
    """In-memory stand-in for the central server used by the sync tests."""

    def __init__(self, *, fail_times: int = 0, permanent_error: str | None = None):
        self.enabled = True
        self.states: list[tuple[str, str]] = []
        self.results: dict[str, dict] = {}
        self.audio: dict[str, dict] = {}
        self.fail_times = fail_times
        self.permanent_error = permanent_error
        self.result_calls = 0

    def report_state(self, job_id, token, state, **kw):
        self.states.append((job_id, state))

    def submit_result(self, job_id, token, result):
        from app.sync.central_client import CentralError

        self.result_calls += 1
        if self.permanent_error:
            raise CentralError(self.permanent_error, "rejected", status=409, permanent=True)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise CentralError("network", "connection refused")
        duplicate = job_id in self.results and self.results[job_id]["idempotency_key"] == result["idempotency_key"]
        if job_id in self.results and not duplicate:
            raise CentralError("result_already_submitted", "conflict", status=409, permanent=True)
        self.results[job_id] = result
        return {"job_id": job_id, "transcript_id": str(uuid.uuid4()), "status": "COMPLETED", "duplicate": duplicate}

    def upload_audio(self, job_id, token, path, filename, mime_type):
        self.audio[job_id] = {"filename": filename, "size": Path(path).stat().st_size}
        return {"recording_id": "x", "duplicate": False}

    def close(self):
        pass


def build_runtime(settings: Settings, *, vad=None, diarization=None, transcription=None):
    from app.ai.runtime import ModelRuntime

    runtime = ModelRuntime.__new__(ModelRuntime)
    runtime._settings = settings
    runtime.vad = vad or FakeVad()
    runtime.diarization = diarization or FakeDiarization()
    runtime.transcription = transcription or FakeTranscription()
    import threading

    runtime._load_lock = threading.Lock()
    runtime._loading = False
    runtime.max_speakers = 4
    return runtime


@pytest.fixture
def agent_app(settings: Settings, keypair):
    """A fully wired agent app with fake models and a fake central server."""
    from fastapi.testclient import TestClient

    from app.jobs.job_manager import JobManager
    from app.jobs.store import JobStore
    from app.main import create_app
    from app.security.token_validation import ProcessingTokenValidator, PublicKeyProvider

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = JobStore(settings.db_path)
    runtime = build_runtime(settings)
    central = FakeCentral()
    manager = JobManager(settings, store, runtime, central)
    app = create_app(settings)

    # Replace the lifespan wiring with our test doubles.
    app.router.lifespan_context = _noop_lifespan
    app.state.settings = settings
    app.state.store = store
    app.state.runtime = runtime
    app.state.client = central
    app.state.manager = manager
    app.state.token_validator = ProcessingTokenValidator(settings, store, PublicKeyProvider(settings))
    manager.start()
    client = TestClient(app)
    yield {"client": client, "settings": settings, "store": store, "runtime": runtime, "central": central, "manager": manager, "keypair": keypair}
    manager.stop()
    store.close()


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def _noop_lifespan(app):
    yield


def wait_for_state(store, job_id: str, states: set[str], timeout: float = 20.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        job = store.get(job_id)
        if job and job.state in states:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach {states}; last={store.get(job_id).state if store.get(job_id) else None}")


def read_result(store, job_id: str) -> dict:
    return json.loads(Path(store.get(job_id).result_path).read_text(encoding="utf-8"))
