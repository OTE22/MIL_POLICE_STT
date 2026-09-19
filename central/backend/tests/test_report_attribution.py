"""The join the محضر تحقيق builder will use must never attribute one person's words to another.

The report combines SEVERAL recordings of one session into a single chronological document.
Every diarizer emits SPEAKER_00 for its own first voice, so before recording-local
provenance existed, four recordings shared one speaker row and a person confirmed in
recording 1 silently owned everyone else's lines. In a submitted investigation file that is
not a display bug - it is testimony attributed to the wrong human.

These tests pin the attribution path the report builder consumes:

    transcript_segments.speaker_label  ->  session_speakers (session_id, speaker_label)
                                       ->  person_identities.identity_id

Phase 2 of the report work: prove the path is collision-free BEFORE any report code exists.
"""

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import PersonIdentity, SessionSpeaker, Transcript

from conftest import auth, create_session, request_token, sample_result
from test_speaker_identity_isolation import ALI, STRANGER, _submit_recording
from test_voice_matching import _enroll, _link_identity, _speakers, _voice


def _submit_with_text(client, token, session_id, label, lines):
    """One recording whose single diarized speaker `label` says `lines`."""
    tok = request_token(client, token, session_id)
    body = sample_result()
    body["segments"] = [
        {
            "speaker_label": label,
            "start_seconds": 1.0 + 2 * i,
            "end_seconds": 2.0 + 2 * i,
            "text": text,
            "is_overlap": False,
        }
        for i, text in enumerate(lines)
    ]
    body["speaker_count"] = 1
    res = client.post(
        f"/api/local-processing/{tok['job_id']}/result",
        json=body,
        headers=auth(tok["processing_token"]),
    )
    assert res.status_code == 200, res.text
    return tok


def _attributed_lines(session_id):
    """Exactly the report builder's join: every segment of the session, resolved to a person.

    Returns [(person_name or None, speaker_label, recording_id, text), ...] in the order the
    report would read them.
    """
    with SessionLocal() as db:
        sid = uuid.UUID(str(session_id))
        speakers = {
            s.speaker_label: s
            for s in db.scalars(select(SessionSpeaker).where(SessionSpeaker.session_id == sid)).all()
        }
        identities = {
            i.id: i.person_name
            for i in db.scalars(
                select(PersonIdentity).where(
                    PersonIdentity.id.in_([s.identity_id for s in speakers.values() if s.identity_id])
                )
            ).all()
        }
        out = []
        transcripts = db.scalars(
            select(Transcript).where(Transcript.session_id == sid).order_by(Transcript.created_at)
        ).all()
        for t in transcripts:
            for seg in t.segments:  # relationship is ordered by sequence
                sp = speakers.get(seg.speaker_label)
                name = identities.get(sp.identity_id) if sp and sp.identity_id else None
                out.append((name, seg.speaker_label, t.recording_id, seg.edited_text or seg.original_text))
        return out


def test_two_recordings_same_local_label_never_share_a_person(client, investigator):
    """Ali confirmed in recording 1; a different human, also diarized SPEAKER_00, in
    recording 2. The report must quote each of them separately."""
    t = investigator["token"]
    s = create_session(client, t)

    # Recording 1 - Ali, identified by a human and enrolled.
    _submit_recording(client, t, s["id"], labels=("SPEAKER_00",), voice=_voice(SPEAKER_00=ALI))
    sp = _speakers(client, t, s["id"])["SPEAKER_00"]
    assert _link_identity(client, t, s["id"], sp["id"], "MIL-ARMY-70001", "علي عباس").status_code == 200
    assert _enroll(client, t, s["id"], sp["id"], "MIL-ARMY-70001", "علي عباس").status_code in (200, 201)

    # Recording 2 - a stranger the diarizer ALSO calls SPEAKER_00 (0.5372 vs Ali = no match).
    _submit_recording(client, t, s["id"], labels=("SPEAKER_00",), voice=_voice(SPEAKER_00=STRANGER))

    with SessionLocal() as db:
        rows = db.scalars(
            select(SessionSpeaker).where(SessionSpeaker.session_id == uuid.UUID(s["id"]))
        ).all()

    assert len(rows) == 2, "one observation per (recording, local label)"
    assert {r.source_label for r in rows} == {"SPEAKER_00"}, "same local label in both recordings"
    assert len({r.recording_id for r in rows}) == 2, "different recordings"
    assert len({r.speaker_label for r in rows}) == 2, "distinct VISIBLE labels - what segments carry"

    identified = [r for r in rows if r.identity_id is not None]
    assert len(identified) == 1, "only the human-confirmed observation carries an identity"


