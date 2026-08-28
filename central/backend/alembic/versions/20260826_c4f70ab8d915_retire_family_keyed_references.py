"""Retire family-keyed and document-keyed canonical references.

LBN-<CAZA>-<REGISTER> keyed a canonical person on رقم السجل, which identifies a FAMILY civil
record - an إخراج قيد lists everyone registered under it. UNHCR-/UNRWA- keyed one on a card
number, which is evidence about a person rather than the person. Both are replaced by CIV-*,
issued by us and stable across every document being corrected or reissued.

The identity_id never changes. A person does not become someone else because the scheme that
named them was wrong; their prints, speakers and history all stay attached.

WHAT THIS MIGRATION CANNOT DETECT
---------------------------------
The old code REFUSED a second person whose name differed from the one already on a reference.
So relatives with different names were blocked at data entry and never merged - the collapse
only ever happened silently between relatives who share a NAME, and that case is by
construction invisible to a name-based check.

This migration therefore refuses on any conflicting evidence it CAN see, and reports every
LBN identity carrying more than one participant so an operator can review the rest by hand.
It does not guess, does not auto-split, and does not merge.

Revision ID: c4f70ab8d915
Revises: a7d3e0c9b512
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4f70ab8d915"
down_revision = "a7d3e0c9b512"
branch_labels = None
depends_on = None

# Canonical references that were keyed on something that is not a person.
RETIRED_PREFIXES = ("LBN-", "UNHCR-", "UNRWA-")
# The card schemes become external identifiers instead of being discarded.
AGENCY_TYPES = {"UNHCR-": "UNHCR", "UNRWA-": "UNRWA"}


def _prefix(reference: str) -> str | None:
    for prefix in RETIRED_PREFIXES:
        if reference.upper().startswith(prefix):
            return prefix
    return None


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            "SELECT id, reference_display, reference_normalized, person_name "
            "FROM person_identities WHERE merged_into_id IS NULL"
        )
    ).mappings().all()
    retired = [r for r in rows if _prefix(r["reference_normalized"] or "")]
    if not retired:
        return

    ambiguous: list[str] = []
    review: list[str] = []

    for row in retired:
        identity_id = row["id"]
        reference = row["reference_normalized"]

        # Every distinct human name recorded against this identity. Trimmed only: folding
        # further would be inventing a same-person rule, which is the mistake being undone.
        names = {
            (n or "").strip()
            for n in conn.execute(
                sa.text(
                    "SELECT DISTINCT subject_name FROM subjects WHERE identity_id = :i "
                    "UNION SELECT DISTINCT person_name FROM voice_enrollments WHERE identity_id = :i"
                ),
                {"i": identity_id},
            ).scalars().all()
            if (n or "").strip()
        }

        # Two passports, or two of any one document kind, is two people - whatever the names say.
        clashing_documents = conn.execute(
            sa.text(
                "SELECT d.document_type, count(DISTINCT d.document_number) AS n "
                "FROM subject_documents d JOIN subjects s ON s.id = d.subject_id "
                "WHERE s.identity_id = :i AND coalesce(d.document_number, '') <> '' "
                "GROUP BY d.document_type HAVING count(DISTINCT d.document_number) > 1"
            ),
            {"i": identity_id},
        ).mappings().all()

        if len(names) > 1:
            ambiguous.append(f"{row['reference_display']} -> names {sorted(names)}")
            continue
        if clashing_documents:
            kinds = ", ".join(f"{d['document_type']}x{d['n']}" for d in clashing_documents)
            ambiguous.append(f"{row['reference_display']} -> several documents of one kind ({kinds})")
            continue

        participants = conn.execute(
            sa.text("SELECT count(*) FROM subjects WHERE identity_id = :i"), {"i": identity_id}
        ).scalar_one()
        if reference.startswith("LBN-") and participants > 1:
            # Not refused - one person legitimately appears in several investigations - but a
            # family key carrying several participants is exactly where a silent collapse would
            # hide, and only a human can tell the two apart.
            review.append(f"{row['reference_display']} ({participants} participants)")

    if ambiguous:
        detail = "; ".join(sorted(ambiguous))
        raise RuntimeError(
            "Cannot retire family-keyed references: one reference is recorded against more "
            "than one person. رقم السجل identifies a family, so these may be relatives that "
            "were collapsed into a single canonical identity. Split them by hand, then re-run "
            f"the migration. {detail}"
        )

    for row in retired:
        identity_id = row["id"]
        old_display = row["reference_display"]
        prefix = _prefix(row["reference_normalized"])

        value = conn.execute(sa.text("SELECT nextval('civilian_person_reference_seq')")).scalar_one()
        new_reference = f"CIV-{int(value):08d}"

        conn.execute(
            sa.text(
                "UPDATE person_identities SET reference_display = :d, reference_normalized = :d "
                "WHERE id = :i"
            ),
            {"d": new_reference, "i": identity_id},
        )
        # Current-state rows follow the person. Enrolment snapshots deliberately do not: they
        # record what was true when the print was taken.
        for table in ("subjects", "session_speakers"):
            conn.execute(
                sa.text(f"UPDATE {table} SET reference_number = :d WHERE identity_id = :i"),
                {"d": new_reference, "i": identity_id},
            )

        # An agency card was never the person, but it IS good evidence for finding them again.
        # The old canonical value survives here, as an identifier - deliberately NOT as an
        # alias row, which would resolve automatically and recreate the unsafe assumption.
        agency = AGENCY_TYPES.get(prefix or "")
        if agency:
            number = old_display.split("-", 1)[1] if "-" in old_display else old_display
            conn.execute(
                sa.text(
                    "INSERT INTO person_identifiers "
                    "(id, identity_id, identifier_type, issuer_namespace, value_display, value_normalized) "
                    "VALUES (gen_random_uuid(), :i, :t, '', :v, :n) "
                    "ON CONFLICT (identifier_type, issuer_namespace, value_normalized) DO NOTHING"
                ),
                {"i": identity_id, "t": agency, "v": number, "n": number.strip().upper()},
            )

        print(f"[identity] {old_display} -> {new_reference} (identity {identity_id} unchanged)")

    if review:
        print(
            "[identity][REVIEW] family-keyed references carrying several participants. These "
            "were migrated because nothing contradicted them, but a family register cannot "
            "prove one person - confirm each is a single human: " + "; ".join(sorted(review))
        )


def downgrade() -> None:
    # The mapping back to a family key is not reconstructible, and reinstating it would
    # reinstate the defect. Deliberately not implemented.
    raise NotImplementedError("retiring family-keyed references cannot be undone")
