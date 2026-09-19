"""Exercise the migration against legacy rows in an isolated transactional schema."""
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.db.session import engine


def test_legacy_links_aliases_and_service_numbers_survive():
    # The installed alembic package owns that namespace, so load our revision by file path.
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('retire_reference_revision', Path(__file__).parents[1] / 'alembic/versions/d8a4f2c91e60_remove_person_references.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    survivor, alias, subject, speaker, enrollment, investigator = [uuid.uuid4() for _ in range(6)]
    schema = 'migration_test_' + uuid.uuid4().hex
    with engine.connect() as db:
        transaction = db.begin()
        try:
            db.execute(text(f'CREATE SCHEMA {schema}'))
            db.execute(text(f'SET LOCAL search_path TO {schema}'))
            db.execute(text('CREATE TABLE person_identities (id uuid PRIMARY KEY, person_name text NOT NULL, reference_normalized text UNIQUE, reference_display text, merged_into_id uuid, created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now())'))
            db.execute(text('CREATE TABLE person_identifiers (id uuid PRIMARY KEY, identity_id uuid, identifier_type text, issuer_namespace text, value_display text, value_normalized text, UNIQUE(identifier_type, issuer_namespace, value_normalized))'))
            for table, name in [('subjects', 'subject_name'), ('investigator_profiles', 'full_name'), ('session_speakers', 'display_name')]:
                db.execute(text(f'CREATE TABLE {table} (id uuid PRIMARY KEY, identity_id uuid, reference_number text, {name} text, military_id text, security_branch text)'))
            db.execute(text('CREATE TABLE voice_enrollments (id uuid PRIMARY KEY, identity_id uuid, person_reference text, person_name text, model text)'))
            db.execute(text('CREATE INDEX ix_voice_enrollment_person_model ON voice_enrollments (person_reference, model)'))
            db.execute(text('CREATE TABLE permissions (code text)'))
            db.execute(text("INSERT INTO permissions VALUES ('subjects.reference.override')"))
            db.execute(text('CREATE SEQUENCE civilian_person_reference_seq'))
            db.execute(text('CREATE SEQUENCE tmp_person_reference_seq'))
            db.execute(text("INSERT INTO person_identities VALUES (:id, 'Ali', 'SPECIAL-1', 'SPECIAL-1', NULL, now(), now()), (:alias, 'Ali', 'MIL-ARMY-4471', 'MIL-ARMY-4471', :id, now(), now())"), {'id': survivor, 'alias': alias})
            for table, name, rowid in [('subjects', 'subject_name', subject), ('investigator_profiles', 'full_name', investigator), ('session_speakers', 'display_name', speaker)]:
                db.execute(text(f"INSERT INTO {table} VALUES (:id, :alias, 'MIL-ARMY-4471', 'Ali', '4471', 'ARMY')"), {'id': rowid, 'alias': alias})
            db.execute(text("INSERT INTO voice_enrollments VALUES (:id, NULL, 'MIL-ARMY-4471', 'Ali', 'model')"), {'id': enrollment})
            with Operations.context(MigrationContext.configure(db)):
                migration.upgrade()
            for table in ['subjects', 'session_speakers', 'investigator_profiles', 'voice_enrollments']:
                assert db.execute(text(f'SELECT identity_id FROM {table}')).scalar_one() == survivor
            assert db.execute(text('SELECT merged_into_id FROM person_identities WHERE id=:id'), {'id': alias}).scalar_one() == survivor
            assert db.execute(text("SELECT identity_id FROM person_identifiers WHERE identifier_type='MILITARY' AND value_normalized='4471'")).scalar_one() == survivor
            assert db.execute(text('SELECT count(*) FROM permissions')).scalar_one() == 0
        finally:
            transaction.rollback()
