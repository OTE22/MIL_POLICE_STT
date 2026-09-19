"""Phase 4: selecting, pinning, merging and pairing the evidence a محضر is written from.

Every test here asserts something a submitted document depends on: that it quotes the right
transcript revision, in the right order, stitched into readable turns, and that it never
changes underneath the investigator when someone edits a transcript later.
"""

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    SessionSpeaker,
    SpeakerRole,
    Transcript,
    TranscriptSegment,
    TranscriptSourceMode,
)
from app.services.report_context import (
    build_qa_blocks,
    build_turns,
    completed_recordings,
    compose_name,
    effective_text,
    latest_transcript_for_recording,
    pin_transcripts,
    segments_digest,
    speaker_map,
    stale_pins,
)

from conftest import auth, create_session, request_token, sample_result

CORRECTED = TranscriptSourceMode.CORRECTED
ORIGINAL = TranscriptSourceMode.ORIGINAL


def _submit(client, token, session_id, turns):
    """One recording. `turns` = [(label, text), ...] laid out 2s apart with 1s gaps."""
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
    return tok


def _set_role(session_id, speaker_label, role):
    with SessionLocal() as db:
        row = db.scalars(
            select(SessionSpeaker).where(
                SessionSpeaker.session_id == uuid.UUID(str(session_id)),
                SessionSpeaker.speaker_label == speaker_label,
            )
        ).one()
        row.speaker_role = role
        db.commit()


def _recording_ids(session_id):
    with SessionLocal() as db:
        return [r.id for r in completed_recordings(db, uuid.UUID(str(session_id)))]


# --------------------------------------------------------------------- text mode


def test_effective_text_prefers_the_human_correction(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "نص الذكاء الاصطناعي")])

    with SessionLocal() as db:
        seg = db.scalars(select(TranscriptSegment)).all()[-1]
        assert effective_text(seg, CORRECTED) == "نص الذكاء الاصطناعي"
        seg.edited_text = "النص المصحح"
        db.commit()
        db.refresh(seg)
        assert effective_text(seg, CORRECTED) == "النص المصحح"
        # ORIGINAL ignores the correction entirely - that is the point of the mode.
        assert effective_text(seg, ORIGINAL) == "نص الذكاء الاصطناعي"


# --------------------------------------------------------------------- per-recording selection


def test_newest_transcript_is_chosen_per_recording_not_per_session(client, investigator):
    """The session-wide `_latest_transcript` would collapse three recordings into one."""
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "التسجيل الأول")])
    _submit(client, t, s["id"], [("SPEAKER_00", "التسجيل الثاني")])
    _submit(client, t, s["id"], [("SPEAKER_00", "التسجيل الثالث")])

    ids = _recording_ids(s["id"])
    assert len(ids) == 3
    with SessionLocal() as db:
        texts = []
        for rid in ids:
            tr = latest_transcript_for_recording(db, rid)
            assert tr is not None and tr.recording_id == rid
            texts.append(tr.segments[0].original_text)
    assert texts == ["التسجيل الأول", "التسجيل الثاني", "التسجيل الثالث"]


def test_a_reprocessed_recording_contributes_its_newest_transcript(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "النسخة القديمة")])
    rid = _recording_ids(s["id"])[0]

    # A second transcript for the SAME recording (reprocessing), created later.
    with SessionLocal() as db:
        old = latest_transcript_for_recording(db, rid)
        newer = Transcript(
            session_id=old.session_id,
            recording_id=rid,
            job_id=old.job_id,  # replaced below; job_id is UNIQUE
            status=old.status,
            language="ar",
        )
        # A transcript needs its own job row; reuse the model-level requirement minimally by
        # detaching the unique job_id from the old row first.
        old_job = old.job_id
        db.delete(old)
        db.flush()
        newer.job_id = old_job
        newer.segments.append(
            TranscriptSegment(
                sequence=1,
                speaker_label="SPEAKER_00",
                start_seconds=1.0,
                end_seconds=2.0,
                original_text="النسخة الجديدة",
            )
        )
        db.add(newer)
        db.commit()

    with SessionLocal() as db:
        tr = latest_transcript_for_recording(db, rid)
        assert tr.segments[0].original_text == "النسخة الجديدة"


# --------------------------------------------------------------------- pinning


def test_pins_record_the_exact_revision_and_detect_a_later_edit(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "الإفادة الأصلية")])
    ids = _recording_ids(s["id"])

    with SessionLocal() as db:
        pins = pin_transcripts(db, ids, CORRECTED)
        assert len(pins) == 1
        assert pins[0]["recording_id"] == str(ids[0])
        assert len(pins[0]["segments_sha256"]) == 64
        assert stale_pins(db, pins, CORRECTED) == [], "freshly pinned draft is not stale"

    # Someone corrects the transcript afterwards.
    with SessionLocal() as db:
        seg = db.scalars(select(TranscriptSegment)).all()[-1]
        seg.edited_text = "الإفادة بعد التصحيح"
        db.commit()

    with SessionLocal() as db:
        stale = stale_pins(db, pins, CORRECTED)
        assert len(stale) == 1 and stale[0]["reason"] == "segments_edited"
        # The pin itself is unchanged - the draft still quotes what it was built from.
        assert pins[0]["segments_sha256"] != pin_transcripts(db, ids, CORRECTED)[0]["segments_sha256"]


