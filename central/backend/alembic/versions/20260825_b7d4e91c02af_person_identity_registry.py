"""Canonical person identity registry

`Subject` is session-scoped and recreated on every session save, so nothing tied the same
human together across sessions. Two investigators entering one person produced two unrelated
records — which is how one person acquired three reference numbers and made the voice matcher
treat his own embeddings as competing identities.

Adds `person_identities`, keyed by a normalized reference number with a UNIQUE constraint as
the cross-session guarantee, and points subjects, speakers and voice prints at it. Merged rows
are retained with `merged_into_id` so a merged-away reference can never be recreated.

Also adds the partial unique index that makes enrolment race-safe: one ACTIVE print per
source sample per model. `model` is part of the key because embeddings are not comparable
across models and `best_match` filters on it.

Revision ID: b7d4e91c02af
Revises: a3f1c7b9e204
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b7d4e91c02af"
down_revision = "a3f1c7b9e204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "person_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reference_normalized", sa.String(length=100), nullable=False),
        sa.Column("reference_display", sa.String(length=100), nullable=False),
        sa.Column("person_name", sa.String(length=200), nullable=False),
        sa.Column("merged_into_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merged_into_id"], ["person_identities.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("reference_normalized", name="uq_person_identity_reference"),
    )
    op.create_index("ix_person_identities_reference_normalized", "person_identities", ["reference_normalized"])
    op.create_index("ix_person_identities_merged_into_id", "person_identities", ["merged_into_id"])

    for table in ("subjects", "session_speakers", "voice_enrollments"):
        op.add_column(table, sa.Column("identity_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_index(f"ix_{table}_identity_id", table, ["identity_id"])
        op.create_foreign_key(
            f"fk_{table}_identity", table, "person_identities", ["identity_id"], ["id"], ondelete="SET NULL"
        )

    _backfill_identities()

    # Enrolment race safety: two operators, or one double-click, must not create two prints
    # from the same sample. A SELECT-then-INSERT cannot prevent it under READ COMMITTED.
    op.execute(
        "CREATE UNIQUE INDEX uq_voice_enrollment_active_source "
        "ON voice_enrollments (source_session_id, source_speaker_label, model) "
        "WHERE is_active"
    )


def _backfill_identities() -> None:
    """Attach existing rows to canonical identities.

    Matching and grouping move to identity_id, so a legacy row left without one would stop
    matching silently. Every existing reference is therefore resolved here, using the *same*
    normalization function as the application - a second rule written in SQL would drift.
    """
    # Importing the app's normalizer keeps exactly one definition of "same reference".
    from app.services.person_identity import normalize_reference

    conn = op.get_bind()

    # (normalized, display, name) from every table that carries a reference today.
    sources = [
        ("subjects", "reference_number", "subject_name"),
        ("session_speakers", "reference_number", "display_name"),
        ("voice_enrollments", "person_reference", "person_name"),
    ]

    identities: dict[str, tuple[str, str]] = {}   # normalized -> (display, name)
    conflicts: dict[str, set[str]] = {}           # normalized -> names seen

    for table, ref_col, name_col in sources:
        rows = conn.execute(
            sa.text(f"SELECT {ref_col} AS ref, {name_col} AS name FROM {table} WHERE {ref_col} IS NOT NULL")
        ).mappings()
        for row in rows:
            normalized = normalize_reference(row["ref"])
            if not normalized:
                continue
            name = (row["name"] or "").strip()
            if name:
                conflicts.setdefault(normalized, set()).add(name)
            if normalized not in identities or (name and identities[normalized][1] == ""):
                identities[normalized] = ((row["ref"] or "").strip(), name)

    # One reference carrying two different names is a genuine ambiguity. Guessing which is
    # canonical could file a biometric print under the wrong person, so refuse and report.
    ambiguous = {ref: names for ref, names in conflicts.items() if len(names) > 1}
    if ambiguous:
        detail = "; ".join(f"{ref} -> {sorted(names)}" for ref, names in sorted(ambiguous.items()))
        raise RuntimeError(
            "Cannot backfill canonical identities: the same reference is recorded under "
            f"different names. Resolve these, then re-run the migration. {detail}"
        )

    for normalized, (display, name) in identities.items():
        conn.execute(
            sa.text(
                "INSERT INTO person_identities (id, reference_normalized, reference_display, person_name) "
                "VALUES (gen_random_uuid(), :n, :d, :name) ON CONFLICT (reference_normalized) DO NOTHING"
            ),
            {"n": normalized, "d": display or normalized, "name": name or normalized},
        )

    # Point every existing row at its identity. The join is on the normalized form, computed
    # the same way for both sides.
    for table, ref_col, _ in sources:
        rows = conn.execute(
            sa.text(f"SELECT id, {ref_col} AS ref FROM {table} WHERE {ref_col} IS NOT NULL")
        ).mappings().all()
        for row in rows:
            normalized = normalize_reference(row["ref"])
            if not normalized:
                continue
            conn.execute(
                sa.text(
                    f"UPDATE {table} SET identity_id = "
                    "(SELECT id FROM person_identities WHERE reference_normalized = :n) WHERE id = :rid"
                ),
                {"n": normalized, "rid": row["id"]},
            )

    # Nothing that could match before may become invisible now.
    orphaned = conn.execute(
        sa.text(
            "SELECT count(*) FROM voice_enrollments "
            "WHERE is_active AND person_reference IS NOT NULL AND identity_id IS NULL"
        )
    ).scalar()
    if orphaned:
        raise RuntimeError(f"{orphaned} active voice enrolment(s) did not receive a canonical identity")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_voice_enrollment_active_source")
    for table in ("voice_enrollments", "session_speakers", "subjects"):
        op.drop_constraint(f"fk_{table}_identity", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_identity_id", table_name=table)
        op.drop_column(table, "identity_id")
    op.drop_index("ix_person_identities_merged_into_id", table_name="person_identities")
    op.drop_index("ix_person_identities_reference_normalized", table_name="person_identities")
    op.drop_table("person_identities")
