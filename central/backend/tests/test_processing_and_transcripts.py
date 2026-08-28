from __future__ import annotations

import io
import math
import struct
import time
import uuid
import wave
from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings
from app.core.processing_tokens import load_private_key, load_public_key
from tests.conftest import auth, create_session, request_token, sample_result


def _wav_bytes(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) for i in range(int(16000 * seconds))))
    return buf.getvalue()


def _forged_token(claims_override: dict | None = None, key: str | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    claims = {
        "iss": settings.processing_token_issuer,
        "aud": settings.processing_token_audience,
        "sub": str(uuid.uuid4()),
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "accept_by": int((now + timedelta(minutes=10)).timestamp()),
        "job_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "recording_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "allowed_action": "process_recording",
    }
    claims.update(claims_override or {})
    return jwt.encode(claims, key or load_private_key(), algorithm="ES256")


# ------------------------------------------------------------------ token issue


def test_processing_token_generation_and_claims(client, investigator):
    s = create_session(client, investigator["token"])
    tok = request_token(client, investigator["token"], s["id"])
    assert tok["allowed_action"] == "process_recording"
    claims = jwt.decode(tok["processing_token"], load_public_key(), algorithms=["ES256"], audience="military-stt-agent", issuer="military-stt-central")
    assert claims["job_id"] == tok["job_id"] and claims["session_id"] == s["id"] and claims["user_id"] == investigator["user"]["id"]
    assert claims["accept_by"] < claims["exp"] and "password" not in claims
    # session moved to PROCESSING, recording created, audit written
    detail = client.get(f"/api/investigations/{s['id']}", headers=auth(investigator["token"])).json()
    assert detail["status"] == "PROCESSING" and detail["recordings"][0]["upload_status"] == "PENDING"
    jobs = client.get(f"/api/investigations/{s['id']}/jobs", headers=auth(investigator["token"])).json()
    assert jobs[0]["status"] == "REQUESTED"
    pub = client.get("/api/local-processing/public-key").json()
    assert pub["algorithm"] == "ES256" and "BEGIN PUBLIC KEY" in pub["public_key_pem"]


def test_processing_token_validates_audio_metadata(client, investigator):
    s = create_session(client, investigator["token"])
    base = {"original_filename": "x.exe", "mime_type": "audio/wav", "size_bytes": 10}
    res = client.post(f"/api/investigations/{s['id']}/local-processing-token", json=base, headers=auth(investigator["token"]))
    assert res.status_code == 400 and res.json()["detail"] == "unsupported_extension"
    res = client.post(f"/api/investigations/{s['id']}/local-processing-token", json={**base, "original_filename": "x.wav", "mime_type": "text/plain"}, headers=auth(investigator["token"]))
    assert res.status_code == 400 and res.json()["detail"] == "unsupported_mime_type"
    res = client.post(f"/api/investigations/{s['id']}/local-processing-token", json={**base, "original_filename": "x.wav", "size_bytes": 10**12}, headers=auth(investigator["token"]))
    assert res.status_code == 400 and res.json()["detail"] == "file_too_large"


# ------------------------------------------------------------------ agent side auth


def test_expired_token_rejected_on_sync(client, investigator):
    s = create_session(client, investigator["token"])
    tok = request_token(client, investigator["token"], s["id"])
    expired = _forged_token({"job_id": tok["job_id"], "exp": int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp())})
    res = client.post(f"/api/local-processing/{tok['job_id']}/result", json=sample_result(), headers=auth(expired))
    assert res.status_code == 401 and res.json()["detail"] == "processing_token_expired"


def test_invalid_and_mismatched_tokens_rejected(client, investigator):
    s = create_session(client, investigator["token"])
    tok = request_token(client, investigator["token"], s["id"])
    # no token
    assert client.post(f"/api/local-processing/{tok['job_id']}/result", json=sample_result()).status_code == 401
    # user JWT is not a processing token
    res = client.post(f"/api/local-processing/{tok['job_id']}/result", json=sample_result(), headers=auth(investigator["token"]))
    assert res.status_code == 401
    # forged with another key
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    other = ec.generate_private_key(ec.SECP256R1()).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    res = client.post(f"/api/local-processing/{tok['job_id']}/result", json=sample_result(), headers=auth(_forged_token({"job_id": tok["job_id"]}, key=other)))
    assert res.status_code == 401 and res.json()["detail"] == "processing_token_invalid"
    # valid signature but for another job id
    tok2 = request_token(client, investigator["token"], s["id"])
    res = client.post(f"/api/local-processing/{tok['job_id']}/result", json=sample_result(), headers=auth(tok2["processing_token"]))
    assert res.status_code == 403 and res.json()["detail"] == "processing_token_job_mismatch"
    # wrong allowed_action
    res = client.post(f"/api/local-processing/{tok['job_id']}/state", json={"state": "DIARIZING"}, headers=auth(_forged_token({"job_id": tok["job_id"], "allowed_action": "admin"})))
    assert res.status_code == 401


