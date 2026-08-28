"""The canonical person registry: normalization, get-or-create, aliases, and races.

These tests pin the invariant the whole redesign rests on:

    one normalized reference -> one identity -> zero or many voice prints

They deliberately include real concurrency against PostgreSQL. A sequential "call it twice"
test would pass even against an implementation with no database guarantee at all.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import PersonIdentity
from app.services.person_identity import (
    ReferenceNameMismatch,
    find_identity,
    get_or_create_identity,
    normalize_reference,
    resolve_identity,
)


# --------------------------------------------------------------------------
# normalization
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("MIL-4471", "MIL-4471"),
        ("mil-4471", "MIL-4471"),          # case folds
        ("  MIL-4471  ", "MIL-4471"),      # trimmed
        ("MIL-٤٤٧١", "MIL-4471"),          # Arabic-Indic digits fold
        ("MIL-۴۴۷۱", "MIL-4471"),          # Extended Arabic-Indic digits fold
        ("MIL   4471", "MIL 4471"),        # internal whitespace collapses
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_normalization_folds_only_what_is_safe(raw, expected):
    assert normalize_reference(raw) == expected


def test_separators_are_not_interchangeable():
    """Deliberately conservative: nothing proves a space and a hyphen mean the same thing,
    and wrongly merging two people is far worse than failing to merge one."""
    assert normalize_reference("MIL 4471") != normalize_reference("MIL-4471")
    assert normalize_reference("MIL4471") != normalize_reference("MIL-4471")


# --------------------------------------------------------------------------
# get-or-create
# --------------------------------------------------------------------------

def test_same_reference_returns_one_identity():
    with SessionLocal() as db:
        a = get_or_create_identity(db, "MIL-4471", "الرائد علي حسن")
        db.commit()
        b = get_or_create_identity(db, "mil-٤٤٧١", "الرائد علي حسن")
        db.commit()
        assert a is not None and b is not None
        assert a.id == b.id
        assert db.scalar(select(PersonIdentity).where(PersonIdentity.reference_normalized == "MIL-4471")) is not None


def test_no_reference_creates_no_identity():
    """مكتوم القيد / غير محدد الهوية are legitimate: they simply cannot own a voice print."""
    with SessionLocal() as db:
        assert get_or_create_identity(db, None, "شخص") is None
        assert get_or_create_identity(db, "   ", "شخص") is None
        db.commit()
        assert db.scalars(select(PersonIdentity)).all() == []


def test_conflicting_name_is_refused_without_mutating():
    with SessionLocal() as db:
        get_or_create_identity(db, "MIL-4471", "الرائد علي حسن")
        db.commit()
        with pytest.raises(ReferenceNameMismatch):
            get_or_create_identity(db, "MIL-4471", "أحمد محمد")
        db.rollback()
        rows = db.scalars(select(PersonIdentity)).all()
        assert len(rows) == 1
        assert rows[0].person_name == "الرائد علي حسن"


# --------------------------------------------------------------------------
# aliases
# --------------------------------------------------------------------------

def _merge(db, source: PersonIdentity, target: PersonIdentity) -> None:
    source.merged_into_id = target.id
    db.flush()


def test_alias_resolves_to_the_survivor_and_cannot_be_recreated():
    with SessionLocal() as db:
        a = get_or_create_identity(db, "REF-A", "علي")
        b = get_or_create_identity(db, "REF-B", "علي")
        _merge(db, b, a)
        db.commit()

        # A stale client submitting the merged-away reference lands on the survivor.
        resolved = get_or_create_identity(db, "REF-B", "علي")
        db.commit()
        assert resolved is not None and resolved.id == a.id
        assert len(db.scalars(select(PersonIdentity)).all()) == 2  # B kept as an alias, not recreated


def test_alias_name_is_validated_against_the_terminal_identity():
    """An alias row's own name is history; the survivor's name is what counts."""
    with SessionLocal() as db:
        a = get_or_create_identity(db, "REF-A", "الرائد علي حسن")
        b = get_or_create_identity(db, "REF-B", "علي حسن")   # older, different spelling
        _merge(db, b, a)
        db.commit()

        # The survivor's current name succeeds even though the alias row records another.
        assert get_or_create_identity(db, "REF-B", "الرائد علي حسن").id == a.id
        db.commit()

        with pytest.raises(ReferenceNameMismatch):
            get_or_create_identity(db, "REF-B", "أحمد محمد")
        db.rollback()


def test_resolution_survives_a_corrupt_cycle():
    """A cycle should be impossible, but resolution must not spin forever if one exists."""
    with SessionLocal() as db:
        a = get_or_create_identity(db, "REF-A", "علي")
        b = get_or_create_identity(db, "REF-B", "علي")
        a.merged_into_id = b.id
        b.merged_into_id = a.id
        db.flush()
        assert resolve_identity(db, a) is not None  # terminates


def test_find_identity_returns_none_for_unknown_reference():
    with SessionLocal() as db:
        assert find_identity(db, "NOPE-1") is None


# --------------------------------------------------------------------------
# real concurrency
# --------------------------------------------------------------------------

def test_concurrent_creation_yields_exactly_one_identity():
    """Two investigators entering the same person at the same moment.

    This is the test that proves the UNIQUE(reference_normalized) is doing the work: with a
    plain SELECT-then-INSERT both threads would see nothing and both would insert.
    """
    reference = f"MIL-{uuid.uuid4().hex[:8].upper()}"
    results: list[uuid.UUID | None] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        try:
            with SessionLocal() as db:
                barrier.wait(timeout=10)          # maximise the overlap
                identity = get_or_create_identity(db, reference, "الرائد علي حسن")
                db.commit()
                results.append(identity.id if identity else None)
        except Exception as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"unexpected errors: {errors}"
    assert len(results) == 2
    assert results[0] == results[1], "both callers must receive the same canonical identity"

    with SessionLocal() as db:
        rows = db.scalars(
            select(PersonIdentity).where(PersonIdentity.reference_normalized == reference)
        ).all()
        assert len(rows) == 1, "the database must permit exactly one row for a reference"


def test_database_rejects_a_duplicate_reference_directly():
    """Proves the guarantee is in the schema, not only in the service."""
    from sqlalchemy.exc import IntegrityError

    with SessionLocal() as db:
        get_or_create_identity(db, "MIL-9001", "علي")
        db.commit()
        db.add(
            PersonIdentity(
                reference_normalized="MIL-9001", reference_display="MIL-9001", person_name="آخر"
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


# --------------------------------------------------------------------------
# merging: aliases, resurrection, cycles
# --------------------------------------------------------------------------

def test_merge_keeps_the_source_as_an_alias():
    from app.services.person_identity import merge_identities

    with SessionLocal() as db:
        a = get_or_create_identity(db, "REF-A", "علي")
        b = get_or_create_identity(db, "REF-B", "علي")
        db.commit()
        source, target = merge_identities(db, b.id, a.id)
        db.commit()
        assert target.id == a.id
        assert source.merged_into_id == a.id
        # Kept, not deleted: the retained UNIQUE row is what blocks resurrection.
        assert db.get(PersonIdentity, b.id) is not None


def test_self_merge_and_cycles_are_rejected():
    from app.services.person_identity import IdentityMergeConflict, merge_identities

    with SessionLocal() as db:
        a = get_or_create_identity(db, "REF-A", "علي")
        b = get_or_create_identity(db, "REF-B", "علي")
        db.commit()

        with pytest.raises(IdentityMergeConflict):
            merge_identities(db, a.id, a.id)
        db.rollback()

        merge_identities(db, b.id, a.id)
        db.commit()
        # A -> B would close the loop B -> A -> B.
        with pytest.raises(IdentityMergeConflict):
            merge_identities(db, a.id, b.id)
        db.rollback()


def test_merged_reference_is_not_resurrected_by_a_stale_payload():
    """The scenario that makes aliases necessary.

    `_apply_subjects` reads subjects from the REQUEST, not the database, so no amount of
    rewriting stored rows stops a stale tab from submitting the merged-away reference.
    """
    from app.services.person_identity import merge_identities

    with SessionLocal() as db:
        a = get_or_create_identity(db, "REF-A", "علي")
        b = get_or_create_identity(db, "REF-B", "علي")
        db.commit()
        merge_identities(db, b.id, a.id)
        db.commit()
        before = len(db.scalars(select(PersonIdentity)).all())

        # A stale client submits the dead reference.
        resolved = get_or_create_identity(db, "REF-B", "علي")
        db.commit()

        assert resolved.id == a.id
        assert len(db.scalars(select(PersonIdentity)).all()) == before, "REF-B must not be recreated"


def test_concurrent_opposite_merges_cannot_commit_a_cycle():
    """A -> B racing B -> A, for real.

    The chain check alone is not enough: both transactions can see no cycle and both write.
    Locking the terminals in sorted UUID order, then re-resolving, is what prevents it.
    """
    from app.services.person_identity import IdentityMergeConflict, merge_identities

    with SessionLocal() as db:
        a = get_or_create_identity(db, f"REF-A-{uuid.uuid4().hex[:6]}", "علي")
        b = get_or_create_identity(db, f"REF-B-{uuid.uuid4().hex[:6]}", "علي")
        db.commit()
        a_id, b_id = a.id, b.id

    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def merge(src, dst) -> None:
        try:
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                merge_identities(db, src, dst)
                db.commit()
                outcomes.append("ok")
        except IdentityMergeConflict:
            outcomes.append("conflict")
        except Exception as exc:  # noqa: BLE001 - surfaced in the assertion below
            outcomes.append(f"error:{type(exc).__name__}")

    threads = [
        threading.Thread(target=merge, args=(a_id, b_id)),
        threading.Thread(target=merge, args=(b_id, a_id)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(outcomes) == 2, f"both threads must finish: {outcomes}"

    # Whatever the interleaving, the graph must still terminate.
    with SessionLocal() as db:
        a_row = db.get(PersonIdentity, a_id)
        b_row = db.get(PersonIdentity, b_id)
        assert not (a_row.merged_into_id == b_id and b_row.merged_into_id == a_id), (
            f"a cycle was committed: {outcomes}"
        )
        assert resolve_identity(db, a_row) is not None
        assert resolve_identity(db, b_row) is not None
