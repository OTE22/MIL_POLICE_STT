"""display_name is a session label; it must never become a canonical person name.

The reported bug: a subject recorded as "علي عباس" with rank "رائد" is shown in المتحدثون as
"رائد علي عباس". That decorated label reached get_or_create_identity as the canonical name and
was compared byte-for-byte against the registry, so saving the speaker was refused.

The latent bug underneath it is worse: because the speaker PATCH re-validated display_name on
EVERY save, any speaker whose label had drifted from person_name - after a rename, a merge
repoint, or a hand-edited label - could never be edited again, not even to change its notes.

So the rule these tests pin is: assert the name the client explicitly sent, or assert nothing.
"""

from __future__ import annotations

import uuid

from tests.conftest import auth
from tests.test_voice_matching import EMB_A, EMB_B, _speakers, _submit, _voice

CANONICAL = "علي عباس"
DECORATED = "رائد علي عباس"  # what the UI displays: rank + name


def _ref() -> str:
    return f"MIL-ARMY-{uuid.uuid4().hex[:6].upper()}"


def _patch(client, token, session_id, speaker_id, **body):
    return client.patch(
        f"/api/investigations/{session_id}/speakers/{speaker_id}",
        json=body,
        headers=auth(token),
    )


def _registry(client, token, reference):
    """The canonical rows the registry actually holds for a reference."""
    res = client.get(f"/api/voice-enrollments/people?q={reference}", headers=auth(token))
    assert res.status_code == 200, res.text
    return res.json()


def _identified_speaker(client, token):
    """A speaker whose display_name deliberately differs from its canonical person_name."""
    s = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, token, s["id"])
    military_id = uuid.uuid4().hex[:6].upper()
    reference = f"MIL-ARMY-{military_id}"

    # The person is recorded through the existing session workflow, canonical name only.
    # The reference is DERIVED from the identifiers - ordinary entry cannot type one.
    res = client.put(
        f"/api/investigations/{s['id']}",
        json={"subjects": [{
            "subject_name": CANONICAL,
            "rank": "رائد",
            "person_type": "MILITARY",
            "security_branch": "ARMY",
            "military_id": military_id,
        }]},
        headers=auth(token),
    )
    assert res.status_code == 200, res.text
    assert res.json()["subjects"][0]["reference_number"] == reference

    # The speaker carries the DECORATED label, exactly as picking the chip would set it.
    res = _patch(
        client, token, s["id"], sp["SPEAKER_00"]["id"],
        display_name=DECORATED, reference_number=reference, speaker_role="SUBJECT",
    )
    assert res.status_code == 200, res.text
    assert res.json()["identity_id"], "the reference must resolve the canonical identity"
    return s, sp["SPEAKER_00"]["id"], reference


def test_an_unrelated_patch_survives_a_display_name_that_drifted(client, investigator):
    """(A) The latent bug: notes must be editable on a speaker whose label carries a rank."""
    t = investigator["token"]
    s, speaker_id, reference = _identified_speaker(client, t)

    res = _patch(client, t, s["id"], speaker_id, notes="ملاحظة")
    assert res.status_code == 200, res.text
    assert res.json()["notes"] == "ملاحظة"

    # The label kept its rank and the registry kept the bare name. Both are correct.
    assert res.json()["display_name"] == DECORATED
    people = _registry(client, t, reference)
    assert [p["person_name"] for p in people] == [CANONICAL]


def test_an_explicit_contradicting_name_is_still_refused(client, investigator):
    """(B) The conflict guard is untouched: an EXPLICIT name that disagrees still fails."""
    t = investigator["token"]
    s, speaker_id, reference = _identified_speaker(client, t)

    res = _patch(client, t, s["id"], speaker_id, person_name="شخص آخر")
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == "person_reference_name_mismatch"

    # Refused means nothing moved.
    people = _registry(client, t, reference)
    assert [p["person_name"] for p in people] == [CANONICAL]


def test_a_new_reference_is_never_named_after_the_display_label(client, investigator):
    """(C) The reported bug at its root: a label must not be able to create a person."""
    t = investigator["token"]
    s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, s["id"])
    reference = _ref()

    res = _patch(
        client, t, s["id"], sp["SPEAKER_00"]["id"],
        display_name=DECORATED, reference_number=reference, speaker_role="SUBJECT",
    )
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "person_name_required_for_new_reference"

    # Nothing was created - least of all a person called "رائد علي عباس".
    assert _registry(client, t, reference) == []


def test_a_new_reference_may_be_created_from_an_explicit_canonical_name(client, investigator):
    """(D) The same request succeeds once the client says who this actually is."""
    t = investigator["token"]
    s = _submit(client, t, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    sp = _speakers(client, t, s["id"])
    reference = _ref()

    res = _patch(
        client, t, s["id"], sp["SPEAKER_00"]["id"],
        display_name=DECORATED, person_name=CANONICAL,
        reference_number=reference, speaker_role="SUBJECT",
    )
    assert res.status_code == 200, res.text
    assert res.json()["identity_id"]
    assert res.json()["display_name"] == DECORATED  # the rank stays on the label

    people = _registry(client, t, reference)
    assert [p["person_name"] for p in people] == [CANONICAL]
    assert DECORATED not in [p["person_name"] for p in people]
