"""Civilians are ISSUED a canonical reference; their civil record never identifies them.

رقم السجل is a family key: an إخراج قيد lists everyone registered under it. Deriving from it
gave relatives one canonical person - refused outright when their names differed, silently
merged when they matched, and naming a son after his grandfather is ordinary here. Merging two
humans into one biometric identity is not recoverable; an extra identity awaiting
consolidation is.

So CIV-* belongs to the person, not to their paperwork: it survives a passport, a قضاء or a
name spelling being corrected, and two relatives are simply two people.
"""

from __future__ import annotations

import threading
import uuid

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import PersonIdentity
from app.services.person_identity import allocate_civilian_reference
from tests.conftest import auth, create_session

KEEP = (
    "participant_key", "subject_name", "reference_number", "person_type", "military_id",
    "rank", "unit", "department", "security_branch", "nationality_code", "nationality_name",
    "register_number", "place_of_registration", "caza_code", "is_unregistered",
    "is_undocumented", "undocumented_reason", "identity_confidence", "notes",
)


def _trip(subjects: list[dict]) -> list[dict]:
    return [{k: s.get(k) for k in KEEP} for s in subjects]


def _civilian(name: str, **over) -> dict:
    body = {"subject_name": name, "person_type": "CIVILIAN"}
    body.update(over)
    return body


def _get(client, token, session_id) -> list[dict]:
    res = client.get(f"/api/investigations/{session_id}", headers=auth(token))
    assert res.status_code == 200, res.text
    return res.json()["subjects"]


def _save(client, token, session_id, subjects):
    return client.put(
        f"/api/investigations/{session_id}", json={"subjects": subjects}, headers=auth(token)
    )


def _identity_of(reference: str):
    from app.services.person_identity import find_identity

    with SessionLocal() as db:
        found = find_identity(db, reference)
        return found.id if found else None


# --------------------------------------------------------------------------
# every civilian gets one, and it is theirs
# --------------------------------------------------------------------------

def test_a_civilian_is_issued_a_reference_the_operator_never_types(client, investigator):
    t = investigator["token"]
    s = create_session(client, t, subjects=[_civilian("علي حسن", caza_code="ZAHLE", register_number="123")])
    subject = _get(client, t, s["id"])[0]

    assert subject["reference_number"].startswith("CIV-")
    # The civil record is still recorded - it is simply not who they are.
    assert subject["caza_code"] == "ZAHLE" and subject["register_number"] == "123"


def test_two_relatives_sharing_a_civil_record_are_two_people(client, investigator):
    """The defect this design exists to remove."""
    t = investigator["token"]
    s = create_session(client, t, subjects=[
        _civilian("علي حسن", caza_code="ZAHLE", register_number="123"),
        _civilian("حسن حسن", caza_code="ZAHLE", register_number="123"),
    ])
    subjects = _get(client, t, s["id"])
    refs = {x["subject_name"]: x["reference_number"] for x in subjects}

    assert refs["علي حسن"] != refs["حسن حسن"]
    assert all(r.startswith("CIV-") for r in refs.values())
    assert _identity_of(refs["علي حسن"]) != _identity_of(refs["حسن حسن"])


def test_two_civilians_sharing_a_name_are_two_people(client, investigator):
    """A name has never been an identity, and is not one now that references are issued."""
    t = investigator["token"]
    s = create_session(client, t, subjects=[_civilian("علي حسن"), _civilian("علي حسن")])
    refs = [x["reference_number"] for x in _get(client, t, s["id"])]
    assert len(set(refs)) == 2
    assert _identity_of(refs[0]) != _identity_of(refs[1])


# --------------------------------------------------------------------------
# stability: the reference belongs to the person, not the paperwork
# --------------------------------------------------------------------------

