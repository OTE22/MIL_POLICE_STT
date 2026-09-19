"""Voice identification: per-person grouping, re-enrolment, and on-demand re-matching.

The unit tests below pin the rule that a person may hold SEVERAL prints. Before this,
`UNIQUE (person_reference, model)` forced operators to invent a new reference number for
the same human, and the matcher - which compared the top two ROWS - then saw two rival
candidates and abstained on a perfect 1.0000 match.
"""

from __future__ import annotations

import uuid

from app.models import VoiceEnrollment
from app.services.voice_matching import best_match, cosine_similarity
from tests.conftest import auth, create_session, request_token, sample_result

MODEL = "nvidia/speakerverification_speakernet"
DIM = 4


# Grouping keys on the canonical identity, not on the enrolment's own person_reference
# (which is only a snapshot of what was recorded at enrolment time). Deriving a stable uuid
# from the reference lets these unit tests express "same person" without a database.
def _identity_of(reference: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_OID, reference)


def _enr(reference: str, name: str, embedding: list[float], *, active: bool = True) -> VoiceEnrollment:
    return VoiceEnrollment(
        id=uuid.uuid4(),
        identity_id=_identity_of(reference),
        person_name=name,
        embedding=embedding,
        embedding_dim=len(embedding),
        model=MODEL,
        consent_recorded=True,
        is_active=active,
    )


VOICE_A = [1.0, 0.0, 0.0, 0.0]
VOICE_A2 = [0.94, 0.34, 0.0, 0.0]   # same person, a slightly different sample
VOICE_B = [0.0, 1.0, 0.0, 0.0]      # a clearly different person


def test_cosine_similarity_bounds():
    assert cosine_similarity(VOICE_A, VOICE_A) == 1.0
    assert cosine_similarity(VOICE_A, VOICE_B) == 0.0
    assert cosine_similarity([], VOICE_A) == 0.0
    assert cosine_similarity([1.0, 2.0], VOICE_A) == 0.0  # dimension mismatch


def test_two_prints_of_the_same_person_do_not_cancel_out():
    """The regression this whole change exists for.

    Two prints of ONE person both score 1.0000. Comparing rows, the margin rule called
    that ambiguous and abstained. Grouped by person there is only one candidate, so the
    match stands.
    """
    enrollments = [
        _enr("MIL-ARMY-1", "الرائد علي حسن", VOICE_A),
        _enr("MIL-ARMY-1", "الرائد علي حسن", VOICE_A),
    ]
    match = best_match(VOICE_A, enrollments, model=MODEL, threshold=0.65, margin=0.05)
    assert match is not None, "two prints of the same person must not suppress the match"
    assert match.enrollment.person_name == "الرائد علي حسن"
    assert match.score == 1.0
    assert match.runner_up is None
    assert match.person_print_count == 2


def test_person_is_scored_by_their_best_print():
    enrollments = [
        _enr("MIL-ARMY-1", "الرائد علي حسن", VOICE_B),   # a poor sample
        _enr("MIL-ARMY-1", "الرائد علي حسن", VOICE_A),   # a good one
    ]
    match = best_match(VOICE_A, enrollments, model=MODEL, threshold=0.65, margin=0.05)
    assert match is not None
    assert match.score == 1.0


def test_two_different_people_too_close_still_abstains():
    """The safety rule must survive the change: rival PEOPLE still produce no suggestion."""
    enrollments = [
        _enr("MIL-ARMY-1", "الرائد علي حسن", VOICE_A),
        _enr("MIL-ARMY-2", "أحمد محمد", VOICE_A),   # a different person, identical score
    ]
    assert best_match(VOICE_A, enrollments, model=MODEL, threshold=0.65, margin=0.05) is None


def test_below_threshold_abstains():
    enrollments = [_enr("MIL-ARMY-1", "الرائد علي حسن", VOICE_B)]
    assert best_match(VOICE_A, enrollments, model=MODEL, threshold=0.65, margin=0.05) is None


def test_inactive_and_other_model_enrolments_are_ignored():
    inactive = _enr("MIL-ARMY-1", "الرائد علي حسن", VOICE_A, active=False)
    other = _enr("MIL-ARMY-2", "أحمد محمد", VOICE_A)
    other.model = "some/other-model"
    assert best_match(VOICE_A, [inactive, other], model=MODEL, threshold=0.65, margin=0.05) is None


