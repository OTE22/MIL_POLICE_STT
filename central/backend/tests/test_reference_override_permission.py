"""الرقم المرجعي is system-managed; assigning one by hand is a privileged act.

Normal data entry fills in the structured identifiers and the backend derives the key. That
is what stops one soldier arriving as MIL-4471, MIL 4471 and 4471. Manual assignment still
exists - real paperwork does not always fit the rules - but it now needs
`subjects.reference.override`, and the server enforces it: hiding the button would only be
decoration.

The check has to be narrow, because the form round-trips reference_number on EVERY save. A
value that matches what the identifiers derive, or what the participant already carries, is
an ordinary save. Only a value matching neither is an override.
"""

from __future__ import annotations

import uuid

from tests.conftest import auth, create_session
from tests.test_subject_identity_lifecycle import _get, _round_trip, _save


def _military(**over) -> dict:
    """A subject whose identifiers DO derive: MIL-ARMY-<id>."""
    body = {
        "subject_name": "علي عباس",
        "rank": "رائد",
        "person_type": "MILITARY",
        "security_branch": "ARMY",
        "military_id": uuid.uuid4().hex[:6].upper(),
    }
    body.update(over)
    return body


def _underivable(**over) -> dict:
    """Nothing to derive AND nothing to issue: a soldier whose service number is unknown.

    Civilians can no longer land here - they are always issued a CIV reference - so the only
    remaining un-referenced person is one we cannot classify as a civilian either.
    """
    body = {"subject_name": "سعاد نصر", "person_type": "MILITARY", "security_branch": "ARMY"}
    body.update(over)
    return body


def _session_with(client, token, subject) -> dict:
    """Create the session WITH this person, rather than replacing the default participant.

    Replacing them would drop a participant holding an issued reference without saying so,
    which reconciliation now refuses - correctly: silently discarding a canonical person is
    exactly what it exists to prevent.
    """
    return create_session(client, token, subjects=[subject])


# --------------------------------------------------------------------------
# Ordinary saves - no permission needed
# --------------------------------------------------------------------------

def test_re_saving_a_derived_reference_is_an_ordinary_save(client, investigator):
    t = investigator["token"]
    saved = _session_with(client, t, _military())
    derived = saved["subjects"][0]["reference_number"]
    assert derived.startswith("MIL-ARMY-"), derived

    # The form sends the reference straight back. That is not an override.
    res = _save(client, t, saved["id"], {"subjects": _round_trip(saved["subjects"])})
    assert res.status_code == 200, res.text
    assert res.json()["subjects"][0]["reference_number"] == derived


def test_re_saving_a_carried_temporary_reference_is_an_ordinary_save(client, investigator):
    """A TMP derives from nothing, so it can only be recognised as 'already carried'."""
    t = investigator["token"]
    saved = _session_with(client, t, _underivable(is_undocumented=True, person_type="UNKNOWN"))
    tmp = saved["subjects"][0]["reference_number"]
    assert tmp.startswith("TMP-"), tmp

    res = _save(client, t, saved["id"], {"subjects": _round_trip(saved["subjects"])})
    assert res.status_code == 200, res.text
    # Carried forward, not re-allocated.
    assert res.json()["subjects"][0]["reference_number"] == tmp


# --------------------------------------------------------------------------
# Hand-assignment - refused without the permission
# --------------------------------------------------------------------------

def test_overriding_a_derived_reference_needs_the_permission(client, investigator):
    t = investigator["token"]
    saved = _session_with(client, t, _military())
    subjects = _round_trip(saved["subjects"])
    subjects[0]["reference_number"] = "SPECIAL-4471"

    res = _save(client, t, saved["id"], {"subjects": subjects})
    assert res.status_code == 403, res.text
    assert res.json()["detail"] == "reference_override_not_permitted"

    # Refused means untouched.
    assert _get(client, t, saved["id"])["subjects"][0]["reference_number"] == \
        saved["subjects"][0]["reference_number"]


