"""Phase 7 (backend half): the composer's endpoints.

Permission and session access are checked BEFORE anything is written, the draft is created
once and reused, and every Q&A operation leaves the transcript exactly as it found it.
"""

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import SessionSpeaker, SpeakerRole, TranscriptSegment

from conftest import ADMIN, auth, create_session, request_token, sample_result
from test_report_draft import _evidence_fingerprint


def _login(client):
    return client.post("/api/auth/login", json=ADMIN).json()["access_token"]


def _submit(client, token, session_id, turns):
    tok = request_token(client, token, session_id)
    body = sample_result()
    body["segments"] = [
        {
            "speaker_label": label,
            "start_seconds": 1.0 + 3 * i,
            "end_seconds": 2.0 + 3 * i,
            "text": text,
            "is_overlap": False,
        }
        for i, (label, text) in enumerate(turns)
    ]
    body["speaker_count"] = len({label for label, _ in turns})
    res = client.post(
        f"/api/local-processing/{tok['job_id']}/result",
        json=body,
        headers=auth(tok["processing_token"]),
    )
    assert res.status_code == 200, res.text


def _interview(client, token):
    s = create_session(client, token)
    _submit(
        client,
        token,
        s["id"],
        [
            ("SPEAKER_00", "ما اسمك؟"),
            ("SPEAKER_01", "علي عباس"),
            ("SPEAKER_00", "أين كنت مساء أمس؟"),
            ("SPEAKER_01", "كنت في المنزل"),
        ],
    )
    with SessionLocal() as db:
        sid = uuid.UUID(s["id"])
        for label, role in (("SPEAKER_00", SpeakerRole.INVESTIGATOR), ("SPEAKER_01", SpeakerRole.SUBJECT)):
            row = db.scalar(
                select(SessionSpeaker).where(
                    SessionSpeaker.session_id == sid, SessionSpeaker.speaker_label == label
                )
            )
            row.speaker_role = role
        db.commit()
    transcript = client.get(f"/api/investigations/{s['id']}/transcript", headers=auth(token)).json()
    reviewed = client.post(f"/api/investigations/{s['id']}/transcripts/{transcript['id']}/review",
                           headers=auth(token), json={"expected_token": transcript["current_review_token"]})
    assert reviewed.status_code == 200, reviewed.text
    return s


def _create(client, token, session_id):
    res = client.post(f"/api/investigations/{session_id}/report/html", headers=auth(token), json={})
    assert res.status_code in (200, 201), res.text
    from app.models import ReportDraft
    with SessionLocal() as db:
        draft = db.scalar(select(ReportDraft).where(ReportDraft.session_id == uuid.UUID(session_id)))
        return {"id": str(draft.id), "qa_blocks": [
            {"id": str(b.id), "answer_speaker_id": str(b.answer_speaker_id) if b.answer_speaker_id else None,
             "report_question_text": b.question_source_text, "report_answer_text": b.answer_source_text,
             "question_speaker_id": str(b.question_speaker_id) if b.question_speaker_id else None,
             "source_segment_ids": b.source_segment_ids, "answer_source_text": b.answer_source_text,
             "start_seconds": b.start_seconds}
            for b in draft.qa_blocks]}


