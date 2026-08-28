"""Saving a session repeatedly must not multiply identities.

`_apply_subjects` rebuilds every Subject row on each save. Two things therefore have to hold:

  * a system-issued TMP reference is allocated ONCE for a participant and carried forward,
    not re-allocated because Save was pressed again;
  * when one person's structured identifiers imply a different canonical reference, the whole
    request stops before anything is written - no half-applied session.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import PersonIdentity, Subject
from tests.conftest import auth, create_session


def _get(client, token, session_id):
    res = client.get(f"/api/investigations/{session_id}", headers=auth(token))
    assert res.status_code == 200, res.text
    return res.json()


def _save(client, token, session_id, payload):
    return client.put(f"/api/investigations/{session_id}", json=payload, headers=auth(token))


def _round_trip(subjects: list[dict]) -> list[dict]:
    """What the form sends back: the server subjects, participation keys included."""
    keep = (
        # participant_key is the ONLY handle that survives the rebuild - `id` is destroyed and
        # re-minted on every save, so a payload without the key is a payload about strangers.
        "participant_key",
        "subject_name", "reference_number", "person_type", "military_id", "rank", "unit",
        "department", "security_branch", "nationality_code", "nationality_name",
        "register_number", "place_of_registration", "caza_code", "is_unregistered",
        "is_undocumented", "undocumented_reason", "identity_confidence", "notes",
    )
    return [{k: s.get(k) for k in keep} for s in subjects]


def _identity_count(reference: str) -> int:
    from app.services.person_identity import normalize_reference

    with SessionLocal() as db:
        return db.scalar(
            select(func.count()).select_from(PersonIdentity).where(
                PersonIdentity.reference_normalized == normalize_reference(reference)
            )
        )


# --------------------------------------------------------------------------
# TMP idempotency
# --------------------------------------------------------------------------

def test_undocumented_person_keeps_one_temporary_reference_across_saves(client, investigator):
    """Pressing Save again must not split one participant into several identities."""
    t = investigator["token"]
    s = create_session(client, t, subjects=[
        {"subject_name": "مجهول الهوية", "person_type": "UNKNOWN", "is_undocumented": True},
    ])

    first = _get(client, t, s["id"])["subjects"]
    assert len(first) == 1
    issued = first[0]["reference_number"]
    assert issued and issued.startswith("TMP-"), f"expected a system-issued reference, got {issued!r}"
    identity_id = first[0].get("identity_id") or None

    # Three more saves, editing something unrelated each time, exactly as the form does.
    for note in ("ملاحظة ١", "ملاحظة ٢", "ملاحظة ٣"):
        current = _get(client, t, s["id"])
        res = _save(client, t, s["id"], {"notes": note, "subjects": _round_trip(current["subjects"])})
        assert res.status_code == 200, res.text
        subjects = _get(client, t, s["id"])["subjects"]
        assert len(subjects) == 1
        assert subjects[0]["reference_number"] == issued, "a new TMP was allocated on re-save"

    assert _identity_count(issued) == 1

    with SessionLocal() as db:
        rows = db.scalars(select(Subject).where(Subject.session_id == uuid.UUID(s["id"]))).all()
        assert len({r.identity_id for r in rows}) == 1
        if identity_id:
            assert str(rows[0].identity_id) == identity_id


def test_two_undocumented_people_keep_their_own_references(client, investigator):
    t = investigator["token"]
    s = create_session(client, t, subjects=[
        {"subject_name": "مجهول أ", "person_type": "UNKNOWN", "is_undocumented": True},
        {"subject_name": "مجهول ب", "person_type": "UNKNOWN", "is_undocumented": True},
    ])
    issued = {x["subject_name"]: x["reference_number"] for x in _get(client, t, s["id"])["subjects"]}
    assert len(set(issued.values())) == 2, "two people must not share one reference"
    assert all(v.startswith("TMP-") for v in issued.values())

    # Save twice more, reordering the list the second time.
    for reorder in (False, True):
        current = _get(client, t, s["id"])["subjects"]
        payload = _round_trip(current)
        if reorder:
            payload.reverse()
        res = _save(client, t, s["id"], {"subjects": payload})
        assert res.status_code == 200, res.text

    after = {x["subject_name"]: x["reference_number"] for x in _get(client, t, s["id"])["subjects"]}
    assert after == issued, "each participant must keep its own reference across saves"


def test_a_civilian_is_issued_a_reference_even_with_nothing_else_filled_in(client, investigator):
    """Being a civilian is itself the classification; no document is needed to become a person.

    This replaces the old rule that a sparse form got nothing: back then a civilian could only
    be keyed off their civil record, so an empty form had nothing to key on. Now the reference
    belongs to the person rather than to their paperwork.
    """
    t = investigator["token"]
    s = create_session(client, t, subjects=[{"subject_name": "أحمد محمد"}])
    subjects = _get(client, t, s["id"])["subjects"]
    assert subjects[0]["reference_number"].startswith("CIV-")


def test_a_person_we_cannot_classify_gets_nothing(client, investigator):
    """A soldier with no service number can be neither derived nor issued to."""
    t = investigator["token"]
    s = create_session(client, t, subjects=[
        {"subject_name": "مجهول", "person_type": "MILITARY", "security_branch": "ARMY"},
    ])
    subjects = _get(client, t, s["id"])["subjects"]
    assert (subjects[0]["reference_number"] or "") == ""


# --------------------------------------------------------------------------
# derivation through the real API
# --------------------------------------------------------------------------

def test_military_reference_is_derived_on_save(client, investigator):
    t = investigator["token"]
    s = create_session(client, t, subjects=[
        {"subject_name": "الرائد علي حسن", "person_type": "MILITARY",
         "security_branch": "ARMY", "military_id": "4471"},
    ])
    subject = _get(client, t, s["id"])["subjects"][0]
    assert subject["reference_number"] == "MIL-ARMY-4471"
    assert _identity_count("MIL-ARMY-4471") == 1


def test_an_operator_reference_is_respected(client, admin_token):
    """Real paperwork does not always fit the rules; the override must survive."""
    # Hand-assigning الرقم المرجعي needs subjects.reference.override, which ADMIN holds
    # and INVESTIGATOR does not: it is the exceptional path, not ordinary data entry.
    t = admin_token
    s = create_session(client, t, subjects=[
        {"subject_name": "الرائد علي حسن", "person_type": "MILITARY",
         "security_branch": "ARMY", "military_id": "4471", "reference_number": "SPECIAL-4471"},
    ])
    assert _get(client, t, s["id"])["subjects"][0]["reference_number"] == "SPECIAL-4471"


# --------------------------------------------------------------------------
# preflight: all-or-nothing
# --------------------------------------------------------------------------

def test_changing_an_identifier_asks_before_switching_identity(client, investigator):
    t = investigator["token"]
    s = create_session(client, t, subjects=[
        {"subject_name": "الرائد علي حسن", "person_type": "MILITARY",
         "security_branch": "ARMY", "military_id": "4471"},
    ])
    current = _get(client, t, s["id"])["subjects"]
    assert current[0]["reference_number"] == "MIL-ARMY-4471"

    payload = _round_trip(current)
    payload[0]["military_id"] = "4472"
    payload[0]["reference_number"] = None          # the form clears it so it re-derives
    res = _save(client, t, s["id"], {"subjects": payload})

    assert res.status_code == 409, res.text
    body = res.json()
    assert body["detail"] == "person_reference_change_required"
    change = body["changes"][0]
    assert change["current_reference"] == "MIL-ARMY-4471"
    assert change["derived_reference"] == "MIL-ARMY-4472"
    assert change["participant_key"] == current[0]["participant_key"]

    # Nothing moved, and no second identity appeared.
    assert _get(client, t, s["id"])["subjects"][0]["reference_number"] == "MIL-ARMY-4471"
    assert _identity_count("MIL-ARMY-4472") == 0


def test_a_conflicting_subject_leaves_the_whole_save_untouched(client, investigator):
    """One person needing review must not half-apply the other people in the same request."""
    t = investigator["token"]
    s = create_session(client, t, subjects=[
        {"subject_name": "الرائد علي حسن", "person_type": "MILITARY",
         "security_branch": "ARMY", "military_id": "4471"},
        {"subject_name": "أحمد محمد", "register_number": "725", "caza_code": "BEIRUT"},
    ])
    current = _get(client, t, s["id"])["subjects"]
    before = {x["subject_name"]: x["reference_number"] for x in current}
    # The civilian is ISSUED a reference; قضاء and رقم السجل are only metadata now.
    assert before["أحمد محمد"].startswith("CIV-")

    # Indexed by name, never by position: `session.subjects` has no ORDER BY, so the order
    # the API returns is whatever PostgreSQL yields and flips between runs.
    payload = _round_trip(current)
    by_name = {row["subject_name"]: row for row in payload}
    by_name["الرائد علي حسن"]["military_id"] = "4472"
    by_name["الرائد علي حسن"]["reference_number"] = None
    by_name["أحمد محمد"]["subject_name"] = "أحمد محمد المعدَّل"  # an unrelated edit in the same request

    res = _save(client, t, s["id"], {"subjects": payload})
    assert res.status_code == 409
    assert res.json()["detail"] == "person_reference_change_required"

    after = _get(client, t, s["id"])["subjects"]
    assert {x["subject_name"]: x["reference_number"] for x in after} == before, (
        "the unrelated edit must not have been persisted"
    )
    assert _identity_count("MIL-ARMY-4472") == 0


def test_several_people_needing_review_are_all_reported(client, investigator):
    """Both military: a civilian reference no longer derives, so it can never need review."""
    t = investigator["token"]
    s = create_session(client, t, subjects=[
        {"subject_name": "الرائد علي حسن", "person_type": "MILITARY",
         "security_branch": "ARMY", "military_id": "4471"},
        {"subject_name": "أحمد محمد", "person_type": "MILITARY",
         "security_branch": "ARMY", "military_id": "9001"},
    ])
    current = _get(client, t, s["id"])["subjects"]
    payload = _round_trip(current)
    by_name = {row["subject_name"]: row for row in payload}
    for name, new_id in (("الرائد علي حسن", "4472"), ("أحمد محمد", "9002")):
        by_name[name]["military_id"] = new_id
        by_name[name]["reference_number"] = None

    res = _save(client, t, s["id"], {"subjects": payload})
    assert res.status_code == 409
    changes = res.json()["changes"]
    assert len(changes) == 2, "every person needing review must be reported, not just the first"
    assert {c["derived_reference"] for c in changes} == {"MIL-ARMY-4472", "MIL-ARMY-9002"}


# --------------------------------------------------------------------------
# an override must not leave the derived reference free for someone else
# --------------------------------------------------------------------------

def test_override_reserves_the_derived_reference(client, admin_token):
    """Investigator A overrides; investigator B enters the same soldier plainly.

    Without reserving the implied reference, B would create a second canonical person for
    the same human and the matcher would treat their prints as rivals again.
    """
    # Hand-assigning الرقم المرجعي needs subjects.reference.override: ADMIN holds it,
    # INVESTIGATOR does not.
    t = admin_token
    first = create_session(client, t, subjects=[
        {"subject_name": "الرائد علي حسن", "person_type": "MILITARY", "security_branch": "ARMY",
         "military_id": "4471", "reference_number": "SPECIAL-4471"},
    ])
    assert _get(client, t, first["id"])["subjects"][0]["reference_number"] == "SPECIAL-4471"

    second = create_session(client, t, subjects=[
        {"subject_name": "الرائد علي حسن", "person_type": "MILITARY", "security_branch": "ARMY",
         "military_id": "4471"},
    ])
    # B typed no reference; derivation produced MIL-ARMY-4471, which resolves through the
    # alias, so the row converges on the canonical reference rather than starting a rival.
    stored = _get(client, t, second["id"])["subjects"][0]["reference_number"]
    assert stored == "SPECIAL-4471", stored

    from app.services.person_identity import find_identity

    with SessionLocal() as db:
        chosen = find_identity(db, "SPECIAL-4471")
        implied = find_identity(db, "MIL-ARMY-4471")
        assert chosen is not None and implied is not None
        assert implied.id == chosen.id, "the derived reference must resolve to the chosen identity"

    with SessionLocal() as db:
        rows = db.scalars(select(Subject).where(
            Subject.session_id.in_([uuid.UUID(first["id"]), uuid.UUID(second["id"])])
        )).all()
        assert len({r.identity_id for r in rows}) == 1, "one canonical person, not two"


def test_override_onto_someone_elses_reference_is_refused(client, admin_token):
    """Never quietly move a real person onto another person's canonical identity."""
    # Hand-assigning الرقم المرجعي needs subjects.reference.override: ADMIN holds it,
    # INVESTIGATOR does not.
    t = admin_token
    create_session(client, t, subjects=[
        {"subject_name": "أحمد محمد", "person_type": "MILITARY", "security_branch": "ARMY",
         "military_id": "9001"},
    ])

    res = client.post(
        "/api/investigations",
        json={"title": "تعارض", "subjects": [
            {"subject_name": "الرائد علي حسن", "person_type": "MILITARY", "security_branch": "ARMY",
             "military_id": "9001", "reference_number": "SPECIAL-9001"},
        ]},
        headers=auth(t),
    )
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == "person_reference_name_mismatch"
