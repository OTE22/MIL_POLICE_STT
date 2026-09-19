"""Retiring LBN-/UNHCR-/UNRWA- canonical references onto CIV-*, without guessing.

The migration has already run against the test database, so these tests re-run its logic
against rows they plant themselves. That is deliberate: the interesting cases are legacy data
shapes that no longer occur, and the only way to prove the migration handles them is to build
them.

The point being defended: a person keeps their identity_id. A wrong naming scheme is not a
reason for someone to become a different person and lose their prints.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.db.session import SessionLocal, engine


@pytest.fixture(autouse=True)
def legacy_reference_columns():
    """This historical migration is tested against its historical schema only."""
    columns = {
        "person_identities": ["reference_normalized", "reference_display"],
        "subjects": ["reference_number"],
        "session_speakers": ["reference_number"],
        "voice_enrollments": ["person_reference"],
    }
    with engine.begin() as db:
        for table, names in columns.items():
            for name in names:
                db.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {name} varchar(100)"))
        db.execute(sa.text("CREATE SEQUENCE civilian_person_reference_seq"))
    try:
        yield
    finally:
        with engine.begin() as db:
            for table, names in columns.items():
                for name in names:
                    db.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN {name}"))
            db.execute(sa.text("DROP SEQUENCE civilian_person_reference_seq"))

MIGRATION = "20260826_c4f70ab8d915_retire_family_keyed_references"


def _load_migration():
    """Import the migration module by path - it is not on the package path."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / f"{MIGRATION}.py"
    spec = importlib.util.spec_from_file_location(MIGRATION, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identity(db, reference: str, name: str) -> uuid.UUID:
    identity_id = uuid.uuid4()
    db.execute(
        sa.text(
            "INSERT INTO person_identities (id, reference_normalized, reference_display, person_name) "
            "VALUES (:i, :r, :r, :n)"
        ),
        {"i": identity_id, "r": reference, "n": name},
    )
    return identity_id


def _session(db) -> uuid.UUID:
    session_id = uuid.uuid4()
    user_id = db.execute(sa.text("SELECT id FROM users LIMIT 1")).scalar_one()
    db.execute(
        sa.text(
            "INSERT INTO investigation_sessions (id, session_number, title, status, created_by) "
            "VALUES (:i, :n, 'جلسة', 'DRAFT', :u)"
        ),
        {"i": session_id, "n": f"INV-{uuid.uuid4().hex[:8]}", "u": user_id},
    )
    return session_id


def _subject(db, session_id, identity_id, name, reference) -> uuid.UUID:
    subject_id = uuid.uuid4()
    db.execute(
        sa.text(
            "INSERT INTO subjects (id, session_id, identity_id, subject_name, reference_number, "
            "person_type, participant_key) "
            "VALUES (:i, :s, :d, :n, :r, 'CIVILIAN', gen_random_uuid())"
        ),
        {"i": subject_id, "s": session_id, "d": identity_id, "n": name, "r": reference},
    )
    return subject_id


def _run_upgrade(db, monkeypatch):
    """Run the migration body against this session's connection."""
    module = _load_migration()
    monkeypatch.setattr(module.op, "get_bind", lambda: db.connection(), raising=False)
    module.upgrade()


def _reference_of(db, identity_id) -> str:
    return db.execute(
        sa.text("SELECT reference_display FROM person_identities WHERE id = :i"), {"i": identity_id}
    ).scalar_one()


# --------------------------------------------------------------------------
# the unambiguous case
# --------------------------------------------------------------------------

def test_an_unambiguous_family_key_becomes_a_civilian_reference(monkeypatch):
    with SessionLocal() as db:
        identity_id = _identity(db, "LBN-ZAHLE-123", "علي حسن")
        session_id = _session(db)
        _subject(db, session_id, identity_id, "علي حسن", "LBN-ZAHLE-123")
        db.flush()

        _run_upgrade(db, monkeypatch)

        # Same person, new name for them.
        new_reference = _reference_of(db, identity_id)
        assert new_reference.startswith("CIV-")
        # Current-state rows followed.
        assert db.execute(
            sa.text("SELECT reference_number FROM subjects WHERE identity_id = :i"), {"i": identity_id}
        ).scalar_one() == new_reference
        # And the family key is NOT reinstated as something that resolves a person.
        assert db.execute(
            sa.text("SELECT count(*) FROM person_identities WHERE reference_normalized = 'LBN-ZAHLE-123'")
        ).scalar_one() == 0
        db.rollback()


def test_one_person_in_several_investigations_is_still_one_person(monkeypatch):
    """More than one participant is normal - it is the whole point of a registry."""
    with SessionLocal() as db:
        identity_id = _identity(db, "LBN-ZAHLE-77", "علي حسن")
        for _ in range(2):
            _subject(db, _session(db), identity_id, "علي حسن", "LBN-ZAHLE-77")
        db.flush()

        _run_upgrade(db, monkeypatch)

        assert _reference_of(db, identity_id).startswith("CIV-")
        db.rollback()


# --------------------------------------------------------------------------
# refusing rather than guessing
# --------------------------------------------------------------------------

def test_a_family_key_recorded_against_two_names_is_refused(monkeypatch):
    """Two humans behind one رقم سجل. Splitting them is an operator decision, not ours."""
    with SessionLocal() as db:
        identity_id = _identity(db, "LBN-ZAHLE-123", "علي حسن")
        session_id = _session(db)
        _subject(db, session_id, identity_id, "علي حسن", "LBN-ZAHLE-123")
        _subject(db, session_id, identity_id, "حسن حسن", "LBN-ZAHLE-123")
        db.flush()

        with pytest.raises(RuntimeError) as raised:
            _run_upgrade(db, monkeypatch)

        message = str(raised.value)
        assert "LBN-ZAHLE-123" in message
        assert "علي حسن" in message and "حسن حسن" in message
        assert "by hand" in message, "the operator must be told what to do about it"
        db.rollback()


def test_two_passports_under_one_reference_are_refused(monkeypatch):
    """Two of one document kind is two people, whatever the names happen to say."""
    with SessionLocal() as db:
        identity_id = _identity(db, "LBN-ZAHLE-9", "علي حسن")
        session_id = _session(db)
        first = _subject(db, session_id, identity_id, "علي حسن", "LBN-ZAHLE-9")
        second = _subject(db, session_id, identity_id, "علي حسن", "LBN-ZAHLE-9")
        for subject_id, number in ((first, "P1111111"), (second, "P2222222")):
            db.execute(
                sa.text(
                    "INSERT INTO subject_documents (id, subject_id, document_type, document_number) "
                    "VALUES (gen_random_uuid(), :s, 'PASSPORT', :n)"
                ),
                {"s": subject_id, "n": number},
            )
        db.flush()

        with pytest.raises(RuntimeError) as raised:
            _run_upgrade(db, monkeypatch)
        assert "PASSPORT" in str(raised.value)
        db.rollback()


def test_nothing_is_migrated_when_any_identity_is_ambiguous(monkeypatch):
    """All-or-nothing: a half-migrated registry is worse than an unmigrated one."""
    with SessionLocal() as db:
        safe = _identity(db, "LBN-BEIRUT-1", "سمير خالد")
        unsafe = _identity(db, "LBN-ZAHLE-2", "علي حسن")
        session_id = _session(db)
        _subject(db, session_id, safe, "سمير خالد", "LBN-BEIRUT-1")
        _subject(db, session_id, unsafe, "علي حسن", "LBN-ZAHLE-2")
        _subject(db, session_id, unsafe, "حسن حسن", "LBN-ZAHLE-2")
        db.flush()

        with pytest.raises(RuntimeError):
            _run_upgrade(db, monkeypatch)

        assert _reference_of(db, safe) == "LBN-BEIRUT-1", "the safe identity must not have moved"
        db.rollback()


# --------------------------------------------------------------------------
# agency cards become evidence, not identity
# --------------------------------------------------------------------------

def test_an_agency_card_becomes_an_external_identifier(monkeypatch):
    with SessionLocal() as db:
        identity_id = _identity(db, "UNHCR-556677", "علي حسن")
        _subject(db, _session(db), identity_id, "علي حسن", "UNHCR-556677")
        db.flush()

        _run_upgrade(db, monkeypatch)

        assert _reference_of(db, identity_id).startswith("CIV-")
        # The number survives where it can still find the person.
        row = db.execute(
            sa.text(
                "SELECT identifier_type, value_normalized FROM person_identifiers "
                "WHERE identity_id = :i"
            ),
            {"i": identity_id},
        ).mappings().one()
        assert row["identifier_type"] == "UNHCR"
        assert row["value_normalized"] == "556677"
        db.rollback()


def test_the_identity_id_never_changes(monkeypatch):
    """A person keeps their prints, speakers and history. Only their name for us changes."""
    with SessionLocal() as db:
        identity_id = _identity(db, "LBN-TRIPOLI-5", "علي حسن")
        _subject(db, _session(db), identity_id, "علي حسن", "LBN-TRIPOLI-5")
        db.flush()

        _run_upgrade(db, monkeypatch)

        assert db.execute(
            sa.text("SELECT count(*) FROM person_identities WHERE id = :i"), {"i": identity_id}
        ).scalar_one() == 1
        db.rollback()
