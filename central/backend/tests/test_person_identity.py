"""Person UUID creation, identifier normalization and concurrent merge safety."""
import threading
import uuid
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import PersonIdentity
from app.services.person_identity import create_identity, resolve_identity, normalize_identifier, identity_for_person

@pytest.mark.parametrize("value, expected", [(None,None),("  ",None),(" ab-٤٤٧١ ","AB-4471"),("ab  4471","AB 4471")])
def test_external_identifier_normalization(value, expected):
    assert normalize_identifier(value) == expected

def test_same_names_do_not_reuse_identity():
    with SessionLocal() as db:
        a = create_identity(db, "علي")
        b = create_identity(db, "علي")
        assert a.id != b.id

def test_concurrent_military_claims_reuse_one_uuid():
    ids, errors = [], []
    barrier = threading.Barrier(2)
    def create():
        try:
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                person = identity_for_person(db, SimpleNamespace(subject_name="علي", military_id="4471", security_branch="ARMY"))
                db.commit()
                ids.append(person.id)
        except Exception as exc:
            errors.append(str(exc))
    threads = [threading.Thread(target=create) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=20)
    assert not errors
    assert len(ids) == 2 and ids[0] == ids[1]

def test_merge_keeps_the_source_as_an_alias():
    from app.services.person_identity import merge_identities

    with SessionLocal() as db:
        a = create_identity(db, "علي")
        b = create_identity(db, "علي")
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
        a = create_identity(db, "علي")
        b = create_identity(db, "علي")
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
        a = create_identity(db, "علي")
        b = create_identity(db, "علي")
        db.commit()
        merge_identities(db, b.id, a.id)
        db.commit()
        before = len(db.scalars(select(PersonIdentity)).all())

        # A stale client submits the dead reference.
        resolved = resolve_identity(db, db.get(PersonIdentity, b.id))
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
        a = create_identity(db, "علي")
        b = create_identity(db, "علي")
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
