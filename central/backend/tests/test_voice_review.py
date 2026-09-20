"""Review decisions, provenance-safe playback, and model compatibility."""
import uuid

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import AudioRecording, AuditLog, SessionSpeaker, Transcript, VoiceEnrollment
from app.models.enums import RecordingUploadStatus
from conftest import auth
from test_biometric_check import _axis, _check
from test_batch_voice_matching import _person, _print
from test_voice_readiness import enrolled
from test_voice_matching import EMB_A, _submit, _voice, _speakers


def review(client, token, row, action="FLAG", reason="راجع المصدر"):
    return client.post(f"/api/voice-enrollments/{row['id']}/reviews", headers=auth(token), json={
        "action": action, "reason": reason, "expected_updated_at": row["updated_at"],
        "identity_id": row["identity_id"],
    })


def current(client, token, row):
    rows = client.get("/api/voice-enrollments?include_inactive=true", headers=auth(token)).json()
    return next(r for r in rows if r["id"] == row["id"])


def history(client, token, row):
    return client.get(f"/api/voice-enrollments/people/{row['identity_id']}/reviews", headers=auth(token))


def test_review_lifecycle_preserves_notes_and_records_operator(client, investigator):
    token = investigator["token"]
    row = enrolled(client, token)
    saved = review(client, token, row)
    assert saved.status_code == 200, saved.text
    assert saved.json()["reviewer_name"]
    assert saved.json()["reason"] == "راجع المصدر"
    checked = _check(client, token, row["identity_id"]).json()
    assert checked["groups"][0]["prints"][0]["review_status"] == "FLAGGED"
    assert review(client, token, current(client, token, row), "NOTE", "عينة قصيرة").status_code == 200
    checked = _check(client, token, row["identity_id"]).json()
    assert checked["groups"][0]["prints"][0]["review_status"] == "FLAGGED"
    assert review(client, token, current(client, token, row), "RESOLVE", "تمت مراجعة التسجيل").status_code == 200
    checked = _check(client, token, row["identity_id"]).json()
    assert checked["groups"][0]["prints"][0]["review_status"] == "RESOLVED"
    entries = history(client, token, row).json()
    assert [e["action"] for e in entries] == ["RESOLVE", "NOTE", "FLAG"]
    assert all("embedding" not in e and "ip_address" not in e for e in entries)
    after = current(client, token, row)
    assert after["notes"] == row["notes"]
    assert after["is_active"]


def test_stale_and_wrong_identity_reviews_cannot_mutate(client, investigator):
    token = investigator["token"]
    row = enrolled(client, token)
    assert review(client, token, {**row, "identity_id": str(uuid.uuid4())}).status_code == 409
    assert review(client, token, row).status_code == 200
    assert review(client, token, row, "DEACTIVATE").status_code == 409
    assert current(client, token, row)["is_active"]
    assert len(history(client, token, row).json()) == 1


@pytest.mark.parametrize("reason", ["", "   ", "x" * 2001])
def test_review_requires_meaningful_bounded_reason(client, investigator, reason):
    row = enrolled(client, investigator["token"])
    assert review(client, investigator["token"], row, reason=reason).status_code == 422
    assert history(client, investigator["token"], row).json() == []


def test_review_requires_permission_and_history_is_scoped(client, investigator, viewer):
    token = investigator["token"]
    row = enrolled(client, token)
    assert review(client, viewer["token"], row).status_code == 403
    assert history(client, viewer["token"], row).status_code == 403
    assert client.post(f"/api/voice-enrollments/{row['id']}/reviews").status_code == 401
    assert review(client, token, row).status_code == 200
    with SessionLocal() as db:
        other = _person(db, "شخص آخر", "other")
        db.commit()
    assert client.get(f"/api/voice-enrollments/people/{other.id}/reviews", headers=auth(token)).json() == []


def test_deactivation_invalidates_pending_suggestion_and_survives_deletion(client, investigator):
    token = investigator["token"]
    row = enrolled(client, token)
    session = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A))
    assert _speakers(client, token, session["id"])["SPEAKER_00"]["identification_status"] == "SUGGESTED"
    response = review(client, token, row, "DEACTIVATE", "عينة تحتاج استبدالاً")
    assert response.status_code == 200, response.text
    assert not current(client, token, row)["is_active"]
    assert _speakers(client, token, session["id"])["SPEAKER_00"]["identification_status"] == "NONE"
    assert client.delete(f"/api/voice-enrollments/{row['id']}", headers=auth(token)).status_code == 204
    assert history(client, token, row).json()[0]["action"] == "DEACTIVATE"


