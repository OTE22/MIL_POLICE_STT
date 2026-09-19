"""بانتظار التسجيل, person search, and the guarantees around them.

Identifying an unknown speaker reuses the EXISTING session workflow: the investigation PUT
adds the person, the speaker PATCH links them. Nothing here introduces a voice-specific
person flow, and `identity_id` is resolved by the backend from the reference number.
"""

from __future__ import annotations

import uuid

from tests.conftest import auth
from tests.test_voice_matching import (
    EMB_A,
    EMB_B,
    _enroll,
    _link_identity,
    _speakers,
    _subject_for,
    _submit,
    _voice,
)


def _candidates(client, token):
    res = client.get("/api/voice-enrollments/candidates", headers=auth(token))
    assert res.status_code == 200, res.text
    return res.json()


def _identify(client, token, session, speaker_id, name, reference):
    """Identify a speaker exactly as the UI does: existing session PUT, then speaker PATCH."""
    res = _link_identity(client, token, session["id"], speaker_id, reference, name)
    assert res.status_code == 200, res.text
    return res.json()


def _ref() -> str:
    return f"MIL-ARMY-{uuid.uuid4().hex[:6].upper()}"


def test_identified_speaker_becomes_a_candidate(client, investigator):
    t = investigator["token"]
    s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, s["id"])

    # An unidentified speaker is never a candidate: an anonymous voice must not be enrolled.
    assert _candidates(client, t) == []

    reference = _ref()
    updated = _identify(client, t, s, sp["SPEAKER_00"]["id"], "أحمد محمد", reference)
    assert updated["identity_id"], "the backend must resolve the identity from the reference"

    rows = _candidates(client, t)
    assert len(rows) == 1
    assert rows[0]["display_name"] == "أحمد محمد"
    assert rows[0]["identity_id"]
    assert rows[0]["enrollment_state"] == "never_enrolled"

    assert _enroll(client, t, s["id"], sp["SPEAKER_00"]["id"], reference, "أحمد محمد").status_code == 201
    assert _candidates(client, t) == [], "an enrolled sample is no longer waiting"


def test_identifying_an_existing_person_creates_no_second_identity(client, investigator):
    """Investigator B naming the same person must land on investigator A's identity."""
    t = investigator["token"]
    reference = _ref()

    first = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp1 = _speakers(client, t, first["id"])
    a = _identify(client, t, first, sp1["SPEAKER_00"]["id"], "الرائد علي حسن", reference)

    second = _submit(client, t, voice=_voice(SPEAKER_00=EMB_B, SPEAKER_01=EMB_A))
    sp2 = _speakers(client, t, second["id"])
    b = _identify(client, t, second, sp2["SPEAKER_00"]["id"], "الرائد علي حسن", reference)

    assert a["identity_id"] == b["identity_id"]
    people = [p for p in client.get(f"/api/voice-enrollments/people?q=الرائد علي حسن", headers=auth(t)).json()
              if p["person_name"] == "الرائد علي حسن"]
    assert len(people) == 1, "one canonical person, not two"


def test_same_reference_different_name_is_refused_for_review(client, investigator):
    t = investigator["token"]
    reference = _ref()
    s1 = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp1 = _speakers(client, t, s1["id"])
    _identify(client, t, s1, sp1["SPEAKER_00"]["id"], "الرائد علي حسن", reference)

    s2 = _submit(client, t, voice=_voice(SPEAKER_00=EMB_B, SPEAKER_01=EMB_A))
    res = client.put(
        f"/api/investigations/{s2['id']}",
        json={"subjects": s2["subjects"] + [_subject_for(reference, "أحمد محمد")]},
        headers=auth(t),
    )
    assert res.status_code == 409
    body = res.json()
    assert body["detail"] == "person_identity_name_mismatch"
    # The UI shows both names, so the investigator can see what to correct.
    assert body["existing_name"] == "الرائد علي حسن"
    assert body["submitted_name"] == "أحمد محمد"


def test_speaker_without_an_embedding_is_never_a_candidate(client, investigator):
    t = investigator["token"]
    s = _submit(client, t)                      # no voice payload at all
    sp = _speakers(client, t, s["id"])
    _identify(client, t, s, sp["SPEAKER_00"]["id"], "أحمد محمد", _ref())
    assert _candidates(client, t) == []