def test_repeated_saves_never_issue_a_second_reference(client, investigator):
    """No CIV inflation: pressing Save must not keep minting people."""
    t = investigator["token"]
    s = create_session(client, t, subjects=[_civilian("علي حسن")])
    first = _get(client, t, s["id"])[0]

    payload = _trip([first])
    for i in range(3):
        payload[0]["notes"] = f"ملاحظة {i}"
        assert _save(client, t, s["id"], payload).status_code == 200
        payload = _trip(_get(client, t, s["id"]))

    after = _get(client, t, s["id"])[0]
    assert after["reference_number"] == first["reference_number"]
    assert after["participant_key"] == first["participant_key"]
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(PersonIdentity).where(
                PersonIdentity.reference_display == first["reference_number"]
            )
        ) == 1


def test_correcting_documents_does_not_change_who_someone_is(client, investigator):
    """Passport, قضاء, register, nationality, spelling - all metadata about the person."""
    t = investigator["token"]
    s = create_session(client, t, subjects=[_civilian("علي حسن", caza_code="ZAHLE", register_number="123")])
    before = _get(client, t, s["id"])[0]
    identity_before = _identity_of(before["reference_number"])

    payload = _trip([before])
    payload[0].update(
        subject_name="علي حسن الموسوي",     # spelling corrected
        caza_code="BEIRUT",                  # registered elsewhere than first recorded
        register_number="999",
        nationality_code="LB",
    )
    assert _save(client, t, s["id"], payload).status_code == 200

    after = _get(client, t, s["id"])[0]
    assert after["reference_number"] == before["reference_number"]
    assert _identity_of(after["reference_number"]) == identity_before


def test_a_civil_register_reused_by_a_stranger_is_not_a_conflict(client, investigator):
    """Sharing a family record with someone must never read as claiming their identity."""
    t = investigator["token"]
    first = create_session(client, t, subjects=[_civilian("علي حسن", caza_code="ZAHLE", register_number="123")])
    ref_a = _get(client, t, first["id"])[0]["reference_number"]

    second = create_session(client, t, subjects=[_civilian("مريم حسن", caza_code="ZAHLE", register_number="123")])
    ref_b = _get(client, t, second["id"])[0]["reference_number"]

    assert ref_a != ref_b
    assert _identity_of(ref_a) != _identity_of(ref_b)


# --------------------------------------------------------------------------
# reuse across investigations
# --------------------------------------------------------------------------

def test_the_same_person_carried_into_a_second_investigation_is_reused(client, investigator):
    t = investigator["token"]
    first = create_session(client, t, subjects=[_civilian("علي حسن")])
    person = _get(client, t, first["id"])[0]
    reference = person["reference_number"]

    # A second session records the SAME person by carrying their reference, as selecting them
    # from the registry does.
    second = create_session(client, t, subjects=[
        {"subject_name": "علي حسن", "person_type": "CIVILIAN", "reference_number": reference},
    ])
    carried = _get(client, t, second["id"])[0]

    assert carried["reference_number"] == reference, "no second CIV for the same person"
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(PersonIdentity).where(
                PersonIdentity.reference_display == reference
            )
        ) == 1


# --------------------------------------------------------------------------
# the allocator itself
# --------------------------------------------------------------------------

def test_references_are_sequential_and_fixed_width():
    with SessionLocal() as db:
        first = allocate_civilian_reference(db)
        second = allocate_civilian_reference(db)
        db.commit()
    assert first.startswith("CIV-") and len(first) == len("CIV-") + 8
    assert int(first[4:]) + 1 == int(second[4:])


def test_concurrent_civilian_creation_never_collides():
    """A sequence is what makes this safe; COUNT(*)+1 or MAX()+1 would hand out one value.

    Real threads against real PostgreSQL: a sequential 'call it twice' test would pass even
    against an implementation with no database guarantee at all.
    """
    issued: list[str] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def create() -> None:
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            reference = allocate_civilian_reference(db)
            db.commit()
        with lock:
            issued.append(reference)

    threads = [threading.Thread(target=create) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert len(issued) == 2
    assert len(set(issued)) == 2, f"two civilians received the same reference: {issued}"