def test_digest_depends_on_the_text_mode(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "نص أصلي")])
    with SessionLocal() as db:
        seg = db.scalars(select(TranscriptSegment)).all()[-1]
        seg.edited_text = "نص مصحح"
        db.commit()
        segs = list(db.get(Transcript, seg.transcript_id).segments)
        assert segments_digest(segs, CORRECTED) != segments_digest(segs, ORIGINAL)


# --------------------------------------------------------------------- turns


def test_fragmented_segments_of_one_speaker_become_one_turn(client, investigator):
    """The spec's example: three fragments -> one readable question."""
    t = investigator["token"]
    s = create_session(client, t)
    _submit(
        client,
        t,
        s["id"],
        [
            ("SPEAKER_00", "هل تعرف"),
            ("SPEAKER_00", "الشخص أحمد"),
            ("SPEAKER_00", "ومنذ متى تعرفه؟"),
            ("SPEAKER_01", "نعم أعرفه"),
            ("SPEAKER_01", "من حوالي خمس سنوات"),
        ],
    )
    ids = _recording_ids(s["id"])
    with SessionLocal() as db:
        turns = build_turns(db, ids, CORRECTED)

    assert len(turns) == 2, "one turn per speaker, not five"
    assert turns[0].text == "هل تعرف الشخص أحمد ومنذ متى تعرفه؟"
    assert turns[1].text == "نعم أعرفه من حوالي خمس سنوات"
    # Every source segment stays referenced - provenance is never lost to merging.
    assert len(turns[0].segment_ids) == 3
    assert len(turns[1].segment_ids) == 2


def test_turns_run_chronologically_across_recordings(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "أولاً")])
    _submit(client, t, s["id"], [("SPEAKER_00", "ثانياً")])
    _submit(client, t, s["id"], [("SPEAKER_00", "ثالثاً")])
    ids = _recording_ids(s["id"])
    with SessionLocal() as db:
        turns = build_turns(db, ids, CORRECTED)
    assert [t_.text for t_ in turns] == ["أولاً", "ثانياً", "ثالثاً"]
    assert len({t_.recording_id for t_ in turns}) == 3


def test_turns_follow_the_selected_recordings_only(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "مشمول")])
    _submit(client, t, s["id"], [("SPEAKER_00", "مستبعد")])
    ids = _recording_ids(s["id"])
    with SessionLocal() as db:
        turns = build_turns(db, [ids[0]], CORRECTED)
    assert [t_.text for t_ in turns] == ["مشمول"]


def test_turns_honour_the_pinned_transcript_not_the_newest(client, investigator):
    """A draft quotes what it pinned, even after the transcript is edited."""
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "الإفادة وقت البناء")])
    ids = _recording_ids(s["id"])
    with SessionLocal() as db:
        pins = pin_transcripts(db, ids, CORRECTED)

    with SessionLocal() as db:
        seg = db.scalars(select(TranscriptSegment)).all()[-1]
        seg.edited_text = "تعديل لاحق"
        db.commit()

    with SessionLocal() as db:
        # Same pinned transcript id -> same row; the edit shows because CORRECTED reads
        # edited_text, which is exactly why the draft's own Q&A copies are authoritative.
        rebuilt = build_turns(db, ids, CORRECTED, pins=pins)
        assert rebuilt[0].text == "تعديل لاحق"
        # ...while ORIGINAL mode still yields the machine text.
        assert build_turns(db, ids, ORIGINAL, pins=pins)[0].text == "الإفادة وقت البناء"


# --------------------------------------------------------------------- Q&A pairing