def test_deactivated_print_offers_reactivation_not_a_duplicate(client, investigator):
    t = investigator["token"]
    reference = _ref()
    s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, s["id"])
    _identify(client, t, s, sp["SPEAKER_00"]["id"], "أحمد محمد", reference)
    created = _enroll(client, t, s["id"], sp["SPEAKER_00"]["id"], reference, "أحمد محمد").json()

    client.patch(f"/api/voice-enrollments/{created['id']}", json={"is_active": False}, headers=auth(t))
    rows = _candidates(client, t)
    assert len(rows) == 1
    assert rows[0]["enrollment_state"] == "enrolled_inactive"
    assert rows[0]["inactive_enrollment_id"] == created["id"]


def test_reactivating_over_an_active_print_is_a_clean_conflict(client, investigator):
    """The partial unique index must surface as a 409, never a raw 500."""
    t = investigator["token"]
    reference = _ref()
    s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, s["id"])
    _identify(client, t, s, sp["SPEAKER_00"]["id"], "أحمد محمد", reference)
    first = _enroll(client, t, s["id"], sp["SPEAKER_00"]["id"], reference, "أحمد محمد").json()

    client.patch(f"/api/voice-enrollments/{first['id']}", json={"is_active": False}, headers=auth(t))
    second = _enroll(client, t, s["id"], sp["SPEAKER_00"]["id"], reference, "أحمد محمد")
    assert second.status_code in (200, 201), second.text

    res = client.patch(f"/api/voice-enrollments/{first['id']}", json={"is_active": True}, headers=auth(t))
    assert res.status_code == 409
    assert res.json()["detail"] == "enrollment_already_active"

    rows = client.get("/api/voice-enrollments?include_inactive=true", headers=auth(t)).json()
    active = [r for r in rows if r["person_name"] == "أحمد محمد" and r["is_active"]]
    assert len(active) == 1, "exactly one active print per sample"


def test_person_search_does_not_leak_inaccessible_activity(client, investigator, investigator2):
    """An identity may be reusable without disclosing where else it has been used."""
    t1, t2 = investigator["token"], investigator2["token"]
    reference = _ref()

    s = _submit(client, t1, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t1, s["id"])
    _identify(client, t1, s, sp["SPEAKER_00"]["id"], "الرائد علي حسن", reference)
    assert _enroll(client, t1, s["id"], sp["SPEAKER_00"]["id"], reference, "الرائد علي حسن").status_code == 201

    mine = [p for p in client.get(f"/api/voice-enrollments/people?q=الرائد علي حسن", headers=auth(t1)).json()
            if p["person_name"] == "الرائد علي حسن"]
    assert mine and mine[0]["accessible_print_count"] == 1

    theirs = [p for p in client.get(f"/api/voice-enrollments/people?q=الرائد علي حسن", headers=auth(t2)).json()
              if p["person_name"] == "الرائد علي حسن"]
    assert theirs, "the identity must still be reusable"
    assert theirs[0]["person_name"] == "الرائد علي حسن"
    assert theirs[0]["accessible_print_count"] == 0, "counts must not disclose inaccessible activity"
    assert theirs[0]["accessible_session_count"] == 0


def test_candidates_are_scoped_to_accessible_sessions(client, investigator, investigator2):
    t1, t2 = investigator["token"], investigator2["token"]
    s = _submit(client, t1, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t1, s["id"])
    _identify(client, t1, s, sp["SPEAKER_00"]["id"], "أحمد محمد", _ref())
    assert len(_candidates(client, t1)) == 1
    assert _candidates(client, t2) == [], "another investigator must not discover the speaker"


def test_client_cannot_choose_the_identity(client, investigator):
    """identity_id is backend-owned: a posted UUID must never attach a speaker to a person."""
    t = investigator["token"]
    s1 = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp1 = _speakers(client, t, s1["id"])
    victim = _identify(client, t, s1, sp1["SPEAKER_00"]["id"], "الرائد علي حسن", _ref())

    s2 = _submit(client, t, voice=_voice(SPEAKER_00=EMB_B, SPEAKER_01=EMB_A))
    sp2 = _speakers(client, t, s2["id"])
    res = client.patch(
        f"/api/investigations/{s2['id']}/speakers/{sp2['SPEAKER_00']['id']}",
        json={"display_name": "شخص آخر", "identity_id": victim["identity_id"]},
        headers=auth(t),
    )
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "person_not_in_session"


