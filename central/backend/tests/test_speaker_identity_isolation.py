"""A diarization label is local to ONE recording - identity must never leak across them.

The defect these tests pin down, measured on live data before the fix: four recordings in
one session all emitted SPEAKER_00 and shared one SessionSpeaker row. A person confirmed in
recording 1 was inherited by whoever spoke in recordings 2-4 even though the matcher
correctly scored the new voice 0.5372 against them (a different-speaker score, threshold
0.65), and the row's probe embedding was overwritten by each new voice - so the confirmed
person's row ended up holding a stranger's voiceprint.

An identity is assigned only because a human selected the person or biometric evidence
passed the validated criteria - never because that person was the last one identified.
"""

import math
import uuid

from sqlalchemy import select

from app.core.processing_tokens import issue_processing_token
from app.db.session import SessionLocal
from app.models import JobStatus, LocalProcessingJob, SessionSpeaker

from conftest import auth, create_session, request_token, sample_result
from test_voice_matching import API_DIM, MODEL, _enroll, _link_identity, _speakers, _voice

# Unit vectors with exact cosines against ALI = e0. STRANGER reproduces the measured 0.5372.
ALI = [1.0] + [0.0] * (API_DIM - 1)
ALI_AGAIN = [0.8, 0.6] + [0.0] * (API_DIM - 2)          # cos vs ALI = 0.80  -> SUGGESTED
STRANGER = [0.5372, math.sqrt(1 - 0.5372**2)] + [0.0] * (API_DIM - 2)  # cos = 0.5372 -> UNKNOWN
DIFFERENT = [0.0, 1.0] + [0.0] * (API_DIM - 2)          # cos vs ALI = 0.0


def _submit_recording(client, token, session_id, *, labels=("SPEAKER_00",), voice=None):
    """One agent submission = one recording. Returns (recording label map via speakers)."""
    tok = request_token(client, token, session_id)
    body = sample_result()
    body["segments"] = [
        {
            "speaker_label": label,
            "start_seconds": 1.0 + 2 * i,
            "end_seconds": 2.0 + 2 * i,
            "text": f"مقطع {i}",
            "is_overlap": False,
        }
        for i, label in enumerate(labels)
    ]
    body["speaker_count"] = len(labels)
    if voice is not None:
        body["voice_identification"] = voice
    res = client.post(
        f"/api/local-processing/{tok['job_id']}/result",
        json=body,
        headers=auth(tok["processing_token"]),
    )
    assert res.status_code == 200, res.text
    return tok


def _rows(session_id):
    with SessionLocal() as db:
        return {
            r.speaker_label: {
                "recording_id": r.recording_id,
                "source_label": r.source_label,
                "identity_id": r.identity_id,
                "display_name": r.display_name,
                "status": r.identification_status.value,
                "suggested_name": r.suggested_name,
                "embedding": list(r.voice_embedding or []),
            }
            for r in db.scalars(
                select(SessionSpeaker).where(SessionSpeaker.session_id == uuid.UUID(str(session_id)))
            ).all()
        }


# ---------------------------------------------------------------------------
# Provenance: rows are per (recording, local label)
# ---------------------------------------------------------------------------