def test_same_person_wins_over_a_distant_rival():
    enrollments = [
        _enr("MIL-ARMY-1", "الرائد علي حسن", VOICE_A),
        _enr("MIL-ARMY-1", "الرائد علي حسن", VOICE_A2),
        _enr("MIL-ARMY-2", "أحمد محمد", VOICE_B),
    ]
    match = best_match(VOICE_A, enrollments, model=MODEL, threshold=0.65, margin=0.05)
    assert match is not None
    assert match.enrollment.identity_id == _identity_of("MIL-ARMY-1")
    assert match.person_print_count == 2
    assert match.runner_up == 0.0


# ---------------------------------------------------------------------------
# API level: enrolment rules and on-demand re-matching
# ---------------------------------------------------------------------------

# The submission schema requires at least 16 dimensions, so the API-level tests use
# conforming vectors (the pure best_match tests above stay small and readable).
API_DIM = 16
EMB_A = [1.0] + [0.0] * (API_DIM - 1)
EMB_B = [0.0, 1.0] + [0.0] * (API_DIM - 2)


def _submit(client, token, *, voice=None):
    """Create a session and submit an agent result, optionally with embeddings."""
    s = create_session(client, token)
    tok = request_token(client, token, s["id"])
    body = sample_result()
    if voice is not None:
        body["voice_identification"] = voice
    res = client.post(
        f"/api/local-processing/{tok['job_id']}/result",
        json=body,
        headers=auth(tok["processing_token"]),
    )
    assert res.status_code == 200, res.text
    return s


def _voice(**speakers) -> dict:
    return {
        "provider": "nemo_speakernet",
        "model": MODEL,
        "model_revision": "1.16.0",
        "embedding_dim": API_DIM,
        "device": "cpu",
        "speakers": {k: {"embedding": v, "seconds": 8.0} for k, v in speakers.items()},
    }


def _speakers(client, token, session_id):
    res = client.get(f"/api/investigations/{session_id}/speakers", headers=auth(token))
    assert res.status_code == 200, res.text
    return {s["speaker_label"]: s for s in res.json()}


def _subject_for(reference: str, name: str) -> dict:
    """A participant whose structured identifiers DERIVE the reference we want.

    Ordinary data entry cannot type الرقم المرجعي any more - it is derived, and hand-assigning
    one needs subjects.reference.override. So a test that wants a specific reference has to
    ask for it the way the form does: by supplying the identifiers it comes from.
    """
    prefix, _, military_id = reference.rpartition("-")
    assert prefix == "MIL-ARMY", f"only the military namespace is derivable here: {reference}"
    return {
        "subject_name": name,
        "person_type": "MILITARY",
        "security_branch": "ARMY",
        "military_id": military_id,
    }


def _link_identity(client, token, session_id, speaker_id, reference, name):
    """Establish the canonical person, exactly as تحديد الهوية does in the UI.

    Enrolment no longer creates people - it resolves the speaker's identity_id and refuses
    without one - so a print now requires this step first: the session PUT records the
    person, the speaker PATCH links them, and the backend resolves identity from الرقم
    المرجعي. Returns the failing response when the reference turns out to be someone
    else's, so callers can assert on it.
    """
    current = client.get(f"/api/investigations/{session_id}", headers=auth(token)).json()
    subjects = current.get("subjects") or []
    serial = reference.removeprefix("MIL-ARMY-")
    person = next((p for p in subjects if p.get("military_id") == serial and p.get("security_branch") == "ARMY"), None)
    if person is None or person["subject_name"] != name:
        res = client.put(f"/api/investigations/{session_id}",
                         json={"subjects": subjects + [_subject_for(reference, name)]}, headers=auth(token))
        if res.status_code >= 400:
            return res
        person = next(p for p in res.json()["subjects"] if p.get("military_id") == serial)
    return client.patch(f"/api/investigations/{session_id}/speakers/{speaker_id}",
                        json={"display_name": name, "identity_id": person["identity_id"], "speaker_role": "SUBJECT"},
                        headers=auth(token))


def _enroll(client, token, session_id, speaker_id, reference, name, **over):
    # A reference means "this is a real person" - link them before enrolling. Passing an
    # empty reference deliberately skips this, which is how the "no identity" case is tested.
    if reference:
        linked = _link_identity(client, token, session_id, speaker_id, reference, name)
        if linked.status_code >= 400:
            return linked
    body = {
        "person_name": name,
        "model": MODEL,
        "model_revision": "1.16.0",
        "consent_recorded": True,
    }
    body.update(over)
    return client.post(
        f"/api/investigations/{session_id}/speakers/{speaker_id}/enroll",
        json=body,
        headers=auth(token),
    )