def test_stale_merged_reference_converges_on_the_survivor(client, investigator):
    """Requirement §2: a stale payload must not keep re-submitting a dead reference."""
    from app.db.session import SessionLocal
    from app.models import PersonIdentity, SessionSpeaker, Subject
    from app.services.person_identity import merge_identities
    from app.services.person_identifiers import find_by_identifier
    def find_identity(db, reference):
        return find_by_identifier(db, identifier_type="MILITARY", issuer="ARMY", value=reference.removeprefix("MIL-ARMY-"))

    t = investigator["token"]
    ref_a, ref_b = _ref(), _ref()

    s1 = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp1 = _speakers(client, t, s1["id"])
    _identify(client, t, s1, sp1["SPEAKER_00"]["id"], "علي حسن", ref_a)

    s2 = _submit(client, t, voice=_voice(SPEAKER_00=EMB_B, SPEAKER_01=EMB_A))
    sp2 = _speakers(client, t, s2["id"])
    _identify(client, t, s2, sp2["SPEAKER_00"]["id"], "علي حسن", ref_b)

    with SessionLocal() as db:
        a = find_identity(db, ref_a)
        b = find_identity(db, ref_b)
        merge_identities(db, b.id, a.id)
        db.commit()
        before = db.query(PersonIdentity).count()

    # A stale tab re-saves the old session, still carrying the merged-away reference.
    updated = _identify(client, t, s2, sp2["SPEAKER_00"]["id"], "علي حسن", ref_b)

    with SessionLocal() as db:
        survivor = find_identity(db, ref_a)
        assert updated["identity_id"] == str(survivor.id), "stale reference must resolve forward"
        assert db.query(PersonIdentity).count() == before, "the merged reference must not be recreated"

        speaker = db.get(SessionSpeaker, uuid.UUID(sp2["SPEAKER_00"]["id"]))
        subject = db.query(Subject).filter(Subject.identity_id == survivor.id).first()
        assert subject is not None and subject.identity_id == survivor.id


def test_an_identified_speaker_with_no_display_name_is_still_a_candidate(client, investigator):
    """The case that made a real speaker invisible.

    display_name is a session-local label. A speaker can be linked to a canonical person while
    that label is blank, and the identity carries the person's name - so keying enrolment on
    display_name hid a genuinely enrollable speaker from بانتظار التسجيل entirely.
    """
    from app.db.session import SessionLocal
    from app.models import SessionSpeaker

    t = investigator["token"]
    reference = _ref()
    s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, s["id"])
    _identify(client, t, s, sp["SPEAKER_00"]["id"], "أحمد محمد", reference)

    # Clear the session-local label, keeping the canonical identity.
    with SessionLocal() as db:
        row = db.get(SessionSpeaker, uuid.UUID(sp["SPEAKER_00"]["id"]))
        row.display_name = None
        db.commit()

    after = _speakers(client, t, s["id"])["SPEAKER_00"]
    assert after["display_name"] is None
    assert after["identity_id"], "the speaker is still identified"
    assert after["identity_name"] == "أحمد محمد", "the canonical name must still be available"
    assert after["identity_id"]

    rows = _candidates(client, t)
    assert len(rows) == 1, "an identified speaker must be enrollable even with a blank label"
    # The label stays blank rather than borrowing the canonical name. The two mean different
    # things - a label may carry a rank - and letting one stand in for the other is what put
    # "الرائد علي حسن" into the registry. The canonical name has its own field.
    assert rows[0]["display_name"] == ""
    assert rows[0]["person_name"] == "أحمد محمد"
    assert rows[0]["identity_id"]


def test_a_speaker_with_no_identity_cannot_be_enrolled(client, investigator):
    """The enrol endpoint refuses it, so the button must never offer it."""
    t = investigator["token"]
    s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, s["id"])

    # Named by hand, no reference - so no canonical identity.
    res = client.patch(
        f"/api/investigations/{s['id']}/speakers/{sp['SPEAKER_00']['id']}",
        json={"display_name": "شاهد مجهول"},
        headers=auth(t),
    )
    assert res.status_code == 200
    assert res.json()["identity_id"] is None

    attempt = _enroll(client, t, s["id"], sp["SPEAKER_00"]["id"], "", "شاهد مجهول")
    assert attempt.status_code in (400, 422), attempt.text
    assert _candidates(client, t) == []