def test_four_recordings_emitting_speaker00_become_four_observations(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    for _ in range(4):
        _submit_recording(client, t, s["id"], labels=("SPEAKER_00",))

    rows = _rows(s["id"])
    assert sorted(rows) == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02", "SPEAKER_03"]
    # Same local label every time, four different recordings, no row reuse.
    assert all(r["source_label"] == "SPEAKER_00" for r in rows.values())
    recordings = {str(r["recording_id"]) for r in rows.values()}
    assert len(recordings) == 4 and None not in recordings


def test_reprocessing_the_same_recording_reuses_its_observations(client, investigator):
    """Same recording + same local label -> the same row, no duplicate.

    There is deliberately no public endpoint that re-tokens an existing recording, so the
    second job is minted exactly the way the server mints the first - a real signed token
    for the SAME recording_id - and submitted through the real endpoint.
    """
    t = investigator["token"]
    s = create_session(client, t)
    first = _submit_recording(client, t, s["id"], labels=("SPEAKER_00", "SPEAKER_01"))

    with SessionLocal() as db:
        from app.models import InvestigationSession

        job1 = db.get(LocalProcessingJob, uuid.UUID(first["job_id"]))
        recording_id, session_id, user_id = job1.recording_id, job1.session_id, job1.requested_by
        session_number = db.get(InvestigationSession, session_id).session_number

        job_id = uuid.uuid4()
        issued = issue_processing_token(
            job_id=job_id,
            session_id=session_id,
            recording_id=recording_id,
            user_id=user_id,
            session_number=session_number,
        )
        db.add(
            LocalProcessingJob(
                id=job_id,
                session_id=session_id,
                recording_id=recording_id,
                requested_by=user_id,
                status=JobStatus.REQUESTED,
                token_nonce=issued.nonce,
                token_issued_at=issued.issued_at,
                token_accept_by=issued.accept_by,
                token_expires_at=issued.expires_at,
            )
        )
        db.commit()

    body = sample_result()
    body["segments"] = [
        {"speaker_label": "SPEAKER_00", "start_seconds": 1.0, "end_seconds": 2.0, "text": "إعادة", "is_overlap": False},
        {"speaker_label": "SPEAKER_01", "start_seconds": 3.0, "end_seconds": 4.0, "text": "إعادة", "is_overlap": False},
    ]
    res = client.post(f"/api/local-processing/{job_id}/result", json=body, headers=auth(issued.token))
    assert res.status_code == 200, res.text

    rows = _rows(s["id"])
    assert sorted(rows) == ["SPEAKER_00", "SPEAKER_01"], "reprocessing must not duplicate observations"


# ---------------------------------------------------------------------------
# The reported bug, end to end
# ---------------------------------------------------------------------------


def test_a_new_recordings_stranger_does_not_inherit_the_confirmed_person(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)

    # Recording 1: Ali speaks, is identified by a human, and is enrolled.
    _submit_recording(client, t, s["id"], labels=("SPEAKER_00",), voice=_voice(SPEAKER_00=ALI))
    sp = _speakers(client, t, s["id"])["SPEAKER_00"]
    res = _link_identity(client, t, s["id"], sp["id"], "MIL-ARMY-90001", "علي عباس")
    assert res.status_code == 200, res.text
    res = _enroll(client, t, s["id"], sp["id"], "MIL-ARMY-90001", "علي عباس")
    assert res.status_code in (200, 201), res.text

    # Recording 2: a DIFFERENT human, whose diarizer also calls them SPEAKER_00, and whose
    # voice scores exactly the measured 0.5372 against Ali's print.
    _submit_recording(client, t, s["id"], labels=("SPEAKER_00",), voice=_voice(SPEAKER_00=STRANGER))

    rows = _rows(s["id"])
    assert sorted(rows) == ["SPEAKER_00", "SPEAKER_01"]

    ali_row = rows["SPEAKER_00"]
    stranger_row = rows["SPEAKER_01"]

    # The stranger inherited NOTHING: no identity, no name, and no suggestion (0.5372 < 0.65).
    assert stranger_row["source_label"] == "SPEAKER_00"
    assert stranger_row["identity_id"] is None
    assert stranger_row["display_name"] is None
    assert stranger_row["suggested_name"] is None
    assert stranger_row["status"] == "NONE"

    # Ali's observation is untouched - identity intact AND, critically, his probe embedding
    # was not overwritten by the stranger's voice.
    assert ali_row["display_name"] == "علي عباس"
    assert ali_row["identity_id"] is not None
    assert ali_row["embedding"] == ALI

    # The stranger's own probe landed on the stranger's row.
    assert [round(x, 4) for x in stranger_row["embedding"]] == [round(x, 4) for x in STRANGER]


def test_ali_speaking_again_is_suggested_not_assigned(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit_recording(client, t, s["id"], labels=("SPEAKER_00",), voice=_voice(SPEAKER_00=ALI))
    sp = _speakers(client, t, s["id"])["SPEAKER_00"]
    assert _link_identity(client, t, s["id"], sp["id"], "MIL-ARMY-90002", "علي عباس").status_code == 200
    assert _enroll(client, t, s["id"], sp["id"], "MIL-ARMY-90002", "علي عباس").status_code in (200, 201)

    # Recording 3: Ali again (cos 0.80 vs his print) - a separate observation, biometrically
    # SUGGESTED, and identity_id still NULL until a human confirms.
    _submit_recording(client, t, s["id"], labels=("SPEAKER_00",), voice=_voice(SPEAKER_00=ALI_AGAIN))
    rows = _rows(s["id"])
    again = rows["SPEAKER_01"]
    assert again["status"] == "SUGGESTED"
    assert again["suggested_name"] == "علي عباس"
    assert again["identity_id"] is None, "matching must never assign identity"
    assert again["display_name"] is None


def test_no_candidate_never_falls_back_to_the_last_identified_person(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit_recording(client, t, s["id"], labels=("SPEAKER_00",), voice=_voice(SPEAKER_00=ALI))
    sp = _speakers(client, t, s["id"])["SPEAKER_00"]
    assert _link_identity(client, t, s["id"], sp["id"], "MIL-ARMY-90003", "علي عباس").status_code == 200
    # Deliberately NO enrolment: the gallery is empty.
    _submit_recording(client, t, s["id"], labels=("SPEAKER_00",), voice=_voice(SPEAKER_00=DIFFERENT))
    rows = _rows(s["id"])
    assert rows["SPEAKER_01"]["identity_id"] is None
    assert rows["SPEAKER_01"]["suggested_name"] is None
    assert rows["SPEAKER_01"]["status"] == "NONE"


def test_a_new_session_starts_with_nothing(client, investigator):
    t = investigator["token"]
    s1 = create_session(client, t)
    _submit_recording(client, t, s1["id"], labels=("SPEAKER_00",), voice=_voice(SPEAKER_00=ALI))
    sp = _speakers(client, t, s1["id"])["SPEAKER_00"]
    assert _link_identity(client, t, s1["id"], sp["id"], "MIL-ARMY-90004", "علي عباس").status_code == 200

    s2 = create_session(client, t)
    _submit_recording(client, t, s2["id"], labels=("SPEAKER_00",))
    rows = _rows(s2["id"])
    assert sorted(rows) == ["SPEAKER_00"]
    assert rows["SPEAKER_00"]["identity_id"] is None
    assert rows["SPEAKER_00"]["display_name"] is None