# ------------------------------------------------------------------ sync


def test_result_synchronization_full_flow(client, investigator, admin_token):
    s = create_session(client, investigator["token"])
    tok = request_token(client, investigator["token"], s["id"])
    h = auth(tok["processing_token"])
    ws = {"agent_id": "agent-test-1", "device_name": "DESKTOP-01", "agent_version": "1.0.0", "processing_device": "cpu", "stt_model": "CohereLabs/cohere-transcribe-arabic-07-2026", "diarization_model": "nvidia/diar_streaming_sortformer_4spk-v2.1", "stt_ready": True, "diarization_ready": True}
    for state in ("CREATED", "RECEIVING_AUDIO", "PREPROCESSING", "DIARIZING", "TRANSCRIBING", "FINALIZING", "SYNCING"):
        res = client.post(f"/api/local-processing/{tok['job_id']}/state", json={"state": state, "progress": 0.5, "workstation": ws}, headers=h)
        assert res.status_code == 200, res.text
    assert client.get(f"/api/local-processing/{tok['job_id']}", headers=auth(investigator["token"])).json()["status"] == "PROCESSING"

    result = sample_result()
    res = client.post(f"/api/local-processing/{tok['job_id']}/result", json=result, headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "COMPLETED" and body["duplicate"] is False
    transcript_id = body["transcript_id"]

    # audio upload (original) with sha mismatch refused, then correct
    audio = _wav_bytes()
    res = client.post(f"/api/local-processing/{tok['job_id']}/audio", files={"file": ("interview.wav", audio, "audio/wav")}, headers=h)
    assert res.status_code == 400 and res.json()["detail"] == "sha256_mismatch"
    import hashlib

    result2 = sample_result()
    # resubmit is a conflict (different idempotency key) -> 409; fix the hash via a new session instead
    res = client.post(f"/api/local-processing/{tok['job_id']}/result", json=result2, headers=h)
    assert res.status_code == 409

    s2 = create_session(client, investigator["token"])
    tok2 = request_token(client, investigator["token"], s2["id"])
    h2 = auth(tok2["processing_token"])
    good = sample_result()
    good["audio"]["sha256"] = hashlib.sha256(audio).hexdigest()
    assert client.post(f"/api/local-processing/{tok2['job_id']}/result", json=good, headers=h2).status_code == 200
    res = client.post(f"/api/local-processing/{tok2['job_id']}/audio", files={"file": ("interview.wav", audio, "audio/wav")}, headers=h2)
    assert res.status_code == 201, res.text
    res = client.post(f"/api/local-processing/{tok2['job_id']}/audio", files={"file": ("interview.wav", audio, "audio/wav")}, headers=h2)
    assert res.status_code == 201 and res.json()["duplicate"] is True

    # transcript retrieval by the investigator
    tr = client.get(f"/api/investigations/{s2['id']}/transcript", headers=auth(investigator["token"])).json()
    assert tr["audio_available"] is True and len(tr["segments"]) == 3 and tr["speaker_count"] == 2
    assert [seg["speaker_label"] for seg in tr["segments"]] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]
    assert tr["segments"][2]["is_overlap"] is True and tr["segments"][0]["edited_text"] is None
    assert tr["stt_model_revision"] == "c3e911b42149bf7a1e53d5cef9878aee87515a23"
    labels = sorted(sp["speaker_label"] for sp in tr["speakers"])
    assert labels == ["SPEAKER_00", "SPEAKER_01"]
    # session status + audio streaming
    assert client.get(f"/api/investigations/{s2['id']}", headers=auth(investigator["token"])).json()["status"] == "COMPLETED"
    res = client.get(f"/api/recordings/{tr['recording_id']}/audio", headers=auth(investigator["token"]))
    assert res.status_code == 200 and res.content == audio
    # workstation registered from the sync payload
    wss = client.get("/api/workstations", headers=auth(admin_token)).json()
    assert any(w["agent_id"] == "agent-test-1" and w["status"] == "ONLINE" for w in wss)
    # audit trail
    activity = client.get(f"/api/investigations/{s2['id']}/activity", headers=auth(investigator["token"])).json()
    actions = {e["action"] for e in activity["items"]}
    assert {"LOCAL_PROCESSING_REQUESTED", "LOCAL_PROCESSING_COMPLETED", "TRANSCRIPT_RECEIVED", "RECORDING_UPLOADED"} <= actions
    logs = client.get("/api/audit-logs?entity_type=local_processing_job", headers=auth(admin_token)).json()
    all_actions = {e["action"] for e in logs["items"]}
    assert {"LOCAL_PROCESSING_STARTED", "DIARIZATION_STARTED", "DIARIZATION_COMPLETED", "TRANSCRIPTION_STARTED", "TRANSCRIPTION_COMPLETED"} <= all_actions
    assert transcript_id


