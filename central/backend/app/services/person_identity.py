"""Stable person UUIDs, explicit identity selection, and merge resolution."""
from __future__ import annotations
import unicodedata
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import PersonIdentity

_ARABIC_DIGITS = {ord("٠") + i: str(i) for i in range(10)}
_ARABIC_DIGITS.update({ord("۰") + i: str(i) for i in range(10)})
MAX_ALIAS_HOPS = 16

class PersonNameRequired(Exception):
    pass

class IdentityNameMismatch(Exception):
    def __init__(self, identity, submitted_name):
        self.identity = identity
        self.existing_name = identity.person_name
        self.submitted_name = submitted_name

def normalize_identifier(value: str | None) -> str | None:
    """Fold case, whitespace and digit scripts in external document/service numbers."""
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", value).translate(_ARABIC_DIGITS)
    text = " ".join(text.split())  # trim + collapse internal whitespace runs
    text = text.upper()
    return text or None


def resolve_identity(db: Session, identity: PersonIdentity | None) -> PersonIdentity | None:
    """Follow merged UUIDs to the surviving person."""
    seen: set[uuid.UUID] = set()
    current = identity
    for _ in range(MAX_ALIAS_HOPS):
        if current is None or current.merged_into_id is None:
            return current
        if current.id in seen:  # corrupt graph; refuse to loop forever
            return current
        seen.add(current.id)
        current = db.get(PersonIdentity, current.merged_into_id)
    return current


def create_identity(db: Session, person_name: str) -> PersonIdentity:
    name = (person_name or "").strip()
    if not name:
        raise PersonNameRequired()
    identity = PersonIdentity(person_name=name)
    db.add(identity)
    db.flush()
    return identity

def identity_for_person(db: Session, person, *, identity_id=None, check_name=True) -> PersonIdentity:
    """Reuse an explicit UUID or scoped service number; never resolve by name."""
    from fastapi import HTTPException
    from app.services.person_identifiers import attach_identifier, find_by_identifier
    name = (getattr(person, "subject_name", None) or getattr(person, "full_name", None) or "").strip()
    branch = getattr(person, "security_branch", None)
    branch = getattr(branch, "value", branch)
    serial = (getattr(person, "military_id", None) or "").strip()
    scoped = bool(serial and branch and branch != "OTHER")
    # Serialize claims on a service number, including when the identifier is not yet present.
    # The transaction-scoped lock closes the select/insert race without merging by name.
    if scoped:
        from sqlalchemy import text
        key = f"MILITARY:{branch}:{normalize_identifier(serial)}"
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
    identity = resolve_identity(db, db.get(PersonIdentity, identity_id)) if identity_id else None
    if identity_id and identity is None:
        raise HTTPException(404, detail="identity_not_found")
    if identity is None and scoped:
        identity = find_by_identifier(db, identifier_type="MILITARY", issuer=branch, value=serial)
        if identity and check_name and identity.person_name.strip() != name:
            raise IdentityNameMismatch(identity, name)
    if identity is None:
        identity = create_identity(db, name)
    if scoped:
        attach_identifier(db, identity=identity, identifier_type="MILITARY", issuer=branch, value=serial)
    return identity

class InvestigatorProfileIncomplete(Exception):
    def __init__(self, missing):
        self.missing = missing

def ensure_investigator_identity(db: Session, profile) -> PersonIdentity:
    if not (profile.full_name or "").strip():
        raise InvestigatorProfileIncomplete(["full_name"])
    identity = identity_for_person(db, profile, identity_id=profile.identity_id, check_name=not profile.identity_id)
    profile.identity_id = identity.id
    return identity

class IdentityMergeConflict(Exception):
    """The merge could not be completed safely (self-merge, cycle, or contention)."""


def _lock_identities(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, PersonIdentity]:
    """Lock rows FOR UPDATE in sorted UUID order.

    The deterministic order is what stops two merges running in opposite directions from
    deadlocking against each other.
    """
    ordered = sorted(set(ids), key=str)
    rows = db.scalars(
        select(PersonIdentity).where(PersonIdentity.id.in_(ordered)).order_by(PersonIdentity.id).with_for_update()
    ).all()
    return {r.id: r for r in rows}


