"""Deletion and lost state must not look the same to the server.

`_apply_subjects` replaces the whole subject collection, so a participant missing from the
payload is ambiguous: the operator may have removed them, or the client may simply have lost
the row. The old code could not tell, and resolved it by re-allocating - splitting one
undocumented human into two canonical people whenever Save was pressed with a stale payload.

`participant_key` is the handle that survives the rebuild (`Subject.id` does not - it is
destroyed and re-minted every save), and `removed_participant_keys` states deletion instead of
inferring it. Only one combination is genuinely unanswerable, and that one fails closed.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import PersonIdentity, Subject
from tests.conftest import auth, create_session

KEEP = (
    "participant_key", "subject_name", "reference_number", "person_type", "military_id",
    "rank", "unit", "department", "security_branch", "nationality_code", "nationality_name",
    "register_number", "place_of_registration", "caza_code", "is_unregistered",
    "is_undocumented", "undocumented_reason", "identity_confidence", "notes",
)

NAME_A = "مجهول أ"
NAME_B = "مجهول ب"
NAME_C = "مجهول ج"


def _trip(subjects: list[dict]) -> list[dict]:
    """What the form sends back, participant_key included."""
    return [{k: s.get(k) for k in KEEP} for s in subjects]


def _undocumented(name: str) -> dict:
    return {"subject_name": name, "person_type": "UNKNOWN", "is_undocumented": True}


def _get(client, token, session_id) -> list[dict]:
    res = client.get(f"/api/investigations/{session_id}", headers=auth(token))
    assert res.status_code == 200, res.text
    return res.json()["subjects"]


def _save(client, token, session_id, subjects, removed=None):
    body = {"subjects": subjects}
    if removed is not None:
        body["removed_participant_keys"] = removed
    return client.put(f"/api/investigations/{session_id}", json=body, headers=auth(token))


def _two_undocumented(client, token):
    s = create_session(client, token, subjects=[_undocumented(NAME_A), _undocumented(NAME_B)])
    subjects = _get(client, token, s["id"])
    by_name = {x["subject_name"]: x for x in subjects}
    assert by_name[NAME_A]["reference_number"].startswith("TMP-")
    assert by_name[NAME_B]["reference_number"].startswith("TMP-")
    assert by_name[NAME_A]["reference_number"] != by_name[NAME_B]["reference_number"]
    return s, subjects, by_name


# --------------------------------------------------------------------------
# the two cases that used to be indistinguishable
# --------------------------------------------------------------------------

def test_removing_one_participant_and_adding_another_in_one_save(client, investigator):
    """The flow the form actually produces: the subject list is edited, then saved once."""
    t = investigator["token"]
    s, subjects, by_name = _two_undocumented(client, t)
    tmp_a = by_name[NAME_A]["reference_number"]
    key_a = by_name[NAME_A]["participant_key"]
    key_b = by_name[NAME_B]["participant_key"]

    payload = [x for x in _trip(subjects) if x["subject_name"] != NAME_B]
    payload.append(_undocumented(NAME_C))

    res = _save(client, t, s["id"], payload, removed=[key_b])
    assert res.status_code == 200, res.text

    after = {x["subject_name"]: x for x in _get(client, t, s["id"])}
    assert set(after) == {NAME_A, NAME_C}
    # A is untouched, all the way down to its participation handle.
    assert after[NAME_A]["reference_number"] == tmp_a
    assert after[NAME_A]["participant_key"] == key_a
    # C is genuinely new: exactly one key and exactly one TMP, not a recycled one.
    assert after[NAME_C]["reference_number"].startswith("TMP-")
    assert after[NAME_C]["reference_number"] != tmp_a
    assert after[NAME_C]["participant_key"] not in (key_a, key_b)


def test_a_lost_participant_alongside_a_new_one_fails_closed(client, investigator):
    """B has lost its handle AND its reference, and something new wants a TMP. Unanswerable."""
    t = investigator["token"]
    s, subjects, by_name = _two_undocumented(client, t)
    tmp_a = by_name[NAME_A]["reference_number"]
    tmp_b = by_name[NAME_B]["reference_number"]

    payload = [x for x in _trip(subjects) if x["subject_name"] != NAME_B]
    payload.append(_undocumented(NAME_C))
    # No removed_participant_keys: the client is not claiming B was deleted.
    res = _save(client, t, s["id"], payload)
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == "participant_reference_required"
    # The refusal says nothing about the participant it could not place.
    assert "مجهول" not in res.text and "TMP-" not in res.text

    after = {x["subject_name"]: x["reference_number"] for x in _get(client, t, s["id"])}
    assert after == {NAME_A: tmp_a, NAME_B: tmp_b}, "nothing may be mutated"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Subject)) == 2

    # Stating the intent resolves it.
    res = _save(client, t, s["id"], payload, removed=[by_name[NAME_B]["participant_key"]])
    assert res.status_code == 200, res.text


# --------------------------------------------------------------------------
# carry-forward and rejections
# --------------------------------------------------------------------------

def test_reorder_and_unrelated_edits_never_reallocate(client, investigator):
    t = investigator["token"]
    s, subjects, _ = _two_undocumented(client, t)
    before = {x["subject_name"]: (x["participant_key"], x["reference_number"]) for x in subjects}

    with SessionLocal() as db:
        identities_before = db.scalar(select(func.count()).select_from(PersonIdentity))

    payload = _trip(subjects)
    for _ in range(3):
        payload = list(reversed(payload))
        payload[0]["notes"] = f"ملاحظة {uuid.uuid4().hex[:4]}"
        res = _save(client, t, s["id"], payload)
        assert res.status_code == 200, res.text
        payload = _trip(_get(client, t, s["id"]))

    after = {x["subject_name"]: (x["participant_key"], x["reference_number"]) for x in _get(client, t, s["id"])}
    assert after == before
    with SessionLocal() as db:
        # A DELTA, not a total: the investigator running the session is a canonical person too
        # now, so a fixed count would break on a change that has nothing to do with reordering.
        # What matters here is that reordering allocated nothing new.
        assert db.scalar(select(func.count()).select_from(PersonIdentity)) == identities_before


def test_the_key_alone_carries_an_issued_reference_forward(client, investigator):
    """The key is the ONLY mechanism: `id` is dead after a rebuild and nothing re-derives."""
    t = investigator["token"]
    s, subjects, by_name = _two_undocumented(client, t)
    payload = _trip(subjects)
    for row in payload:
        row["reference_number"] = None      # the form dropped it; only the key remains
    res = _save(client, t, s["id"], payload)
    assert res.status_code == 200, res.text

    after = {x["subject_name"]: x["reference_number"] for x in _get(client, t, s["id"])}
    assert after == {n: by_name[n]["reference_number"] for n in (NAME_A, NAME_B)}


def test_a_duplicate_participant_key_is_rejected(client, investigator):
    t = investigator["token"]
    s, subjects, _ = _two_undocumented(client, t)
    payload = _trip(subjects)
    payload[1]["participant_key"] = payload[0]["participant_key"]
    res = _save(client, t, s["id"], payload)
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "duplicate_participant_key"


def test_a_key_from_another_session_is_rejected(client, investigator):
    """Never adopt a handle we did not issue here - it would graft one session onto another."""
    t = investigator["token"]
    _, other_subjects, _ = _two_undocumented(client, t)
    s, subjects, _ = _two_undocumented(client, t)

    payload = _trip(subjects)
    payload[0]["participant_key"] = other_subjects[0]["participant_key"]
    res = _save(client, t, s["id"], payload)
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "unknown_participant_key"

    res = _save(client, t, s["id"], _trip(subjects), removed=[str(uuid.uuid4())])
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "unknown_participant_key"


def test_removing_and_keeping_the_same_participant_is_refused(client, investigator):
    t = investigator["token"]
    s, subjects, by_name = _two_undocumented(client, t)
    res = _save(client, t, s["id"], _trip(subjects), removed=[by_name[NAME_A]["participant_key"]])
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "conflicting_participant_removal"
