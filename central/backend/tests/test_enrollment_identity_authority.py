"""Enrolment resolves a canonical person; it never creates or renames one.

The second live instance of the rank bug lived here. voice.py read
`body.person_name or speaker.display_name`, and the enrolment page sent the speaker's
DISPLAY label as the canonical name - so enrolling "الرائد علي حسن" for a person recorded
as "علي حسن" collided with the registry and was refused.

The rule now: identity comes from speaker.identity_id and nothing else. The registry owns
both snapshot values, so a stale client cannot rename anyone by enrolling them.
"""

from __future__ import annotations

import uuid

from tests.conftest import auth
from tests.test_voice_matching import (
    EMB_A,
    EMB_B,
    MODEL,
    _link_identity,
    _speakers,
    _submit,
    _voice,
)

CANONICAL = "علي حسن"
DECORATED = "الرائد علي حسن"  # the label the UI shows: rank + name


def _ref() -> str:
    return f"MIL-ARMY-{uuid.uuid4().hex[:6].upper()}"


def _raw_enroll(client, token, session_id, speaker_id, **over):
    """Call the endpoint directly, without the helper's identification step."""
    body = {
        "person_reference": over.pop("person_reference", ""),
        "person_name": over.pop("person_name", ""),
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


def _identified(client, token):
    """A speaker linked to a canonical person, then relabelled with a rank."""
    s = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, token, s["id"])
    reference = _ref()
    res = _link_identity(client, token, s["id"], sp["SPEAKER_00"]["id"], reference, CANONICAL)
    assert res.status_code == 200, res.text

    # The label drifts to carry the rank - no canonical assertion, so this is allowed.
    res = client.patch(
        f"/api/investigations/{s['id']}/speakers/{sp['SPEAKER_00']['id']}",
        json={"display_name": DECORATED},
        headers=auth(token),
    )
    assert res.status_code == 200, res.text
    assert res.json()["identity_name"] == CANONICAL
    return s, sp["SPEAKER_00"]["id"], reference


def test_a_stale_client_cannot_rename_a_person_by_enrolling_them(client, investigator):
    """The reported leak: the decorated label must not reach the registry."""
    t = investigator["token"]
    s, speaker_id, reference = _identified(client, t)

    res = _raw_enroll(
        client, t, s["id"], speaker_id,
        person_name=DECORATED,            # stale: what the page used to send
        person_reference=reference,
    )
    assert res.status_code == 201, res.text

    # The print is filed under the canonical person, not the label.
    assert res.json()["person_name"] == CANONICAL
    assert res.json()["person_reference"] == reference

    people = client.get(f"/api/voice-enrollments/people?q={reference}", headers=auth(t)).json()
    assert [p["person_name"] for p in people] == [CANONICAL]


def test_enrolment_refuses_a_speaker_that_has_no_identity(client, investigator):
    """Enrolment is not an identity-creation path, even with a usable reference."""
    t = investigator["token"]
    s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, s["id"])
    reference = _ref()

    res = _raw_enroll(
        client, t, s["id"], sp["SPEAKER_00"]["id"],
        person_name=CANONICAL, person_reference=reference,
    )
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "speaker_identity_required"

    # Nothing was created: the reference is still unclaimed.
    people = client.get(f"/api/voice-enrollments/people?q={reference}", headers=auth(t)).json()
    assert people == []


def test_a_merged_away_identity_is_followed_to_the_survivor(client, investigator):
    """A speaker linked to an alias enrols under the person who actually survives."""
    t = investigator["token"]
    s, speaker_id, alias_reference = _identified(client, t)

    # A second canonical person, then merge the speaker's identity into it.
    s2 = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp2 = _speakers(client, t, s2["id"])
    survivor_reference = _ref()
    res = _link_identity(client, t, s2["id"], sp2["SPEAKER_00"]["id"], survivor_reference, "حسن علي")
    assert res.status_code == 200, res.text

    from app.db.session import SessionLocal
    from app.services.person_identity import find_identity, merge_identities

    with SessionLocal() as db:
        alias = find_identity(db, alias_reference)
        survivor = find_identity(db, survivor_reference)
        merge_identities(db, alias.id, survivor.id)
        db.commit()
        survivor_name = survivor.person_name
        survivor_display = survivor.reference_display

    res = _raw_enroll(
        client, t, s["id"], speaker_id,
        person_name=DECORATED, person_reference=alias_reference,
    )
    assert res.status_code == 201, res.text
    # Filed under the survivor, not the alias and not the label.
    assert res.json()["person_name"] == survivor_name
    assert res.json()["person_reference"] == survivor_display

    # The speaker itself converged too, so it stops re-submitting a dead reference.
    speakers = _speakers(client, t, s["id"])
    assert speakers["SPEAKER_00"]["reference_number"] == survivor_display