def test_a_person_may_hold_several_prints(client, investigator):
    t = investigator["token"]
    s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, s["id"])
    first = _enroll(client, t, s["id"], sp["SPEAKER_00"]["id"], "MIL-ARMY-1", "الرائد علي حسن")
    assert first.status_code == 201, first.text
    # A second print of the SAME person under the SAME reference is the intended way to
    # improve coverage; it used to be refused with 409 person_already_enrolled.
    second = _enroll(client, t, s["id"], sp["SPEAKER_01"]["id"], "MIL-ARMY-1", "الرائد علي حسن")
    assert second.status_code == 201, second.text
    assert second.json()["id"] != first.json()["id"]


def test_reference_belonging_to_someone_else_is_refused(client, investigator):
    t = investigator["token"]
    s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, s["id"])
    assert _enroll(client, t, s["id"], sp["SPEAKER_00"]["id"], "MIL-ARMY-1", "الرائد علي حسن").status_code == 201
    clash = _enroll(client, t, s["id"], sp["SPEAKER_01"]["id"], "MIL-ARMY-1", "أحمد محمد")
    assert clash.status_code == 409
    assert clash.json()["detail"] == "person_identity_name_mismatch"


def test_enrolling_a_speaker_with_no_embedding_is_refused(client, investigator):
    t = investigator["token"]
    s = _submit(client, t)                       # no voice payload at all
    sp = _speakers(client, t, s["id"])
    assert sp["SPEAKER_00"]["has_voice_embedding"] is False
    res = _enroll(client, t, s["id"], sp["SPEAKER_00"]["id"], "MIL-ARMY-9", "شخص")
    assert res.status_code == 409
    assert res.json()["detail"] == "speaker_has_no_voice_embedding"


def test_rematch_applies_a_voice_enrolled_after_the_session(client, investigator):
    """The gap that left real sessions stuck at NONE forever.

    Matching runs at submission time, so a session processed before the person was
    enrolled never gets a suggestion, no matter what is enrolled later.
    """
    t = investigator["token"]
    # 1. A session processed while the registry is empty -> no suggestion.
    early = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    assert _speakers(client, t, early["id"])["SPEAKER_00"]["identification_status"] == "NONE"

    # 2. The person is enrolled afterwards, from a later session.
    later = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp_later = _speakers(client, t, later["id"])
    assert _enroll(client, t, later["id"], sp_later["SPEAKER_00"]["id"], "MIL-ARMY-1", "الرائد علي حسن").status_code == 201

    # 3. The earlier session is still untouched until a re-scan is asked for.
    assert _speakers(client, t, early["id"])["SPEAKER_00"]["identification_status"] == "NONE"

    res = client.post(f"/api/investigations/{early['id']}/voice-rematch", headers=auth(t))
    assert res.status_code == 200, res.text
    assert res.json()["suggested"] == 1

    after = _speakers(client, t, early["id"])
    assert after["SPEAKER_00"]["identification_status"] == "SUGGESTED"
    assert after["SPEAKER_00"]["suggested_name"] == "الرائد علي حسن"
    # The other voice is nothing like the enrolled one and must stay unidentified.
    assert after["SPEAKER_01"]["identification_status"] == "NONE"


def test_rematch_never_overrides_a_human_decision(client, investigator):
    t = investigator["token"]
    s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, s["id"])
    assert _enroll(client, t, s["id"], sp["SPEAKER_00"]["id"], "MIL-ARMY-1", "الرائد علي حسن").status_code == 201

    client.post(f"/api/investigations/{s['id']}/voice-rematch", headers=auth(t))
    sp = _speakers(client, t, s["id"])
    assert sp["SPEAKER_00"]["identification_status"] == "SUGGESTED"

    # The investigator rejects it; a later re-scan must not resurrect the suggestion.
    res = client.post(
        f"/api/investigations/{s['id']}/speakers/{sp['SPEAKER_00']['id']}/identification",
        json={"accept": False},
        headers=auth(t),
    )
    assert res.status_code == 200, res.text
    client.post(f"/api/investigations/{s['id']}/voice-rematch", headers=auth(t))
    assert _speakers(client, t, s["id"])["SPEAKER_00"]["identification_status"] == "REJECTED"


