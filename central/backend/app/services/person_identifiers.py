"""Attaching and resolving external identifiers.

An external identifier is evidence, not the person. It helps FIND an existing canonical
identity so the same human is reused across investigations instead of being entered twice; it
never becomes their canonical reference, and it never merges anyone on its own.

Only namespaces proven person-unique take part. Everything else may be recorded on the Subject
and searched, but must not resolve an identity automatically - a false merge attaches one
person's biometric evidence to another, and that is not recoverable.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditAction, PersonIdentifier, PersonIdentity
from app.services.person_identity import normalize_reference, resolve_identity

# Namespaces whose values are person-unique, and therefore may resolve an identity by
# themselves. The value is what must be supplied as `issuer_namespace`.
#
#   UNHCR / UNRWA   agency-wide unique -> the agency itself is the namespace
#   PASSPORT        unique per ISSUING COUNTRY -> the country must be supplied, and it is NOT
#                   the person's nationality: a Syrian may hold a travel document issued by
#                   Lebanon, and inferring the issuer from nationality would merge strangers
#
# Deliberately absent: رقم السجل and محل القيد (a family record, not a human), name, date of
# birth, mother's name, address, phone. Those are search aids and nothing more.
AGENCY_SCOPED = {"UNHCR", "UNRWA"}
ISSUER_SCOPED = {"PASSPORT", "RESIDENCY"}
RESOLVING_TYPES = AGENCY_SCOPED | ISSUER_SCOPED


class IdentifierAlreadyAssigned(Exception):
    """This identifier already belongs to a different canonical person.

    Never resolved by moving it: an identifier changing hands is either a data-entry mistake or
    two records of one human, and only an operator can say which. Carries the identity it is
    held by so the caller can offer "use that person instead" - and nothing about the sessions
    that person appears in, which the caller may not be entitled to see.
    """

    def __init__(self, *, identifier_type: str, value: str, held_by: PersonIdentity) -> None:
        self.identifier_type = identifier_type
        self.value = value
        self.held_by = held_by
        super().__init__(f"{identifier_type} {value!r} already belongs to another person")


def _namespace(identifier_type: str, issuer: str | None) -> str:
    """The authority a value is unique within, or "" when the type carries it itself."""
    if identifier_type in AGENCY_SCOPED:
        return ""
    return (issuer or "").strip().upper()


def resolves_automatically(identifier_type: str, issuer: str | None) -> bool:
    """Whether this identifier may point at a person on its own."""
    if identifier_type in AGENCY_SCOPED:
        return True
    if identifier_type in ISSUER_SCOPED:
        # Without the issuer the number is not an identity, so it stays evidence only.
        return bool(_namespace(identifier_type, issuer))
    return False


def find_by_identifier(
    db: Session, *, identifier_type: str, value: str, issuer: str | None = None
) -> PersonIdentity | None:
    """The canonical person this identifier belongs to, following any merge."""
    normalized = normalize_reference(value)
    if not normalized or not resolves_automatically(identifier_type, issuer):
        return None
    row = db.scalar(
        select(PersonIdentifier).where(
            PersonIdentifier.identifier_type == identifier_type,
            PersonIdentifier.issuer_namespace == _namespace(identifier_type, issuer),
            PersonIdentifier.value_normalized == normalized,
        )
    )
    if row is None:
        return None
    return resolve_identity(db, db.get(PersonIdentity, row.identity_id))


def attach_identifier(
    db: Session,
    *,
    identity: PersonIdentity,
    identifier_type: str,
    value: str,
    issuer: str | None = None,
) -> PersonIdentifier | None:
    """Record an identifier against a person, refusing to take it from someone else.

    Returns None when the value cannot be keyed (blank, or a type whose namespace is not
    proven) - recording it as evidence on the Subject is still fine, it simply resolves nobody.
    Re-attaching the same value to the same person is a no-op, so repeated saves are safe.
    """
    normalized = normalize_reference(value)
    if not normalized or not resolves_automatically(identifier_type, issuer):
        return None

    namespace = _namespace(identifier_type, issuer)
    existing = db.scalar(
        select(PersonIdentifier).where(
            PersonIdentifier.identifier_type == identifier_type,
            PersonIdentifier.issuer_namespace == namespace,
            PersonIdentifier.value_normalized == normalized,
        )
    )
    if existing is not None:
        holder = resolve_identity(db, db.get(PersonIdentity, existing.identity_id))
        if holder is not None and holder.id == identity.id:
            return existing
        raise IdentifierAlreadyAssigned(
            identifier_type=identifier_type, value=value.strip(), held_by=holder
        )

    row = PersonIdentifier(
        identity_id=identity.id,
        identifier_type=identifier_type,
        issuer_namespace=namespace,
        value_display=value.strip(),
        value_normalized=normalized,
    )
    db.add(row)
    db.flush()
    return row


def identifiers_for(db: Session, identity_id: uuid.UUID) -> list[PersonIdentifier]:
    return list(
        db.scalars(
            select(PersonIdentifier)
            .where(PersonIdentifier.identity_id == identity_id)
            .order_by(PersonIdentifier.identifier_type, PersonIdentifier.value_display)
        ).all()
    )

# Which presented documents carry an identifier worth keying on, and where their namespace
# comes from. Everything absent here is still recorded on the Subject as evidence - it simply
# resolves nobody.
DOCUMENT_IDENTIFIERS = {
    "UNHCR_CARD": ("UNHCR", None),
    "UNRWA_CARD": ("UNRWA", None),
    "PASSPORT": ("PASSPORT", "issuing_country"),
    "RESIDENCY_PERMIT": ("RESIDENCY", "issuing_country"),
}


def attach_from_documents(
    db: Session, *, identity: PersonIdentity, documents, user_id=None
) -> list[PersonIdentifier]:
    """Record the keyable identifiers a subject presented.

    Raises IdentifierAlreadyAssigned if one of them belongs to somebody else - the save is then
    refused whole, because quietly moving a passport from one person to another is how two
    records of two humans become one.
    """
    attached: list[PersonIdentifier] = []
    for document in documents or []:
        doc_type = getattr(document, "document_type", None)
        doc_value = doc_type.value if hasattr(doc_type, "value") else str(doc_type or "")
        mapping = DOCUMENT_IDENTIFIERS.get(doc_value)
        if mapping is None:
            continue
        identifier_type, issuer_field = mapping
        try:
            row = attach_identifier(
                db,
                identity=identity,
                identifier_type=identifier_type,
                value=getattr(document, "document_number", None) or "",
                issuer=getattr(document, issuer_field, None) if issuer_field else None,
            )
        except IdentifierAlreadyAssigned as clash:
            # Worth a record even though nothing changed: an attempt to move an identifier
            # between two people is either a typo worth finding, or two records of one human.
            _audit(
                db, user_id, AuditAction.PERSON_IDENTIFIER_CONFLICT, identity,
                {"identifier_type": clash.identifier_type,
                 "held_by_identity_id": str(clash.held_by.id) if clash.held_by else None},
            )
            raise
        if row is not None:
            attached.append(row)
            _audit(
                db, user_id, AuditAction.PERSON_IDENTIFIER_ADDED, identity,
                {"identifier_type": row.identifier_type, "issuer_namespace": row.issuer_namespace},
            )
    return attached


def _audit(db: Session, user_id, action, identity: PersonIdentity, metadata: dict) -> None:
    """Record WHICH identifier moved, never its value - that is document data."""
    from app.services.audit import record_audit

    record_audit(
        db,
        action=action,
        user_id=user_id,
        entity_type="person_identity",
        entity_id=identity.id,
        metadata={"person_reference": identity.reference_display, **metadata},
    )
