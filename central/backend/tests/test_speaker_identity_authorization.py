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


def test_re_sending_an_unchanged_reference_is_an_ordinary_save(client, admin_token, labeller):
    """The case that would silently break every ordinary save if the check read
    'reference_number present' instead of 'reference_number changed'.

    The labeller owns the session - they may run one, they simply may not say who anyone is -
    and an administrator does the identifying, as the split intends.
    """
    t_lab = labeller["token"]
    s, speaker = _session_with_speaker(client, t_lab)

    reference = _ref()
    res = client.put(
        f"/api/investigations/{s['id']}",
        json={"subjects": [_subject_for(reference, "علي حسن")]},
        headers=auth(admin_token),
    )
    assert res.status_code == 200, res.text
    res = _patch(client, admin_token, s["id"], speaker["id"],
                 display_name="علي حسن", person_name="علي حسن", reference_number=reference)
    assert res.status_code == 200, res.text

    # The labeller edits the notes and round-trips the reference untouched, as a form does.
    res = client.patch(
        f"/api/investigations/{s['id']}/speakers/{speaker['id']}",
        json={"notes": "ملاحظة", "reference_number": reference},
        headers=auth(t_lab),
    )
    assert res.status_code == 200, res.text
    assert res.json()["notes"] == "ملاحظة"
    assert res.json()["identity_id"], "the identity the administrator set must survive"


# --------------------------------------------------------------------------
# what it may not
# --------------------------------------------------------------------------

def test_binding_a_speaker_to_a_person_is_refused(client, labeller):
    t = labeller["token"]
    s, speaker = _session_with_speaker(client, t)
    res = _patch(client, t, s["id"], speaker["id"],
                 display_name="علي حسن", person_name="علي حسن", reference_number=_ref())
    assert res.status_code == 403, res.text
    assert res.json()["detail"] == "identity_change_not_permitted"


def test_a_refusal_leaves_the_speaker_exactly_as_it_was(client, labeller):
    """A refusal that half-applies a row is worse than no check at all."""
    from sqlalchemy import func, select

    from app.models import PersonIdentity

    t = labeller["token"]
    s, speaker = _session_with_speaker(client, t)
    assert _patch(client, t, s["id"], speaker["id"], display_name="المتحدث الأول").status_code == 200
    before = _speakers(client, t, s["id"])["SPEAKER_00"]

    with SessionLocal() as db:
        identities_before = db.scalar(select(func.count()).select_from(PersonIdentity))

    reference = _ref()
    res = _patch(client, t, s["id"], speaker["id"],
                 display_name="اسم آخر", person_name="علي حسن", reference_number=reference)
    assert res.status_code == 403, res.text

    after = _speakers(client, t, s["id"])["SPEAKER_00"]
    assert after["display_name"] == before["display_name"], "the label must not have moved"
    assert after["reference_number"] == before["reference_number"]
    assert after["identity_id"] == before["identity_id"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PersonIdentity)) == identities_before, (
            "no canonical person may be created by a refused request"
        )


def test_the_same_request_succeeds_with_the_identifying_permission(client, investigator):
    """ROLE_INVESTIGATOR holds both, so nothing an investigator does today breaks."""
    t = investigator["token"]
    s, speaker = _session_with_speaker(client, t)
    reference = _ref()
    res = client.put(
        f"/api/investigations/{s['id']}",
        json={"subjects": [_subject_for(reference, "علي حسن")]},
        headers=auth(t),
    )
    assert res.status_code == 200, res.text

    res = _patch(client, t, s["id"], speaker["id"],
                 display_name="علي حسن", person_name="علي حسن", reference_number=reference)
    assert res.status_code == 200, res.text
    assert res.json()["identity_id"], "the identity must be established"
    assert res.json()["reference_number"] == reference