def test_revisions_and_providers_never_compare_and_pairs_stay_per_person(client, admin_token):
    with SessionLocal() as db:
        person = _person(db, "عينات مختلفة", "rev")
        first = _print(db, person, _axis(0))
        second = _print(db, person, _axis(0))
        different_revision = _print(db, person, _axis(0))
        different_revision.model_revision = "new"
        different_provider = _print(db, person, _axis(0))
        different_provider.provider = "other"
        unrelated = _person(db, "شخص مختلف", "unrelated")
        _print(db, unrelated, _axis(0))
        db.commit()
    result = _check(client, admin_token, person.id).json()
    assert len(result["groups"]) == 3
    pairs = [p for group in result["groups"] for p in group["pairs"]]
    assert len(pairs) == 1
    assert {pairs[0]["first_id"], pairs[0]["second_id"]} == {str(first.id), str(second.id)}
    assert pairs[0]["similarity"] == 1.0


def test_source_uses_enrolled_recording_and_requires_session_access(client, investigator, investigator2):
    token = investigator["token"]
    row = enrolled(client, token)
    with SessionLocal() as db:
        speaker = db.scalar(select(SessionSpeaker).where(
            SessionSpeaker.session_id == uuid.UUID(row["source_session_id"]),
            SessionSpeaker.speaker_label == row["source_speaker_label"]))
        recording = db.get(AudioRecording, speaker.recording_id)
        recording.storage_path = "recordings/test.wav"
        recording.upload_status = RecordingUploadStatus.UPLOADED
        expected_transcript = db.scalar(select(Transcript).where(Transcript.recording_id == recording.id))
        db.commit()
    url = f"/api/voice-enrollments/{row['id']}/source"
    response = client.get(url, headers=auth(token))
    assert response.status_code == 200, response.text
    assert response.json()["recording_id"] == str(recording.id)
    assert response.json()["transcript_id"] == str(expected_transcript.id)
    assert response.json()["segments"]
    assert client.get(url, headers=auth(investigator2["token"])).status_code == 404
    with SessionLocal() as db:
        db.get(SessionSpeaker, speaker.id).recording_id = None
        db.commit()
    assert client.get(url, headers=auth(token)).status_code == 404


def test_check_remains_read_only(client, investigator):
    token = investigator["token"]
    row = enrolled(client, token)
    with SessionLocal() as db:
        before = db.query(AuditLog).count()
    assert _check(client, token, row["identity_id"]).status_code == 200
    with SessionLocal() as db:
        assert db.query(AuditLog).count() == before
        assert db.get(VoiceEnrollment, uuid.UUID(row["id"])).is_active


def test_session_speaker_totals_cover_recordings_without_reprocessing_duplicates(client, investigator):
    from test_speaker_identity_isolation import _submit_recording
    from app.models import LocalProcessingJob, TranscriptSegment
    token = investigator["token"]
    row = enrolled(client, token)
    session_id = row["source_session_id"]
    _submit_recording(client, token, session_id, labels=("SPEAKER_00",))
    before = _speakers(client, token, session_id)
    assert before["SPEAKER_00"]["segment_count"] > 0
    latest = next(s for s in before.values() if s["recording_id"] != before["SPEAKER_00"]["recording_id"])
    label = latest["speaker_label"]
    assert latest["segment_count"] == 1
    assert before["SPEAKER_00"]["recording_name"]
    with SessionLocal() as db:
        recording_id = uuid.UUID(latest["recording_id"])
        original = db.scalar(select(Transcript).where(Transcript.recording_id == recording_id))
        job = db.get(LocalProcessingJob, original.job_id)
        # A later transcript from a new processing job for the same recording.
        new_job = LocalProcessingJob(session_id=job.session_id, recording_id=job.recording_id,
                                     requested_by=job.requested_by, status=job.status,
                                     token_nonce=uuid.uuid4().hex, token_issued_at=job.token_issued_at,
                                     token_accept_by=job.token_accept_by, token_expires_at=job.token_expires_at)
        db.add(new_job)
        db.flush()
        newer = Transcript(session_id=original.session_id, recording_id=recording_id,
                           job_id=new_job.id, language="ar", status=original.status)
        db.add(newer)
        db.flush()
        db.add(TranscriptSegment(transcript_id=newer.id, sequence=0, speaker_label=label,
                                 start_seconds=1, end_seconds=6, original_text="اختبار"))
        db.commit()
    after = _speakers(client, token, session_id)
    assert after["SPEAKER_00"]["total_seconds"] == before["SPEAKER_00"]["total_seconds"]
    assert after[label]["segment_count"] == 1
    assert after[label]["total_seconds"] == 5