def test_global_rematch_only_touches_undecided_speakers(client, investigator, admin_token):
    t = investigator["token"]
    s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, s["id"])
    assert _enroll(client, t, s["id"], sp["SPEAKER_00"]["id"], "MIL-ARMY-1", "الرائد علي حسن").status_code == 201

    res = client.post("/api/voice-enrollments/rematch", headers=auth(t))
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["suggested"] == 1
    assert payload["sessions"] >= 1
    assert _speakers(client, t, s["id"])["SPEAKER_00"]["identification_status"] == "SUGGESTED"

    # A re-run finds nothing new: the row is no longer at NONE.
    assert client.post("/api/voice-enrollments/rematch", headers=auth(t)).json()["suggested"] == 0


def test_prints_without_a_canonical_identity_never_match_anyone():
    """Biometric evidence attributed to nobody must not name anybody.

    Grouping once keyed on the enrolment's own person_reference, so two unrelated prints
    sharing a reference string became one person. Rather than key such rows on something else,
    they are now excluded from matching entirely: a print with no identity cannot suggest a
    speaker, and cannot sit in the ranking pushing a real match below the margin either.
    """
    a = _enr("MIL-ARMY-1", "الرائد علي حسن", VOICE_A)
    b = _enr("MIL-ARMY-1", "الرائد علي حسن", VOICE_A)
    a.identity_id = None
    b.identity_id = None
    # Two rival "people" at identical scores -> ambiguous -> abstain, rather than a wrong merge.
    assert best_match(VOICE_A, [a, b], model=MODEL, threshold=0.65, margin=0.05) is None


def test_two_prints_of_one_person_still_suggest_at_identical_scores(client, investigator):
    """The original production regression, end to end.

    One person was enrolled from several sessions. Because each print was treated as its own
    "person", the top two candidates both scored 1.0000, the margin rule called that ambiguous,
    and a PERFECT match produced no suggestion at all. Grouping by canonical identity is what
    fixes it: both prints belong to one person, so there is no rival to be ambiguous with.
    """
    t = investigator["token"]
    reference = f"MIL-ARMY-{uuid.uuid4().hex[:6].upper()}"

    # Two sessions, the SAME voice, enrolled under the SAME canonical reference.
    for _ in range(2):
        s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
        sp = _speakers(client, t, s["id"])
        res = _enroll(client, t, s["id"], sp["SPEAKER_00"]["id"], reference, "الرائد علي حسن")
        assert res.status_code == 201, res.text

    rows = client.get("/api/voice-enrollments", headers=auth(t)).json()
    mine = [r for r in rows if r["person_name"] in ("الرائد علي حسن", "علي حسن")]
    assert len(mine) == 2, "the person should own two prints"
    assert len({r["identity_id"] for r in mine}) == 1, "both prints must share one canonical identity"

    # A third session with that same voice: two prints will each score 1.0000.
    third = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, third["id"])
    assert sp["SPEAKER_00"]["identification_status"] == "SUGGESTED", (
        "identical scores from one person's own prints must not read as ambiguous"
    )
    assert sp["SPEAKER_00"]["suggested_name"] == "الرائد علي حسن"
    assert float(sp["SPEAKER_00"]["suggested_score"]) == 1.0
    assert sp["SPEAKER_01"]["identification_status"] == "NONE"


def test_renaming_the_person_updates_every_print_at_once(client, investigator):
    """Canonical name lives on the identity, so prints follow without a multi-row update."""
    t = investigator["token"]
    reference = f"MIL-ARMY-{uuid.uuid4().hex[:6].upper()}"
    for _ in range(2):
        s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
        sp = _speakers(client, t, s["id"])
        assert _enroll(client, t, s["id"], sp["SPEAKER_00"]["id"], reference, "علي حسن").status_code == 201

    rows = [r for r in client.get("/api/voice-enrollments", headers=auth(t)).json()
            if r["person_name"] in ("الرائد علي حسن", "علي حسن")]
    assert len(rows) == 2

    from app.db.session import SessionLocal
    from app.models import PersonIdentity

    with SessionLocal() as db:
        identity = db.get(PersonIdentity, uuid.UUID(rows[0]["identity_id"]))
        identity.person_name = "الرائد علي حسن"
        db.commit()

    after = [r for r in client.get("/api/voice-enrollments", headers=auth(t)).json()
             if r["person_name"] in ("الرائد علي حسن", "علي حسن")]
    assert {r["person_name"] for r in after} == {"الرائد علي حسن"}, "current name comes from the registry"
    # The enrolment-time snapshot is history and must be preserved, not rewritten.
    assert {r["enrolled_person_name"] for r in after} == {"علي حسن"}