def test_assigning_a_reference_that_cannot_be_derived_needs_the_permission(client, investigator):
    """The case the read-only field leaves empty: derivation yields nothing."""
    t = investigator["token"]
    saved = _session_with(client, t, _underivable())
    assert saved["subjects"][0]["reference_number"] is None

    subjects = _round_trip(saved["subjects"])
    subjects[0]["reference_number"] = "MANUAL-0001"
    res = _save(client, t, saved["id"], {"subjects": subjects})
    assert res.status_code == 403, res.text
    assert res.json()["detail"] == "reference_override_not_permitted"
    assert _get(client, t, saved["id"])["subjects"][0]["reference_number"] is None


# --------------------------------------------------------------------------
# The same two requests, from someone who holds the permission
# --------------------------------------------------------------------------

def test_an_authorized_user_may_override_and_may_assign(client, admin_token):
    """The same two requests that were refused above, from someone who holds the permission.

    The override is applied at FIRST entry, which is the flow _reserve_derived_alias
    supports: it reserves the implied key as an alias only while that key is still
    unclaimed. Overriding a reference that was already saved once is a separate, existing
    limitation and is deliberately not exercised here.
    """
    t = admin_token

    # (a) override a derived key - the implied one is still reserved as an alias.
    military_id = uuid.uuid4().hex[:6].upper()
    implied = f"MIL-ARMY-{military_id}"
    chosen = f"SPECIAL-{uuid.uuid4().hex[:6].upper()}"
    saved = _session_with(client, t, _military(military_id=military_id, reference_number=chosen))
    assert saved["subjects"][0]["reference_number"] == chosen

    from app.db.session import SessionLocal
    from app.services.person_identity import find_identity

    with SessionLocal() as db:
        # The derived reference resolves to the SAME person, so a later investigator
        # entering the same soldier converges instead of creating a second identity.
        assert find_identity(db, implied).id == find_identity(db, chosen).id

    # (b) assign one where derivation is impossible.
    manual = f"MANUAL-{uuid.uuid4().hex[:6].upper()}"
    saved2 = _session_with(client, t, _underivable(reference_number=manual))
    assert saved2["subjects"][0]["reference_number"] == manual

# --------------------------------------------------------------------------
# namespaces we allocate are never hand-assignable
# --------------------------------------------------------------------------

def test_a_civilian_reference_cannot_be_invented_even_with_the_permission(client, admin_token):
    """CIV-* comes from a sequence. Typing one squats a number it has not reached yet.

    The day the sequence arrives there, that civilian is either refused or silently attached
    to whoever squatted it - so this is refused for everyone, permission or not.
    """
    t = admin_token
    saved = _session_with(client, t, _military())
    subjects = _round_trip(saved["subjects"])
    subjects[0]["reference_number"] = "CIV-00009999"

    res = _save(client, t, saved["id"], {"subjects": subjects})
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "issued_reference_not_assignable"


def test_a_temporary_reference_cannot_be_invented_either(client, admin_token):
    t = admin_token
    saved = _session_with(client, t, _military())
    subjects = _round_trip(saved["subjects"])
    subjects[0]["reference_number"] = "TMP-2026-000999"

    res = _save(client, t, saved["id"], {"subjects": subjects})
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "issued_reference_not_assignable"


def test_an_existing_civilian_reference_may_still_be_carried(client, investigator):
    """Reusing one that exists is selecting a person, not inventing a key - and needs nothing."""
    t = investigator["token"]
    first = create_session(client, t, subjects=[
        {"subject_name": "علي حسن", "person_type": "CIVILIAN"},
    ])
    reference = first["subjects"][0]["reference_number"]
    assert reference.startswith("CIV-")

    second = create_session(client, t, subjects=[
        {"subject_name": "علي حسن", "person_type": "CIVILIAN",
         "reference_number": reference},
    ])
    assert second["subjects"][0]["reference_number"] == reference
