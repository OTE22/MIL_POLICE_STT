"""External identifiers find a person; they never become one, and never merge two.

The canonical reference (CIV-*, MIL-*) is what we call someone and is permanent. A passport or
an UNHCR card is what the world calls them: reissued, corrected, replaced. Keeping the two
apart is what lets a person survive their paperwork changing.

Only namespaces proven person-unique may resolve automatically. رقم السجل is deliberately not
one of them - it identifies a family record, and keying on it merged relatives.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.session import SessionLocal
from app.services.person_identifiers import (
    IdentifierAlreadyAssigned,
    attach_identifier,
    find_by_identifier,
    identifiers_for,
    resolves_automatically,
)
from app.services.person_identity import allocate_civilian_reference, get_or_create_identity


def _civilian(db, name: str):
    return get_or_create_identity(db, allocate_civilian_reference(db), name)


# --------------------------------------------------------------------------
# which namespaces are allowed to resolve at all
# --------------------------------------------------------------------------

def test_agency_cards_resolve_because_the_agency_is_the_namespace():
    assert resolves_automatically("UNHCR", None)
    assert resolves_automatically("UNRWA", None)


def test_a_passport_without_its_issuer_resolves_nobody():
    """Passport 1234567 exists in many countries, so the number alone is not an identity."""
    assert not resolves_automatically("PASSPORT", None)
    assert not resolves_automatically("PASSPORT", "   ")
    assert resolves_automatically("PASSPORT", "LB")


@pytest.mark.parametrize("kind", ["LEBANESE_ID", "CIVIL_EXTRACT", "DRIVING_LICENSE", "OTHER"])
def test_unproven_namespaces_never_resolve(kind):
    assert not resolves_automatically(kind, "LB")


# --------------------------------------------------------------------------
# reuse: the whole point of recording them
# --------------------------------------------------------------------------

def test_an_identifier_finds_the_person_it_belongs_to():
    with SessionLocal() as db:
        person = _civilian(db, "علي حسن")
        attach_identifier(db, identity=person, identifier_type="UNHCR", value="556677")
        db.commit()

        found = find_by_identifier(db, identifier_type="UNHCR", value="556677")
        assert found is not None and found.id == person.id
        assert found.reference_display.startswith("CIV-")


def test_the_same_number_under_two_agencies_is_two_people():
    with SessionLocal() as db:
        a, b = _civilian(db, "علي حسن"), _civilian(db, "سمير خالد")
        attach_identifier(db, identity=a, identifier_type="UNHCR", value="556677")
        attach_identifier(db, identity=b, identifier_type="UNRWA", value="556677")
        db.commit()
        assert find_by_identifier(db, identifier_type="UNHCR", value="556677").id == a.id
        assert find_by_identifier(db, identifier_type="UNRWA", value="556677").id == b.id


def test_the_same_passport_number_from_two_countries_is_two_people():
    with SessionLocal() as db:
        a, b = _civilian(db, "علي حسن"), _civilian(db, "سمير خالد")
        attach_identifier(db, identity=a, identifier_type="PASSPORT", value="1234567", issuer="LB")
        attach_identifier(db, identity=b, identifier_type="PASSPORT", value="1234567", issuer="SY")
        db.commit()
        assert find_by_identifier(db, identifier_type="PASSPORT", value="1234567", issuer="LB").id == a.id
        assert find_by_identifier(db, identifier_type="PASSPORT", value="1234567", issuer="SY").id == b.id


def test_values_fold_the_way_canonical_references_do():
    """Arabic-Indic digits and padding are the same identifier typed differently."""
    with SessionLocal() as db:
        person = _civilian(db, "علي حسن")
        attach_identifier(db, identity=person, identifier_type="UNHCR", value=" 556677 ")
        db.commit()
        assert find_by_identifier(db, identifier_type="UNHCR", value="٥٥٦٦٧٧").id == person.id


def test_re_attaching_the_same_value_to_the_same_person_is_a_no_op():
    """Repeated saves must not accumulate rows or start failing."""
    with SessionLocal() as db:
        person = _civilian(db, "علي حسن")
        first = attach_identifier(db, identity=person, identifier_type="UNHCR", value="556677")
        again = attach_identifier(db, identity=person, identifier_type="UNHCR", value="556677")
        db.commit()
        assert first.id == again.id
        assert len(identifiers_for(db, person.id)) == 1


# --------------------------------------------------------------------------
# collision: never silently transferred
# --------------------------------------------------------------------------

def test_an_identifier_belonging_to_someone_else_is_refused():
    with SessionLocal() as db:
        owner = _civilian(db, "علي حسن")
        attach_identifier(db, identity=owner, identifier_type="UNHCR", value="556677")
        db.commit()

        other = _civilian(db, "سمير خالد")
        with pytest.raises(IdentifierAlreadyAssigned) as raised:
            attach_identifier(db, identity=other, identifier_type="UNHCR", value="556677")
        db.rollback()

        # The caller learns WHO holds it, so they can reuse that person instead.
        assert raised.value.held_by.id == owner.id
        assert raised.value.identifier_type == "UNHCR"

    with SessionLocal() as db:
        # And it did not change hands.
        assert find_by_identifier(db, identifier_type="UNHCR", value="556677").id == owner.id


def test_an_unprovable_namespace_is_recorded_nowhere_rather_than_guessed():
    """Refusing to key it is the point: a wrong key merges two humans."""
    with SessionLocal() as db:
        person = _civilian(db, "علي حسن")
        assert attach_identifier(db, identity=person, identifier_type="LEBANESE_ID", value="123") is None
        assert attach_identifier(db, identity=person, identifier_type="PASSPORT", value="123") is None
        assert attach_identifier(db, identity=person, identifier_type="UNHCR", value="  ") is None
        db.commit()
        assert identifiers_for(db, person.id) == []


def test_a_merged_person_still_answers_through_their_survivor():
    """After consolidation the identifier must resolve the person who survived."""
    from app.services.person_identity import merge_identities

    with SessionLocal() as db:
        duplicate = _civilian(db, "علي حسن")
        survivor = _civilian(db, "علي حسن")
        attach_identifier(db, identity=duplicate, identifier_type="UNHCR", value="556677")
        db.commit()
        merge_identities(db, duplicate.id, survivor.id)
        db.commit()

        found = find_by_identifier(db, identifier_type="UNHCR", value="556677")
        assert found is not None and found.id == survivor.id
