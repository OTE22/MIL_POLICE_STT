"""Central server test-suite. Runs against an isolated PostgreSQL database
(CENTRAL_TEST_DATABASE_URL), migrated with Alembic and truncated between tests.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

TEST_DB_URL = os.environ.get("CENTRAL_TEST_DATABASE_URL")
if not TEST_DB_URL:
    pytest.skip("CENTRAL_TEST_DATABASE_URL not set", allow_module_level=True)

os.environ["CENTRAL_DATABASE_URL"] = TEST_DB_URL
os.environ["ALEMBIC_DATABASE_URL"] = TEST_DB_URL
os.environ.setdefault("CENTRAL_JWT_SECRET", "test-secret-0123456789-0123456789-0123456789")
# The suite must not write into /storage (docker compose run has no such volume); the
# logging tests that need the file sink point CENTRAL_LOG_DIR at a tmp dir themselves.
os.environ.setdefault("CENTRAL_LOG_DIR", "")
os.environ["CENTRAL_BOOTSTRAP_ADMIN_PASSWORD"] = "AdminBootstrap!1"
os.environ["CENTRAL_BOOTSTRAP_ADMIN_USERNAME"] = "admin"
_tmp_root = Path(os.environ.get("CENTRAL_TEST_TMP", "/tmp/mstt-tests"))
_tmp_root.mkdir(parents=True, exist_ok=True)
os.environ["CENTRAL_STORAGE_ROOT"] = str(_tmp_root / "storage")
os.environ["CENTRAL_PROCESSING_TOKEN_PRIVATE_KEY_PATH"] = str(_tmp_root / "priv.pem")
os.environ["CENTRAL_PROCESSING_TOKEN_PUBLIC_KEY_PATH"] = str(_tmp_root / "pub.pem")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.bootstrap import run_bootstrap  # noqa: E402

ADMIN = {"username": "admin", "password": "AdminBootstrap!1"}


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_db():
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE audit_logs, transcript_segments, transcripts, session_speakers, "
                "voice_enrollments, subject_documents, person_identifiers, person_identities, "
                "local_processing_jobs, audio_recordings, subjects, session_investigators, "
                "investigation_sessions, workstations, investigator_profiles, user_roles, users RESTART IDENTITY CASCADE"
            )
        )
    with SessionLocal() as db:
        run_bootstrap(db)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_token(client):
    return login(client, ADMIN["username"], ADMIN["password"])


def create_user(client, admin_token, username, roles, password="Password!1234", **profile):
    """Create a user through the API.

    Every user is a person in the canonical registry now, so the two fields that produce their
    الرقم المرجعي are mandatory. `military_id` is UNIQUE, so it is derived from the username -
    a stable digest rather than hash(), which is salted per process and would collide across
    runs in a way that looks like a flaky test.
    """
    import hashlib

    profile.setdefault(
        "military_id", "T" + hashlib.sha1(username.encode()).hexdigest()[:8].upper()
    )
    profile.setdefault("security_branch", "ARMY")
    body = {
        "username": username,
        "password": password,
        "roles": roles,
        "must_change_password": False,
        "profile": {"full_name": profile.pop("full_name", f"User {username}"), **profile},
    }
    res = client.post("/api/users", json=body, headers=auth(admin_token))
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def investigator(client, admin_token):
    user = create_user(client, admin_token, "inv1", ["INVESTIGATOR"], full_name="الرائد علي حسن", rank="رائد", military_id="M-1001")
    return {"user": user, "token": login(client, "inv1", "Password!1234")}


@pytest.fixture
def investigator2(client, admin_token):
    user = create_user(client, admin_token, "inv2", ["INVESTIGATOR"], full_name="النقيب سامر", military_id="M-1002")
    return {"user": user, "token": login(client, "inv2", "Password!1234")}


@pytest.fixture
def viewer(client, admin_token):
    user = create_user(client, admin_token, "viewer", ["USER"], full_name="مشاهد")
    return {"user": user, "token": login(client, "viewer", "Password!1234")}


def create_session(client, token, **overrides):
    body = {
        "title": "جلسة تحقيق تجريبية",
        "location": "بيروت",
        "session_date": "2026-08-23",
        "start_time": "10:00",
        "expected_speaker_count": 2,
        # Structured identifiers, so الرقم المرجعي DERIVES (LBN-BEIRUT-725). A hand-typed
        # reference is no longer ordinary data entry - it needs subjects.reference.override -
        # and the form cannot produce one, so the fixture must not either.
        "subjects": [
            {
                "subject_name": "أحمد محمد",
                "person_type": "CIVILIAN",
                "register_number": "725",
                "caza_code": "BEIRUT",
            }
        ],
    }
    body.update(overrides)
    res = client.post("/api/investigations", json=body, headers=auth(token))
    assert res.status_code == 201, res.text
    return res.json()


def request_token(client, token, session_id, **overrides):
    body = {"original_filename": "interview.wav", "mime_type": "audio/wav", "size_bytes": 44 + 16000 * 2 * 3, "source": "FILE_UPLOAD"}
    body.update(overrides)
    res = client.post(f"/api/investigations/{session_id}/local-processing-token", json=body, headers=auth(token))
    assert res.status_code == 200, res.text
    return res.json()


def sample_result(idempotency_key: str | None = None) -> dict:
    return {
        "idempotency_key": idempotency_key or uuid.uuid4().hex,
        "language": "ar",
        "stt_provider": "cohere_local",
        "stt_model": "CohereLabs/cohere-transcribe-arabic-07-2026",
        "stt_model_revision": "c3e911b42149bf7a1e53d5cef9878aee87515a23",
        "diarization_provider": "nvidia_sortformer",
        "diarization_model": "nvidia/diar_streaming_sortformer_4spk-v2.1",
        "diarization_model_revision": "fafaab5faa1617a0ca52d38dd3dc4bd636800d3d",
        "vad_model": "snakers4/silero-vad",
        "agent_version": "1.0.0",
        "processing_device": "cpu",
        "speaker_count": 2,
        "warnings": ["Processed on CPU."],
        "processing_metadata": {"segments": 3},
        "audio": {"duration_seconds": 21.0, "sha256": "a" * 64, "size_bytes": 1000},
        "workstation": {"agent_id": "agent-test-1", "device_name": "DESKTOP-01", "agent_version": "1.0.0", "processing_device": "cpu", "stt_ready": True, "diarization_ready": True},
        "segments": [
            {"speaker_label": "SPEAKER_00", "start_seconds": 2.4, "end_seconds": 8.9, "text": "أين كنت مساء أمس؟", "is_overlap": False},
            {"speaker_label": "SPEAKER_01", "start_seconds": 9.1, "end_seconds": 16.3, "text": "كنت في المنزل.", "is_overlap": False},
            {"speaker_label": "SPEAKER_00", "start_seconds": 16.5, "end_seconds": 21.0, "text": "هل كان معك أحد؟", "is_overlap": True},
        ],
    }
