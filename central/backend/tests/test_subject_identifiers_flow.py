"""Documents presented on a subject become external identifiers on the person.

That is what lets the same human be found rather than entered twice - and it is deliberately
separate from their canonical reference, which stays CIV-* however many documents they hold
or lose.
"""

from __future__ import annotations

from app.db.session import SessionLocal
from app.services.person_identifiers import find_by_identifier, identifiers_for
import uuid
from app.models import PersonIdentity
from tests.conftest import auth, create_session

UNHCR = "556677"


def _doc(kind: str, number: str, country: str | None = None) -> dict:
    return {"document_type": kind, "document_number": number, "issuing_country": country}


def _civilian(name: str, documents: list[dict]) -> dict:
    return {"subject_name": name, "person_type": "CIVILIAN", "documents": documents}


def _identifiers_of(reference: str):
    with SessionLocal() as db:
        identity = db.get(PersonIdentity, uuid.UUID(reference))
        return {(r.identifier_type, r.issuer_namespace, r.value_normalized) for r in identifiers_for(db, identity.id)}


def test_an_agency_card_on_a_subject_becomes_an_identifier(client, investigator):
    t = investigator["token"]
    s = create_session(client, t, subjects=[_civilian("علي حسن", [_doc("UNHCR_CARD", UNHCR)])])
    reference = s["subjects"][0]["identity_id"]

    assert uuid.UUID(reference)
    assert ("UNHCR", "", UNHCR) in _identifiers_of(reference)

    with SessionLocal() as db:
        found = find_by_identifier(db, identifier_type="UNHCR", value=UNHCR)
        assert found is not None and str(found.id) == reference


def test_a_passport_needs_its_issuer_to_key_anything(client, investigator):
    """Passport 1234567 exists in many countries, so the number alone stays evidence."""
    t = investigator["token"]
    with_issuer = create_session(client, t, subjects=[
        _civilian("سمير خالد", [_doc("PASSPORT", "P1234567", "LB")]),
    ])
    without = create_session(client, t, subjects=[
        _civilian("ريم قاسم", [_doc("PASSPORT", "P7654321", None)]),
    ])

    assert ("PASSPORT", "LB", "P1234567") in _identifiers_of(with_issuer["subjects"][0]["identity_id"])
    assert _identifiers_of(without["subjects"][0]["identity_id"]) == set()


def test_documents_with_no_proven_namespace_key_nothing(client, investigator):
    """An إخراج قيد is a family record; a driving licence is keyed by an issuer we do not have."""
    t = investigator["token"]
    s = create_session(client, t, subjects=[
        _civilian("مريم حسن", [_doc("CIVIL_EXTRACT", "123"), _doc("DRIVING_LICENSE", "D9")]),
    ])
    assert _identifiers_of(s["subjects"][0]["identity_id"]) == set()


def test_re_saving_the_same_documents_does_not_accumulate(client, investigator):
    t = investigator["token"]
    s = create_session(client, t, subjects=[_civilian("علي حسن", [_doc("UNHCR_CARD", UNHCR)])])
    reference = s["subjects"][0]["identity_id"]
    subject = s["subjects"][0]

    payload = {
        "participant_key": subject["participant_key"],
        "subject_name": subject["subject_name"],
        "identity_id": reference,
        "person_type": "CIVILIAN",
        "documents": [{k: d[k] for k in ("id", "document_type", "document_number", "issuing_country")}
                      for d in subject["documents"]],
    }
    res = client.put(f"/api/investigations/{s['id']}", json={"subjects": [payload]}, headers=auth(t))
    assert res.status_code == 200, res.text
    assert len(_identifiers_of(reference)) == 1


def test_a_card_belonging_to_someone_else_refuses_the_save(client, investigator):
    """Never transferred: the operator is told who holds it, and can reuse that person."""
    t = investigator["token"]
    first = create_session(client, t, subjects=[_civilian("علي حسن", [_doc("UNHCR_CARD", UNHCR)])])
    owner_reference = first["subjects"][0]["identity_id"]

    res = client.post(
        "/api/investigations",
        json={
            "title": "جلسة", "location": "بيروت", "session_date": "2026-08-23",
            "start_time": "10:00", "expected_speaker_count": 2,
            "subjects": [_civilian("شخص آخر", [_doc("UNHCR_CARD", UNHCR)])],
        },
        headers=auth(t),
    )
    assert res.status_code == 409, res.text
    body = res.json()
    assert body["detail"] == "person_identifier_already_assigned"
    assert body["held_by_identity_id"] == owner_reference
    assert body["held_by_name"] == "علي حسن"
    # Nothing about WHERE that person appears: the caller may not be entitled to know.
    assert "session" not in res.text.lower()

    # And it did not change hands.
    assert ("UNHCR", "", UNHCR) in _identifiers_of(owner_reference)
