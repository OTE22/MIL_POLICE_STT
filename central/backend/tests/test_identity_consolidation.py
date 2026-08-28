"""Consolidating two canonical identities that own no voice prints.

Two people can need merging while neither has ever been voice-enrolled - both may be
referenced only by subjects and speakers. `PATCH /voice-enrollments/{id}` cannot reach them,
because it is addressed through an enrolment that does not exist.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import PersonIdentity, SessionSpeaker, Subject, VoiceEnrollment
from app.services.person_identity import find_identity
from tests.conftest import auth, create_session


def _identity(reference: str) -> PersonIdentity | None:
    with SessionLocal() as db:
        row = find_identity(db, reference)
        if row is not None:
            db.expunge(row)
        return row


def _make_person(client, token, name: str, military_id: str) -> tuple[str, str]:
    """A session with one identified person and one named speaker. No prints anywhere."""
    session = create_session(client, token, subjects=[
        {"subject_name": name, "person_type": "MILITARY",
         "security_branch": "ARMY", "military_id": military_id},
    ])
    reference = f"MIL-ARMY-{military_id}"

    with SessionLocal() as db:
        identity = find_identity(db, reference)
        assert identity is not None, f"{reference} should exist"
        # A speaker pointing at the same person, as a transcript would produce.
        db.add(
            SessionSpeaker(
                session_id=uuid.UUID(session["id"]),
                speaker_label="SPEAKER_00",
                display_name=name,
                reference_number=reference,
                identity_id=identity.id,
            )
        )
        db.commit()
        return session["id"], str(identity.id)


def test_two_identities_with_no_prints_can_be_consolidated(client, admin_token, investigator):
    t = investigator["token"]
    session_a, identity_a = _make_person(client, t, "علي حسن", "7001")
    session_b, identity_b = _make_person(client, t, "الرائد علي حسن", "7002")

    with SessionLocal() as db:
        assert db.scalars(select(VoiceEnrollment)).all() == [], "this test is about the no-print case"

    res = client.post(
        f"/api/voice-enrollments/people/{identity_a}/consolidate",
        json={"into_identity_id": identity_b},
        headers=auth(admin_token),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["identity_id"] == identity_b
    assert body["affected_enrollments"] == 0, "no print was required"
    assert body["subjects"] >= 1 and body["speakers"] >= 1

    with SessionLocal() as db:
        # Everything that pointed at A now points at B, carrying B's reference.
        survivor = db.get(PersonIdentity, uuid.UUID(identity_b))
        for subject in db.scalars(select(Subject).where(Subject.session_id == uuid.UUID(session_a))).all():
            assert str(subject.identity_id) == identity_b
            assert subject.reference_number == survivor.reference_display
        for speaker in db.scalars(
            select(SessionSpeaker).where(SessionSpeaker.session_id == uuid.UUID(session_a))
        ).all():
            assert str(speaker.identity_id) == identity_b
            assert speaker.reference_number == survivor.reference_display

        # A survives as an alias, never deleted - that is what blocks resurrection.
        merged = db.get(PersonIdentity, uuid.UUID(identity_a))
        assert merged is not None
        assert str(merged.merged_into_id) == identity_b

    # A stale payload still carrying A's reference resolves forward instead of recreating it.
    stale = _identity("MIL-ARMY-7001")
    assert stale is not None and str(stale.id) == identity_b


def test_consolidation_requires_global_session_access(client, investigator):
    """An investigator may enrol a voice; that must not let them merge identities
    touching sessions they cannot open."""
    t = investigator["token"]
    _, identity_a = _make_person(client, t, "علي حسن", "7101")
    _, identity_b = _make_person(client, t, "الرائد علي حسن", "7102")

    res = client.post(
        f"/api/voice-enrollments/people/{identity_a}/consolidate",
        json={"into_identity_id": identity_b},
        headers=auth(t),
    )
    assert res.status_code == 403, res.text
    assert res.json()["detail"] == "forbidden"

    with SessionLocal() as db:
        assert db.get(PersonIdentity, uuid.UUID(identity_a)).merged_into_id is None, "no mutation"


def test_consolidating_an_identity_into_itself_is_refused(client, admin_token, investigator):
    _, identity = _make_person(client, investigator["token"], "علي حسن", "7201")
    res = client.post(
        f"/api/voice-enrollments/people/{identity}/consolidate",
        json={"into_identity_id": identity},
        headers=auth(admin_token),
    )
    assert res.status_code == 409
    assert res.json()["detail"] == "identity_merge_conflict"


def test_consolidation_is_audited_with_the_affected_counts(client, admin_token, investigator):
    t = investigator["token"]
    _, identity_a = _make_person(client, t, "علي حسن", "7301")
    _, identity_b = _make_person(client, t, "الرائد علي حسن", "7302")
    client.post(
        f"/api/voice-enrollments/people/{identity_a}/consolidate",
        json={"into_identity_id": identity_b},
        headers=auth(admin_token),
    )

    rows = client.get("/api/audit-logs?action=VOICE_ENROLLMENT_UPDATED", headers=auth(admin_token)).json()
    entry = next(
        (r for r in rows["items"] if (r.get("safe_metadata") or {}).get("scope") == "identity_consolidation"),
        None,
    )
    assert entry is not None, "consolidation must be auditable"
    meta = entry["safe_metadata"]
    assert meta["source_identity_id"] == identity_a
    assert meta["target_identity_id"] == identity_b
    assert meta["affected_enrollments"] == 0
    assert meta["affected_subjects"] >= 1
    assert meta["affected_speakers"] >= 1
    assert meta["identity_before"]["person_reference"] == "MIL-ARMY-7301"