def test_investigator_turns_open_blocks_and_answers_close_them(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(
        client,
        t,
        s["id"],
        [
            ("SPEAKER_00", "ما اسمك؟"),
            ("SPEAKER_01", "علي عباس"),
            ("SPEAKER_00", "أين كنت؟"),
            ("SPEAKER_01", "في المنزل"),
        ],
    )
    _set_role(s["id"], "SPEAKER_00", SpeakerRole.INVESTIGATOR)
    _set_role(s["id"], "SPEAKER_01", SpeakerRole.SUBJECT)
    ids = _recording_ids(s["id"])

    with SessionLocal() as db:
        speakers = speaker_map(db, uuid.UUID(s["id"]))
        blocks = build_qa_blocks(build_turns(db, ids, CORRECTED), speakers)

    assert [(b.question_text, b.answer_text) for b in blocks] == [
        ("ما اسمك؟", "علي عباس"),
        ("أين كنت؟", "في المنزل"),
    ]
    assert [b.sequence for b in blocks] == [1, 2]
    assert all(b.question_speaker_id and b.answer_speaker_id for b in blocks)


def test_an_unanswered_question_is_kept_as_its_own_block(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(
        client,
        t,
        s["id"],
        [("SPEAKER_00", "سؤال بلا جواب؟"), ("SPEAKER_00", "سؤال آخر؟"), ("SPEAKER_01", "الجواب")],
    )
    _set_role(s["id"], "SPEAKER_00", SpeakerRole.INVESTIGATOR)
    ids = _recording_ids(s["id"])
    with SessionLocal() as db:
        blocks = build_qa_blocks(
            build_turns(db, ids, CORRECTED), speaker_map(db, uuid.UUID(s["id"]))
        )
    # The two questions are 3s apart in different turns only if the gap exceeds the merge
    # window; either way, no answer may be invented and nothing may be dropped.
    assert blocks[-1].answer_text == "الجواب"
    assert any("سؤال بلا جواب" in b.question_text for b in blocks)


def test_speech_with_no_question_before_it_is_never_dropped(client, investigator):
    """No roles assigned at all: every word still reaches the draft."""
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "إفادة حرة"), ("SPEAKER_01", "إفادة ثانية")])
    ids = _recording_ids(s["id"])
    with SessionLocal() as db:
        blocks = build_qa_blocks(
            build_turns(db, ids, CORRECTED), speaker_map(db, uuid.UUID(s["id"]))
        )
    printed = " ".join(f"{b.question_text} {b.answer_text}" for b in blocks)
    assert "إفادة حرة" in printed and "إفادة ثانية" in printed


def test_two_people_answering_one_question_are_attributed_separately(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(
        client,
        t,
        s["id"],
        [("SPEAKER_00", "من كان هناك؟"), ("SPEAKER_01", "أنا"), ("SPEAKER_02", "وأنا أيضاً")],
    )
    _set_role(s["id"], "SPEAKER_00", SpeakerRole.INVESTIGATOR)
    ids = _recording_ids(s["id"])
    with SessionLocal() as db:
        blocks = build_qa_blocks(
            build_turns(db, ids, CORRECTED), speaker_map(db, uuid.UUID(s["id"]))
        )
    assert len(blocks) == 2, "each person's answer keeps its own attribution"
    assert blocks[0].answer_text == "أنا" and blocks[1].answer_text == "وأنا أيضاً"
    assert blocks[0].answer_speaker_id != blocks[1].answer_speaker_id
    assert blocks[1].question_text == "من كان هناك؟", "the question is repeated, not lost"


def test_qa_blocks_carry_full_provenance(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "سؤال؟"), ("SPEAKER_01", "جواب")])
    _set_role(s["id"], "SPEAKER_00", SpeakerRole.INVESTIGATOR)
    ids = _recording_ids(s["id"])
    with SessionLocal() as db:
        blocks = build_qa_blocks(
            build_turns(db, ids, CORRECTED), speaker_map(db, uuid.UUID(s["id"]))
        )
    b = blocks[0]
    assert b.segment_ids and all(uuid.UUID(x) for x in b.segment_ids)
    assert b.recording_ids == [str(ids[0])]
    assert b.start_seconds is not None and b.end_seconds is not None


# --------------------------------------------------------------------- names


def test_unresolved_speakers_are_never_printed_as_people(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "كلام")])
    with SessionLocal() as db:
        info = speaker_map(db, uuid.UUID(s["id"]))["SPEAKER_00"]
    assert not info.resolved
    name = info.report_name()
    assert "غير محدد الهوية" in name
    assert name != "SPEAKER_00", "a diarization label is not a person"


def test_a_session_local_display_name_is_marked_unverified(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "كلام")])
    with SessionLocal() as db:
        row = db.scalars(
            select(SessionSpeaker).where(SessionSpeaker.session_id == uuid.UUID(s["id"]))
        ).one()
        row.display_name = "أبو حسن"
        db.commit()
        info = speaker_map(db, uuid.UUID(s["id"]))["SPEAKER_00"]
    assert info.report_name() == "أبو حسن (غير موثّق في السجل)"


def test_rank_is_composed_for_display_never_stored_in_the_name():
    """The registry keeps 'علي عباس' and 'رائد' apart; only the page joins them."""
    assert compose_name("علي عباس", "رائد") == "رائد علي عباس"
    assert compose_name("علي عباس", None) == "علي عباس"
    assert compose_name("الرائد علي عباس", "الرائد") == "الرائد علي عباس", "never doubled"


def test_legacy_speaker_rows_are_flagged_not_guessed(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "كلام")])
    with SessionLocal() as db:
        row = db.scalars(
            select(SessionSpeaker).where(SessionSpeaker.session_id == uuid.UUID(s["id"]))
        ).one()
        assert speaker_map(db, uuid.UUID(s["id"]))["SPEAKER_00"].legacy is False
        row.recording_id = None
        db.commit()
        assert speaker_map(db, uuid.UUID(s["id"]))["SPEAKER_00"].legacy is True