def test_duplicate_result_submission_is_idempotent(client, investigator):
    s = create_session(client, investigator["token"])
    tok = request_token(client, investigator["token"], s["id"])
    h = auth(tok["processing_token"])
    result = sample_result("same-key-0123456789")
    first = client.post(f"/api/local-processing/{tok['job_id']}/result", json=result, headers=h).json()
    second = client.post(f"/api/local-processing/{tok['job_id']}/result", json=result, headers=h)
    assert second.status_code == 200 and second.json()["duplicate"] is True
    assert second.json()["transcript_id"] == first["transcript_id"]
    tr = client.get(f"/api/investigations/{s['id']}/transcript", headers=auth(investigator["token"])).json()
    assert len(tr["segments"]) == 3  # not duplicated


def test_failed_processing_reported(client, investigator):
    s = create_session(client, investigator["token"])
    tok = request_token(client, investigator["token"], s["id"])
    h = auth(tok["processing_token"])
    client.post(f"/api/local-processing/{tok['job_id']}/state", json={"state": "DIARIZING"}, headers=h)
    res = client.post(f"/api/local-processing/{tok['job_id']}/state", json={"state": "FAILED", "message": "diarization_model_missing", "failure_stage": "DIARIZING"}, headers=h)
    assert res.status_code == 200 and res.json()["status"] == "FAILED" and res.json()["failure_stage"] == "DIARIZING"
    assert client.get(f"/api/investigations/{s['id']}", headers=auth(investigator["token"])).json()["status"] == "FAILED"
    assert client.get(f"/api/investigations/{s['id']}/transcript", headers=auth(investigator["token"])).status_code == 404


def test_cancelled_job_rejects_result(client, investigator):
    s = create_session(client, investigator["token"])
    tok = request_token(client, investigator["token"], s["id"])
    res = client.post(f"/api/local-processing/{tok['job_id']}/cancel", headers=auth(investigator["token"]))
    assert res.status_code == 200 and res.json()["status"] == "CANCELLED"
    res = client.post(f"/api/local-processing/{tok['job_id']}/result", json=sample_result(), headers=auth(tok["processing_token"]))
    assert res.status_code == 409 and res.json()["detail"] == "job_cancelled"


def test_result_validation(client, investigator):
    s = create_session(client, investigator["token"])
    tok = request_token(client, investigator["token"], s["id"])
    bad = sample_result()
    bad["segments"][0]["speaker_label"] = "Ali"
    assert client.post(f"/api/local-processing/{tok['job_id']}/result", json=bad, headers=auth(tok["processing_token"])).status_code == 422
    bad = sample_result()
    bad["segments"][0]["end_seconds"] = 1.0  # before start
    assert client.post(f"/api/local-processing/{tok['job_id']}/result", json=bad, headers=auth(tok["processing_token"])).status_code == 422


# ------------------------------------------------------------------ transcript edit + speakers


def _synced_session(client, investigator):
    s = create_session(client, investigator["token"])
    tok = request_token(client, investigator["token"], s["id"])
    assert client.post(f"/api/local-processing/{tok['job_id']}/result", json=sample_result(), headers=auth(tok["processing_token"])).status_code == 200
    return s, client.get(f"/api/investigations/{s['id']}/transcript", headers=auth(investigator["token"])).json()


def test_transcript_edit_preserves_original_and_audits(client, investigator, admin_token):
    s, tr = _synced_session(client, investigator)
    seg = tr["segments"][1]
    res = client.patch(f"/api/transcript-segments/{seg['id']}", json={"edited_text": "كنت في المنزل مع عائلتي."}, headers=auth(investigator["token"]))
    assert res.status_code == 200
    body = res.json()
    assert body["original_text"] == "كنت في المنزل." and body["edited_text"] == "كنت في المنزل مع عائلتي."
    assert body["edited_by"] == investigator["user"]["id"] and body["edited_at"] and body["edited_by_name"] == "الرائد علي حسن"
    # restore to the original clears the correction but keeps the audit entry
    res = client.patch(f"/api/transcript-segments/{seg['id']}", json={"edited_text": "كنت في المنزل."}, headers=auth(investigator["token"]))
    assert res.json()["edited_text"] is None and res.json()["original_text"] == "كنت في المنزل."
    logs = client.get("/api/audit-logs?action=TRANSCRIPT_SEGMENT_EDITED", headers=auth(admin_token)).json()
    assert logs["total"] == 2 and logs["items"][0]["safe_metadata"]["original_text_preserved"] is True


