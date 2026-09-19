"""A person is recorded by NAME, and the reference is never a substitute for one.

`subject_name` was optional and `get_or_create_identity` filled the gap with the reference
itself, producing a registry row called "CIV-00000019" - a placeholder that reads as real data
and is indistinguishable from someone actually named that.

These tests hold every layer of that shut: the API contract, the identity service, and the
database constraints underneath both.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.session import SessionLocal
from app.models import PersonIdentity
from app.services.person_identity import PersonNameRequired, create_identity, resolve_identity

from conftest import auth


def _subject(**over):
    body = {"subject_name": "علي عباس", "person_type": "MILITARY",
            "military_id": "NAME-T-1", "security_branch": "ARMY"}
    body.update(over)
    return body


def _post(client, token, subject):
    return client.post("/api/investigations", json={
        "title": "جلسة اختبار الاسم", "location": "بيروت", "session_date": "2026-08-27",
        "start_time": "10:00", "expected_speaker_count": 1, "subjects": [subject],
    }, headers=auth(token))


# --------------------------------------------------------------- the API contract
@pytest.mark.parametrize(
    "name, why",
    [
        (None, "missing"),
        ("", "empty"),
        ("   ", "whitespace only"),
        ("\t\n ", "other whitespace"),
    ],
)
def test_a_subject_without_a_real_name_is_refused(client, investigator, name, why):
    subject = _subject()
    if name is None:
        subject.pop("subject_name")
    else:
        subject["subject_name"] = name
    res = _post(client, investigator["token"], subject)
    assert res.status_code == 422, f"{why} should be refused, got {res.status_code}: {res.text}"


def test_a_name_is_stored_trimmed(client, investigator):
    res = _post(client, investigator["token"], _subject(subject_name="  علي عباس  "))
    assert res.status_code == 201, res.text
    assert res.json()["subjects"][0]["subject_name"] == "علي عباس"


def test_a_latin_name_is_accepted(client, investigator):
    """A passport may carry the only spelling there is. Transliterating would invent evidence."""
    for latin in ("ALI", "JOHN SMITH", "GEORGES HADDAD"):
        res = _post(client, investigator["token"],
                    _subject(subject_name=latin, military_id=f"LAT-{latin[:3]}"))
        assert res.status_code == 201, res.text
        assert res.json()["subjects"][0]["subject_name"] == latin


# ------------------------------------------------------------ the identity service
def test_creating_an_identity_without_a_name_is_refused():
    with SessionLocal() as db:
        with pytest.raises(PersonNameRequired):
            create_identity(db, None)
        with pytest.raises(PersonNameRequired):
            create_identity(db, "   ")
        db.rollback()


def test_a_reference_can_never_become_a_person_name(client, investigator):
    """The exact defect: a person filed under their own reference number."""
    res = _post(client, investigator["token"], _subject(subject_name="سعاد نصر",
                                                        military_id="REF-NOT-NAME"))
    assert res.status_code == 201, res.text
    reference = res.json()["subjects"][0]["identity_id"]
    assert reference

    with SessionLocal() as db:
        names = [n for (n,) in db.execute(text("SELECT person_name FROM person_identities"))]
    assert reference not in names, "a reference number was stored as somebody's name"
    for n in names:
        assert n.strip(), "a blank name reached the registry"


def test_looking_up_an_existing_identity_without_a_name_still_works():
    """Only CREATION needs a name. A lookup already knows who it is, and callers rely on it."""
    with SessionLocal() as db:
        created = create_identity(db, "زياد مراد")
        db.flush()
        again = resolve_identity(db, db.get(PersonIdentity, created.id))
        assert again is not None and again.id == created.id
        db.rollback()


# ------------------------------------------------- the database, under both of them
def test_the_database_refuses_a_blank_subject_name():
    """The last line: no script, migration or future endpoint can write one either."""
    with SessionLocal() as db:
        for bad in ("NULL", "''", "'   '"):
            with pytest.raises((IntegrityError, DBAPIError)):
                db.execute(text(
                    "INSERT INTO subjects (id, session_id, subject_name, person_type) "
                    f"VALUES (gen_random_uuid(), gen_random_uuid(), {bad}, 'CIVILIAN')"))
                db.flush()
            db.rollback()


def test_the_database_refuses_a_blank_person_name():
    with SessionLocal() as db:
        for bad in ("NULL", "''", "'  '"):
            with pytest.raises((IntegrityError, DBAPIError)):
                db.execute(text(
                    "INSERT INTO person_identities "
                    "(id, person_name) "
                    f"VALUES (gen_random_uuid(), {bad})"))
                db.flush()
            db.rollback()


def test_the_registry_never_holds_a_blank_name():
    with SessionLocal() as db:
        blank = db.query(PersonIdentity).filter(
            text("person_name IS NULL OR length(btrim(person_name)) = 0")).count()
    assert blank == 0
