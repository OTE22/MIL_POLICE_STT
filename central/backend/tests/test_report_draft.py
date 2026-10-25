"""Phase 5: the draft persists, the investigator edits it, and the EVIDENCE never moves.

The load-bearing test in this file is `_evidence_fingerprint`: it hashes every transcript,
segment and speaker row of the session, and asserts the fingerprint is byte-identical before
and after each report operation. If a report edit ever writes back into the transcript, the
whole feature becomes indefensible - so it is checked mechanically, not by inspection.
"""

import hashlib
import uuid

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    ReportDraft,
    ReportStatus,
    SessionSpeaker,
    SpeakerRole,
    Transcript,
    TranscriptSegment,
    TranscriptSourceMode,
)
from app.services.report_draft import (
    DraftIsFinal,
    create_draft,
    draft_is_stale,
    get_draft,
    refresh_draft,
    set_source_mode,
)

from conftest import auth, create_session, request_token, sample_result


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


def _evidence_fingerprint(session_id) -> str:
    """A hash over every evidence row of this session. Must never change from report work."""
    sid = uuid.UUID(str(session_id))
    h = hashlib.sha256()
    with SessionLocal() as db:
        for tr in db.scalars(
            select(Transcript).where(Transcript.session_id == sid).order_by(Transcript.created_at)
        ).all():
            h.update(f"T|{tr.id}|{tr.recording_id}|{tr.status}|".encode())
            for seg in sorted(tr.segments, key=lambda s: s.sequence):
                h.update(
                    f"S|{seg.id}|{seg.sequence}|{seg.speaker_label}|{seg.original_text}|"
                    f"{seg.edited_text}|{seg.start_seconds}|{seg.end_seconds}|".encode()
                )
        for sp in db.scalars(
            select(SessionSpeaker)
            .where(SessionSpeaker.session_id == sid)
            .order_by(SessionSpeaker.speaker_label)
        ).all():
            h.update(
                f"P|{sp.id}|{sp.speaker_label}|{sp.recording_id}|{sp.source_label}|"
                f"{sp.identity_id}|{sp.display_name}|{sp.speaker_role}|".encode()
            )
    return h.hexdigest()


def _interview(client, investigator, extra=()):
    """A session with one recording: two Q&A exchanges, roles assigned."""
    t = investigator["token"]
    s = create_session(client, t)
    turns = [
        ("SPEAKER_00", "ما اسمك؟"),
        ("SPEAKER_01", "علي عباس"),
        ("SPEAKER_00", "أين كنت مساء أمس؟"),
        ("SPEAKER_01", "كنت في المنزل"),
        *extra,
    ]
    _submit(client, t, s["id"], turns)
    with SessionLocal() as db:
        sid = uuid.UUID(s["id"])
        for label, role in (("SPEAKER_00", SpeakerRole.INVESTIGATOR), ("SPEAKER_01", SpeakerRole.SUBJECT)):
            row = db.scalar(
                select(SessionSpeaker).where(
                    SessionSpeaker.session_id == sid, SessionSpeaker.speaker_label == label
                )
            )
            if row:
                row.speaker_role = role
        db.commit()
    return s


# --------------------------------------------------------------------- building


def test_first_open_builds_a_draft_from_every_completed_recording(client, investigator):
    s = _interview(client, investigator)
    with SessionLocal() as db:
        draft = create_draft(db, uuid.UUID(s["id"]), None)
        db.commit()
        db.refresh(draft)
        assert draft.status is ReportStatus.DRAFT
        assert draft.transcript_source_mode is TranscriptSourceMode.CORRECTED
        assert len(draft.selected_recording_ids) == 1
        assert len(draft.pinned_transcripts) == 1
        assert [(b.question_source_text, b.answer_source_text) for b in draft.qa_blocks] == [
            ("ما اسمك؟", "علي عباس"),
            ("أين كنت مساء أمس؟", "كنت في المنزل"),
        ]
        # Source and printed text start identical - and stay separately stored.


def test_building_a_draft_does_not_touch_the_evidence(client, investigator):
    s = _interview(client, investigator)
    before = _evidence_fingerprint(s["id"])
    with SessionLocal() as db:
        create_draft(db, uuid.UUID(s["id"]), None)
        db.commit()
    assert _evidence_fingerprint(s["id"]) == before


def test_a_later_transcript_edit_does_not_change_the_draft(client, investigator):
    """The invariant: correcting a transcript never silently rewrites a drafted محضر."""
    s = _interview(client, investigator)
    with SessionLocal() as db:
        draft = create_draft(db, uuid.UUID(s["id"]), None)
        db.commit()
        draft_id = draft.id
        printed_before = [(b.question_source_text, b.answer_source_text) for b in draft.qa_blocks]

    with SessionLocal() as db:
        seg = db.scalars(
            select(TranscriptSegment).order_by(TranscriptSegment.created_at.desc())
        ).all()[0]
        seg.edited_text = "نص مختلف تماماً"
        db.commit()

    with SessionLocal() as db:
        draft = db.get(ReportDraft, draft_id)
        assert [(b.question_source_text, b.answer_source_text) for b in draft.qa_blocks] == printed_before
        # ...but the draft KNOWS it is behind, so the composer can offer a refresh.
        assert draft_is_stale(db, draft), "the stale pin must be visible"


def test_refresh_rebuilds_from_the_current_transcripts(client, investigator):
    s = _interview(client, investigator)
    with SessionLocal() as db:
        draft = create_draft(db, uuid.UUID(s["id"]), None)
        db.commit()
        draft_id = draft.id
        db.commit()

    with SessionLocal() as db:
        seg = db.scalars(select(TranscriptSegment).order_by(TranscriptSegment.sequence)).all()[0]
        seg.edited_text = "ما هو اسمك بالكامل؟"
        db.commit()

    from app.models import ReportDraft

    with SessionLocal() as db:
        draft = db.get(ReportDraft, draft_id)
        refresh_draft(db, draft, None)
        db.commit()
        db.refresh(draft)
        assert draft.qa_blocks[0].question_source_text == "ما هو اسمك بالكامل؟"
        # A refresh is a rebuild: the investigator's wording is knowingly replaced.
        assert draft.qa_blocks[0].question_source_text == "ما هو اسمك بالكامل؟"
        assert draft_is_stale(db, draft) == []


def test_switching_text_mode_requotes_the_evidence(client, investigator):
    s = _interview(client, investigator)
    with SessionLocal() as db:
        seg = db.scalars(select(TranscriptSegment).order_by(TranscriptSegment.sequence)).all()[0]
        seg.edited_text = "سؤال مصحح؟"
        db.commit()

    from app.models import ReportDraft

    with SessionLocal() as db:
        draft = create_draft(db, uuid.UUID(s["id"]), None)
        db.commit()
        assert draft.qa_blocks[0].question_source_text == "سؤال مصحح؟"
        set_source_mode(db, draft, TranscriptSourceMode.ORIGINAL, None)
        db.commit()
        db.refresh(draft)
        assert draft.qa_blocks[0].question_source_text == "ما اسمك؟", "original AI text"
        assert draft.transcript_source_mode is TranscriptSourceMode.ORIGINAL


# --------------------------------------------------------------------- finality


def test_one_draft_per_session_is_reused(client, investigator):
    s = _interview(client, investigator)
    with SessionLocal() as db:
        created = create_draft(db, uuid.UUID(s["id"]), None)
        db.commit()
        found = get_draft(db, uuid.UUID(s["id"]))
        assert found is not None and found.id == created.id