def merge_identities(
    db: Session, source_id: uuid.UUID, target_id: uuid.UUID, *, max_attempts: int = 3
) -> tuple[PersonIdentity, PersonIdentity]:
    """Point `source` at `target`, keeping the source row as an alias. Returns (source, target).

    Merged UUIDs remain resolvable for stale clients.

    Concurrency is the hard part. Resolving terminals, then locking, is not enough: another
    transaction can extend the chain while we wait for the lock, leaving us about to merge
    against a terminal we never locked. So after acquiring the locks we re-resolve, and if
    either terminal moved we start over rather than reaching for another lock out of order.
    """
    for _ in range(max_attempts):
        source = resolve_identity(db, db.get(PersonIdentity, source_id))
        target = resolve_identity(db, db.get(PersonIdentity, target_id))
        if source is None or target is None:
            raise IdentityMergeConflict("identity not found")
        if source.id == target.id:
            raise IdentityMergeConflict("cannot merge an identity into itself")

        _lock_identities(db, [source.id, target.id])

        # Re-resolve now that the rows are held. Expiring first is essential: db.get() serves
        # from the session identity map, so without this the "re-read" would replay the same
        # pre-lock snapshot and happily merge against a terminal that has since moved.
        db.expire_all()
        source_now = resolve_identity(db, db.get(PersonIdentity, source.id))
        target_now = resolve_identity(db, db.get(PersonIdentity, target.id))
        if source_now is None or target_now is None:
            raise IdentityMergeConflict("identity not found")
        if source_now.id != source.id or target_now.id != target.id:
            # A terminal moved while we waited. The locked set is no longer the right one, so
            # start over rather than reaching for another lock out of order. Locks stay held
            # until the transaction ends; PostgreSQL's deadlock detector is the backstop, and
            # it aborts one side deterministically.
            continue

        if source_now.id == target_now.id:
            raise IdentityMergeConflict("cannot merge an identity into itself")
        # Walking from the target must never arrive back at the source.
        if resolve_identity(db, target_now) is not None:
            walker: PersonIdentity | None = target_now
            for _hop in range(MAX_ALIAS_HOPS):
                if walker is None:
                    break
                if walker.id == source_now.id:
                    raise IdentityMergeConflict("merge would create a cycle")
                walker = db.get(PersonIdentity, walker.merged_into_id) if walker.merged_into_id else None

        source_now.merged_into_id = target_now.id
        db.flush()
        return source_now, target_now

    raise IdentityMergeConflict("identity graph kept changing; retry")


def repoint_identity(db: Session, *, source_id: uuid.UUID, target: PersonIdentity) -> dict[str, int | list[str]]:
    """Move everything that pointed at one identity onto another.

    Identity-level on purpose: subjects and speakers are repointed whether or not a voice
    print exists, because two identities can need consolidating while neither owns one.

    Enrollment name snapshots remain unchanged. Stale UUIDs follow the merge alias.
    """
    from app.models import InvestigatorProfile, SessionSpeaker, Subject, VoiceEnrollment

    if source_id == target.id:
        return {"enrollment_ids": [], "subjects": 0, "speakers": 0}

    moved = db.scalars(select(VoiceEnrollment).where(VoiceEnrollment.identity_id == source_id)).all()
    for row in moved:
        row.identity_id = target.id

    subjects = db.scalars(select(Subject).where(Subject.identity_id == source_id)).all()
    for subject in subjects:
        subject.identity_id = target.id

    speakers = db.scalars(select(SessionSpeaker).where(SessionSpeaker.identity_id == source_id)).all()
    for speaker in speakers:
        speaker.identity_id = target.id

    for profile in db.scalars(select(InvestigatorProfile).where(InvestigatorProfile.identity_id == source_id)):
        profile.identity_id = target.id

    db.flush()
    return {
        "enrollment_ids": [str(row.id) for row in moved],
        "subjects": len(subjects),
        "speakers": len(speakers),
    }
