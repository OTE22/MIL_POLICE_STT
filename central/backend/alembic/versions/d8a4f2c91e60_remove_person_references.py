"""Replace person reference numbers with existing stable UUID relationships.

Revision ID: d8a4f2c91e60
Revises: c7e14b93a2f6
"""
from __future__ import annotations

import unicodedata
import uuid

import sqlalchemy as sa
from alembic import op

revision = "d8a4f2c91e60"
down_revision = "c7e14b93a2f6"
branch_labels = None
depends_on = None


def _normalize(value):
    digits = {ord("٠") + i: str(i) for i in range(10)}
    digits.update({ord("۰") + i: str(i) for i in range(10)})
    return " ".join(unicodedata.normalize("NFKC", value or "").translate(digits).split()).upper()


def upgrade():
    db = op.get_bind()
    rows = db.execute(sa.text("SELECT id, reference_normalized, merged_into_id FROM person_identities")).mappings().all()
    by_id = {r["id"]: r for r in rows}
    def survivor(identity_id):
        seen = set()
        while identity_id in by_id and by_id[identity_id]["merged_into_id"]:
            if identity_id in seen:
                raise RuntimeError("Person identity merge cycle; repair before migration")
            seen.add(identity_id)
            identity_id = by_id[identity_id]["merged_into_id"]
        return identity_id
    by_reference = {_normalize(r["reference_normalized"]): survivor(r["id"]) for r in rows}

    # Recover legacy rows that have a reference but lack their UUID link, before dropping it.
    # Rows without references get separate UUIDs; matching a name must never merge people.
    for table, reference, name in [
        ("subjects", "reference_number", "subject_name"),
        ("investigator_profiles", "reference_number", "full_name"),
        ("session_speakers", "reference_number", "display_name"),
        ("voice_enrollments", "person_reference", "person_name"),
    ]:
        for row in db.execute(sa.text(f"SELECT id, identity_id, {reference} AS ref, {name} AS name FROM {table}")).mappings().all():
            identity_id = survivor(row["identity_id"]) if row["identity_id"] else by_reference.get(_normalize(row["ref"]))
            # An anonymous diarization speaker is not an identified person.
            if not identity_id and table == "session_speakers" and not row["ref"]:
                continue
            if not identity_id:
                if not (row["name"] or "").strip():
                    if table == "voice_enrollments":
                        raise RuntimeError("Voice enrollment has neither a person nor a name; resolve before migration")
                    continue
                identity_id = uuid.uuid4()
                temporary = f"migration-{identity_id}"
                db.execute(sa.text("INSERT INTO person_identities (id, person_name, reference_normalized, reference_display) VALUES (:id, :name, :ref, :ref)"),
                           {"id": identity_id, "name": row["name"].strip(), "ref": temporary})
                if row["ref"]:
                    by_reference[_normalize(row["ref"])] = identity_id
            db.execute(sa.text(f"UPDATE {table} SET identity_id = :identity WHERE id = :id"), {"identity": identity_id, "id": row["id"]})

    # Preserve military-number recognition (including old aliases) as scoped evidence,
    # rather than generating MIL-* identifiers for people ever again.
    military = []
    branches = {"ARMY", "ISF", "GENERAL_SECURITY", "STATE_SECURITY", "CUSTOMS"}
    for ref, identity_id in by_reference.items():
        pieces = ref.split("-", 2)
        if len(pieces) == 3 and pieces[0] == "MIL" and pieces[1] in branches:
            military.append((identity_id, pieces[1], pieces[2]))
    for table in ("subjects", "investigator_profiles"):
        military.extend((r["identity_id"], r["security_branch"], r["military_id"]) for r in db.execute(sa.text(
            f"SELECT identity_id, security_branch::text, military_id FROM {table} WHERE identity_id IS NOT NULL AND military_id IS NOT NULL"
        )).mappings() if r["security_branch"] in branches)
    for identity_id, branch, serial in military:
        normalized = _normalize(serial)
        if not normalized:
            continue
        existing = db.execute(sa.text("SELECT identity_id FROM person_identifiers WHERE identifier_type='MILITARY' AND issuer_namespace=:branch AND value_normalized=:value"),
                              {"branch": branch, "value": normalized}).scalar()
        if existing:
            if survivor(existing) != identity_id:
                raise RuntimeError("Conflicting military identifiers; resolve before migration")
            continue
        db.execute(sa.text("INSERT INTO person_identifiers (id, identity_id, identifier_type, issuer_namespace, value_display, value_normalized) VALUES (:id, :identity, 'MILITARY', :branch, :display, :value)"),
                   {"id": uuid.uuid4(), "identity": identity_id, "branch": branch, "display": serial, "value": normalized})

    op.drop_index("ix_voice_enrollment_person_model", table_name="voice_enrollments")
    op.create_index("ix_voice_enrollment_identity_model", "voice_enrollments", ["identity_id", "model"])
    for table, column in [("subjects", "reference_number"), ("investigator_profiles", "reference_number"),
                          ("session_speakers", "reference_number"), ("voice_enrollments", "person_reference"),
                          ("person_identities", "reference_display"), ("person_identities", "reference_normalized")]:
        op.drop_column(table, column)
    op.execute("DROP SEQUENCE IF EXISTS civilian_person_reference_seq")
    op.execute("DROP SEQUENCE IF EXISTS tmp_person_reference_seq")
    # Permission grants cascade with the obsolete permission row.
    op.execute("DELETE FROM permissions WHERE code = 'subjects.reference.override'")


def downgrade():
    raise RuntimeError("Reference numbers were retired. Restore a pre-migration backup to downgrade.")