def test_transcript_edit_authorization(client, investigator, investigator2, viewer, admin_token):
    s, tr = _synced_session(client, investigator)
    seg = tr["segments"][0]
    # viewer: no transcripts.edit permission
    assert client.patch(f"/api/transcript-segments/{seg['id']}", json={"edited_text": "x"}, headers=auth(viewer["token"])).status_code == 403
    # other investigator: has permission but not resource access
    assert client.patch(f"/api/transcript-segments/{seg['id']}", json={"edited_text": "x"}, headers=auth(investigator2["token"])).status_code == 404
    assert client.get(f"/api/investigations/{s['id']}/transcript", headers=auth(investigator2["token"])).status_code == 404
    # admin can edit anything
    assert client.patch(f"/api/transcript-segments/{seg['id']}", json={"edited_text": "تصحيح المدير"}, headers=auth(admin_token)).status_code == 200


def test_speaker_rename(client, investigator, viewer, admin_token):
    s, tr = _synced_session(client, investigator)
    speakers = {sp["speaker_label"]: sp for sp in tr["speakers"]}
    assert speakers["SPEAKER_00"]["segment_count"] == 2 and speakers["SPEAKER_01"]["segment_count"] == 1
    res = client.patch(f"/api/investigations/{s['id']}/speakers/{speakers['SPEAKER_00']['id']}", json={"display_name": "المحقق", "speaker_role": "INVESTIGATOR"}, headers=auth(investigator["token"]))
    assert res.status_code == 200 and res.json()["display_name"] == "المحقق" and res.json()["speaker_role"] == "INVESTIGATOR"
    # The civilian reference is ISSUED by the backend, so read it rather than assuming it.
    civilian_ref = client.get(f"/api/investigations/{s['id']}", headers=auth(investigator["token"])).json()["subjects"][0]["reference_number"]
    assert civilian_ref.startswith("CIV-"), civilian_ref
    res = client.patch(f"/api/investigations/{s['id']}/speakers/{speakers['SPEAKER_01']['id']}", json={"display_name": "أحمد محمد", "person_name": "أحمد محمد", "speaker_role": "SUBJECT", "reference_number": civilian_ref}, headers=auth(investigator["token"]))
    assert res.status_code == 200 and res.json()["display_name"] == "أحمد محمد"
    listing = client.get(f"/api/investigations/{s['id']}/speakers", headers=auth(investigator["token"])).json()
    assert {sp["speaker_label"]: sp["display_name"] for sp in listing} == {"SPEAKER_00": "المحقق", "SPEAKER_01": "أحمد محمد"}
    # viewer cannot rename
    assert client.patch(f"/api/investigations/{s['id']}/speakers/{speakers['SPEAKER_00']['id']}", json={"display_name": "x"}, headers=auth(viewer["token"])).status_code in (403, 404)  # not assigned -> hidden
    logs = client.get("/api/audit-logs?action=SPEAKER_RENAMED", headers=auth(admin_token)).json()
    assert logs["total"] == 2 and logs["items"][0]["safe_metadata"]["new"]["display_name"]


def test_workstation_register_from_frontend(client, investigator, admin_token, viewer):
    body = {"agent_id": "agent-abc", "device_name": "PC-7", "agent_version": "1.0.0", "stt_model": "CohereLabs/cohere-transcribe-arabic-07-2026", "diarization_model": "nvidia/diar_streaming_sortformer_4spk-v2.1", "processing_device": "cuda", "gpu_name": "RTX 4070", "stt_ready": True, "diarization_ready": False}
    res = client.post("/api/workstations/register", json=body, headers=auth(investigator["token"]))
    assert res.status_code == 200 and res.json()["status"] == "DEGRADED" and res.json()["registered_by_name"] == "الرائد علي حسن"
    assert client.post("/api/workstations/register", json=body, headers=auth(viewer["token"])).status_code == 403
    assert client.get("/api/workstations", headers=auth(viewer["token"])).status_code == 403
    assert len(client.get("/api/workstations", headers=auth(admin_token)).json()) == 1
    time.sleep(0)
