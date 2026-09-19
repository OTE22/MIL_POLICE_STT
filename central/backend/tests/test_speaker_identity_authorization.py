"""Labelling a speaker and binding them to a person are different authorities.

`speakers.assign` says "you may name the voices in this session". `voice.identify` says "you may
declare which human this is" - a claim that reaches the canonical registry and, through it, the
biometric prints. They were the same permission until now, so anyone who could type a label could
also bind a speaker to a person.

The split is enforced on the server, not in React: hiding the option in the picker leaves the
endpoint open to anyone who can call it.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.session import SessionLocal
from tests.conftest import auth, create_user, login
from tests.test_voice_matching import EMB_A, EMB_B, _speakers, _submit, _subject_for, _voice

# Everything ROLE_INVESTIGATOR holds EXCEPT the two voice permissions. Someone who runs the
# session and names its speakers, but may not say who anyone is.
LABELLER_PERMISSIONS = [
    "investigators.read",
    "investigations.create",
    "investigations.read_assigned",
    "investigations.update",
    "recordings.create",
    "processing.request",
    "transcripts.read",
    "transcripts.edit",
    "speakers.assign",
]


@pytest.fixture
def labeller(client, admin_token):
    """A user with speakers.assign and NOT voice.identify. No seeded role is like this."""
    from sqlalchemy import select

    from app.models import Permission, Role, User

    with SessionLocal() as db:
        # `roles` survives the between-test truncate (bootstrap re-seeds it), so this fixture
        # has to be idempotent - it runs once per test, against a table that remembers.
        role = db.scalar(select(Role).where(Role.name == "LABELLER"))
        if role is None:
            role = Role(name="LABELLER", description="names speakers, cannot identify people")
            for code in LABELLER_PERMISSIONS:
                perm = db.scalar(select(Permission).where(Permission.code == code))
                assert perm is not None, f"{code} is not seeded"
                role.permissions.append(perm)
            db.add(role)
            db.commit()

    # POST /users only accepts the three seeded role names, so the account is created normally
    # and then re-roled in the database. Going through the API first is deliberate: the password
    # is hashed by the same code a real login verifies against.
    create_user(client, admin_token, "labeller1", ["INVESTIGATOR"], full_name="مسمّي المتحدثين")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "labeller1"))
        role = db.scalar(select(Role).where(Role.name == "LABELLER"))
        user.roles.clear()
        user.roles.append(role)
        db.commit()
        assert "voice.identify" not in user.permission_codes
        assert "speakers.assign" in user.permission_codes

    return {"token": login(client, "labeller1", "Password!1234")}


def _patch(client, token, session_id, speaker_id, **body):
    return client.patch(
        f"/api/investigations/{session_id}/speakers/{speaker_id}", json=body, headers=auth(token)
    )


def _session_with_speaker(client, token):
    s = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    return s, _speakers(client, token, s["id"])["SPEAKER_00"]


def _ref() -> str:
    return f"MIL-ARMY-{uuid.uuid4().hex[:6].upper()}"


# --------------------------------------------------------------------------
# what speakers.assign alone may still do
# --------------------------------------------------------------------------

def test_notes_need_only_the_labelling_permission(client, labeller):
    t = labeller["token"]
    s, speaker = _session_with_speaker(client, t)
    res = _patch(client, t, s["id"], speaker["id"], notes="ملاحظة")
    assert res.status_code == 200, res.text
    assert res.json()["notes"] == "ملاحظة"


def test_a_temporary_label_needs_only_the_labelling_permission(client, labeller):
    """A label is a session-local note about a voice, not a claim about a person."""
    t = labeller["token"]
    s, speaker = _session_with_speaker(client, t)
    res = _patch(client, t, s["id"], speaker["id"], display_name="المتحدث الأول", speaker_role="WITNESS")
    assert res.status_code == 200, res.text
    assert res.json()["display_name"] == "المتحدث الأول"
    assert res.json()["identity_id"] is None, "a label must never establish an identity"


def test_uuid_selection_requires_voice_identify(client, labeller):
    t = labeller["token"]
    s, speaker = _session_with_speaker(client, t)
    subject = s["subjects"][0]
    res = _patch(client, t, s["id"], speaker["id"], identity_id=subject["identity_id"])
    assert res.status_code == 403
    assert res.json()["detail"] == "identity_change_not_permitted"

def test_role_and_notes_preserve_an_existing_identity(client, labeller):
    from app.models import SessionSpeaker
    t = labeller["token"]
    s, speaker = _session_with_speaker(client, t)
    identity_id = s["subjects"][0]["identity_id"]
    with SessionLocal() as db:
        db.get(SessionSpeaker, uuid.UUID(speaker["id"])).identity_id = uuid.UUID(identity_id)
        db.commit()
    res = _patch(client, t, s["id"], speaker["id"], notes="ملاحظة", speaker_role="WITNESS")
    assert res.status_code == 200
    assert res.json()["identity_id"] == identity_id

def test_retired_reference_cannot_bypass_permission(client, labeller):
    t = labeller["token"]
    s, speaker = _session_with_speaker(client, t)
    res = _patch(client, t, s["id"], speaker["id"], reference_number="MIL-ARMY-4471")
    assert res.status_code == 422