def test_report_join_quotes_each_person_only_their_own_lines(client, investigator):
    """The end-to-end guarantee: no line of recording 2 is attributed to Ali."""
    t = investigator["token"]
    s = create_session(client, t)

    _submit_with_text(client, t, s["id"], "SPEAKER_00", ["أنا علي عباس", "كنت في المركز"])
    ali_sp = _speakers(client, t, s["id"])["SPEAKER_00"]
    assert _link_identity(client, t, s["id"], ali_sp["id"], "MIL-ARMY-70002", "علي عباس").status_code == 200

    # A second recording, same local label, DIFFERENT human, never identified.
    _submit_with_text(client, t, s["id"], "SPEAKER_00", ["أنا شخص آخر", "لم أكن هناك"])

    lines = _attributed_lines(s["id"])
    assert len(lines) == 4

    by_person = {}
    for name, _label, _rec, text in lines:
        by_person.setdefault(name, []).append(text)

    assert by_person["علي عباس"] == ["أنا علي عباس", "كنت في المركز"]
    # The unidentified speaker's testimony stays unattributed - never folded into Ali's.
    assert by_person[None] == ["أنا شخص آخر", "لم أكن هناك"]
    assert "أنا شخص آخر" not in by_person["علي عباس"]

    # Both recordings are represented, each with its own visible label.
    assert len({rec for _n, _l, rec, _t in lines}) == 2
    assert len({label for _n, label, _r, _t in lines}) == 2


def test_the_same_person_across_two_recordings_resolves_to_one_identity(client, investigator):
    """The inverse guarantee: separate observations MAY share a person when a human says so,
    so the report groups their testimony under one name."""
    t = investigator["token"]
    s = create_session(client, t)

    _submit_with_text(client, t, s["id"], "SPEAKER_00", ["الجواب الأول"])
    first = _speakers(client, t, s["id"])["SPEAKER_00"]
    assert _link_identity(client, t, s["id"], first["id"], "MIL-ARMY-70003", "وليد الايوبي").status_code == 200

    _submit_with_text(client, t, s["id"], "SPEAKER_00", ["الجواب الثاني"])
    second = _speakers(client, t, s["id"])["SPEAKER_01"]
    assert _link_identity(client, t, s["id"], second["id"], "MIL-ARMY-70003", "وليد الايوبي").status_code == 200

    lines = _attributed_lines(s["id"])
    assert [name for name, *_ in lines] == ["وليد الايوبي", "وليد الايوبي"]
    # Two separate observations, ONE canonical person.
    with SessionLocal() as db:
        rows = db.scalars(
            select(SessionSpeaker).where(SessionSpeaker.session_id == uuid.UUID(s["id"]))
        ).all()
    assert len(rows) == 2
    assert len({r.identity_id for r in rows}) == 1


def test_legacy_rows_without_provenance_are_recognisable(client, investigator):
    """Rows created before provenance existed have recording_id NULL. The report must be able
    to FLAG them (ملاحظة قديمة بلا مصدر تسجيل) rather than guess which recording they came
    from - so the builder needs this to be detectable, never invented."""
    t = investigator["token"]
    s = create_session(client, t)
    _submit_recording(client, t, s["id"], labels=("SPEAKER_00",))

    with SessionLocal() as db:
        sid = uuid.UUID(s["id"])
        row = db.scalars(select(SessionSpeaker).where(SessionSpeaker.session_id == sid)).one()
        assert row.recording_id is not None, "new rows always carry provenance"
        # Simulate a pre-provenance row exactly as the database holds them.
        row.recording_id = None
        row.source_label = None
        db.commit()

        legacy = db.scalars(select(SessionSpeaker).where(SessionSpeaker.session_id == sid)).one()
        assert legacy.recording_id is None and legacy.source_label is None
        assert legacy.speaker_label, "the visible label still resolves segments"
