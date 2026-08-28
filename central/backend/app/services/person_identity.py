"""The canonical person registry.

`Subject` records a person's participation in ONE session and is deliberately recreated on
every session save. Nothing therefore ties the same human together across sessions, so two
investigators entering the same person produced two unrelated records — which is how one
person ended up under three reference numbers and made the voice matcher treat his own
embeddings as competing identities.

`person_identities` closes that gap and does nothing else. It owns identity, keyed by a
normalized reference number (الرقم المرجعي), with a database uniqueness guarantee. Subjects
stay session-scoped; speakers and voice prints point at the registry row, which is stable.
"""

from __future__ import annotations

import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import PersonIdentity

# Arabic-Indic (U+0660-0669) and Extended Arabic-Indic (U+06F0-06F9) digits. A reference typed
# on an Arabic keyboard must not become a second identity.
_ARABIC_DIGITS = {ord("٠") + i: str(i) for i in range(10)}
_ARABIC_DIGITS.update({ord("۰") + i: str(i) for i in range(10)})

# How many merged_into_id hops to follow before treating the graph as corrupt.
MAX_ALIAS_HOPS = 16


class PersonNameRequired(Exception):
    """A canonical identity cannot be CREATED without a real name.

    The reference is not a name. Filing someone as "CIV-00000019" produces a row that looks
    named, reads as data, and is indistinguishable from a person actually called that - so the
    gap can never be found again. Refusing is the only honest option: a missing name is a
    validation error, not something to compensate for.
    """

    def __init__(self, reference: str):
        self.reference = reference
        super().__init__(f"a person name is required to create identity {reference}")


class ReferenceNameMismatch(Exception):
    """The reference already belongs to someone else."""

    def __init__(self, reference: str, existing_name: str, submitted_name: str) -> None:
        self.reference = reference
        self.existing_name = existing_name
        self.submitted_name = submitted_name
        super().__init__(f"{reference} is registered to {existing_name!r}, not {submitted_name!r}")


def normalize_reference(reference: str | None) -> str | None:
    """Canonical form of a reference number.

    Deliberately conservative. Case and digit script are folded because they are provably the
    same identifier typed differently; **punctuation and separators are not**. Nothing in the
    domain proves `MIL 4471` and `MIL-4471` are the same person, and wrongly merging two people
    is far worse than failing to merge one.

        mil-4471  ==  MIL-4471  ==  MIL-٤٤٧١
        MIL 4471  !=  MIL-4471
    """
    if reference is None:
        return None
    text = unicodedata.normalize("NFKC", reference).translate(_ARABIC_DIGITS)
    text = " ".join(text.split())  # trim + collapse internal whitespace runs
    text = text.upper()
    return text or None


def resolve_identity(db: Session, identity: PersonIdentity | None) -> PersonIdentity | None:
    """Follow merged_into_id to the surviving identity.

    Merged rows are kept rather than deleted: their UNIQUE(reference_normalized) is what stops
    a stale client from recreating a reference that was merged away.
    """
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


def find_identity(db: Session, reference: str | None) -> PersonIdentity | None:
    """The surviving identity for a reference, or None. Follows aliases."""
    normalized = normalize_reference(reference)
    if not normalized:
        return None
    row = db.scalar(select(PersonIdentity).where(PersonIdentity.reference_normalized == normalized))
    return resolve_identity(db, row)


def get_or_create_identity(db: Session, reference: str | None, person_name: str | None) -> PersonIdentity | None:
    """The canonical identity for this reference, creating it when new.

    Returns None when there is no reference to key on — legitimate for مكتوم القيد or
    غير محدد الهوية, and it simply means the person cannot own a voice print.

    Raises ReferenceNameMismatch when the reference already belongs to a different person.
    The check runs against the TERMINAL identity, never an alias row's historical name.
    """
    normalized = normalize_reference(reference)
    if not normalized:
        return None
    name = (person_name or "").strip()

    existing = find_identity(db, normalized)
    if existing is not None:
        if name and existing.person_name.strip() != name:
            raise ReferenceNameMismatch(existing.reference_display, existing.person_name, name)
        return existing

    # CREATING now, not looking up: a real name is required. Looking an existing identity up
    # without one stays legal above - that is a lookup, and the name is already known.
    if not name:
        raise PersonNameRequired(normalized)

    # Atomic create: the loser of a race reuses the winner's row rather than failing.
    stmt = (
        pg_insert(PersonIdentity)
        .values(
            reference_normalized=normalized,
            reference_display=(reference or "").strip(),
            person_name=name,
        )
        .on_conflict_do_nothing(index_elements=["reference_normalized"])
    )
    db.execute(stmt)
    db.flush()

    created = find_identity(db, normalized)
    if created is None:  # pragma: no cover - only if the row vanished mid-transaction
        raise RuntimeError(f"could not resolve identity for {normalized}")
    if name and created.person_name.strip() != name:
        raise ReferenceNameMismatch(created.reference_display, created.person_name, name)
    return created


class InvestigatorProfileIncomplete(Exception):
    """The profile cannot yield a الرقم المرجعي, so the person cannot be registered.

    Carries the missing field names so the caller can say which ones, rather than making an
    administrator guess what the form wants.
    """

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"investigator profile is missing: {', '.join(missing)}")


def ensure_investigator_identity(db: Session, profile) -> PersonIdentity:
    """Register an investigator as a canonical person, idempotently.

    They run the interview and speak in it, so they are identified and voice-enrolled by the
    same machinery as anyone else - `derive_reference` supplies the military rule unchanged,
    and `get_or_create_identity` owns the registry row.

    Raises InvestigatorProfileIncomplete rather than inventing a reference: a serial without
    its force is not identity evidence, and a guessed branch would merge two real people.
    """
    reference = profile.reference_number or derive_reference(profile)
    if not reference:
        missing = []
        if not _clean(getattr(profile, "military_id", None)):
            missing.append("military_id")
        branch = getattr(profile, "security_branch", None)
        branch_value = getattr(branch, "value", branch)
        if not branch_value or branch_value == "OTHER":
            # OTHER is a catch-all, not a namespace: two "other" forces would collide.
            missing.append("security_branch")
        raise InvestigatorProfileIncomplete(missing or ["military_id", "security_branch"])

    identity = get_or_create_identity(db, reference, (profile.full_name or "").strip() or None)
    if identity is None:  # pragma: no cover - reference is non-empty here
        raise InvestigatorProfileIncomplete(["military_id", "security_branch"])

    profile.reference_number = identity.reference_display
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

    Merged rows are never deleted: retaining the row keeps its UNIQUE(reference_normalized),
    which is the only thing that stops a stale client from recreating a reference that was
    merged away.

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


# ---------------------------------------------------------------------------
# deriving a canonical reference from identifiers the operator already entered
# ---------------------------------------------------------------------------
#
# الرقم المرجعي used to be the only identity field typed free-hand, so the same person
# arrived as MIL-4471, MIL 4471 and 4471 - three identities. Deriving it removes that
# variation at the source.
#
# A derivation is only added when its uniqueness scope is PROVEN. The scopes below were
# confirmed with the domain owner; everything else deliberately returns None, because
# failing to derive is recoverable and merging two real people is not.
#
#   military_id      unique PER FORCE      -> the branch is part of the key
#
# Everything else about a CIVILIAN is descriptive, so civilians no longer derive at all -
# they are ISSUED a reference instead (see allocate_civilian_reference).
#
# رقم السجل in particular is NOT person-unique: it identifies a family civil record, and an
# إخراج قيد lists every member registered under it. Keying on قضاء + رقم السجل gave
# relatives one canonical identity: refused outright when their names differed, silently merged
# when they matched - and naming a son after his grandfather is ordinary here. Passport,
# residency, national id, civil extract and driving licence are keyed by ISSUER, which is free
# text today. UNHCR / UNRWA numbers are trusted EXTERNAL identifiers that help find a person;
# they are no longer the canonical reference themselves.
#
# The asymmetry is deliberate: an extra identity awaiting consolidation is recoverable, two
# humans merged into one biometric identity is not.


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def derive_reference(subject, *, allocate_temporary=None, allocate_civilian=None) -> str | None:
    """The canonical reference for a subject: derived where that is provably safe, else issued.

    `subject` is anything exposing the Subject fields (an ORM row or a SubjectIn).
    `allocate_civilian` issues a CIV reference for a civilian; `allocate_temporary` issues a
    TMP one for a person who has not been classified yet. Both are zero-argument callables, and
    passing neither means "tell me what this derives to, allocate nothing" - which is how the
    override check asks without minting sequence values as a side effect.

    Returns None when nothing can be derived or issued.
    """
    from app.models.enums import PersonType, SecurityBranch

    person_type = getattr(subject, "person_type", None)

    # --- military: the serial is unique within its force, so the force is part of the key.
    military_id = _clean(getattr(subject, "military_id", None))
    branch = getattr(subject, "security_branch", None)
    if military_id and branch is not None:
        branch_value = branch.value if isinstance(branch, SecurityBranch) else str(branch)
        # OTHER is a catch-all, not a namespace: two "other" forces would collide.
        if branch_value and branch_value != SecurityBranch.OTHER.value:
            return normalize_reference(f"MIL-{branch_value}-{military_id}")

    # --- a civilian is ISSUED a reference, never keyed on their civil record. قضاء and
    #     رقم السجل stay on the row as searchable metadata; they identify a family record,
    #     so two relatives sharing them are still two people.
    civilian = person_type == PersonType.CIVILIAN or str(person_type) == "PersonType.CIVILIAN"
    if allocate_civilian is not None and civilian:
        return normalize_reference(allocate_civilian())

    # --- not yet classified: a placeholder so the person can be referred to at all. TMP
    #     guarantees uniqueness, never recognition - two TMPs may be one human, and only an
    #     explicit consolidation may ever say so.
    unknown_person = person_type == PersonType.UNKNOWN or str(person_type) == "PersonType.UNKNOWN"
    if allocate_temporary is not None and unknown_person:
        return normalize_reference(allocate_temporary())

    return None


def allocate_civilian_reference(db: Session) -> str:
    """Issue CIV-NNNNNNNN from a database sequence.

    Every intentionally created civilian gets one, whatever documents they do or do not hold:
    Lebanese or foreign, refugee or resident, documented or not. The reference belongs to the
    PERSON, so it never changes when a passport, a قضاء, an UNHCR number or a name spelling is
    corrected - those are metadata about the person, not the person.

    A sequence, never COUNT(*)+1 or MAX()+1: those race, and two investigators creating
    civilians at the same moment must not receive the same reference.
    """
    from sqlalchemy import text

    value = db.execute(text("SELECT nextval('civilian_person_reference_seq')")).scalar_one()
    return f"CIV-{int(value):08d}"


def allocate_temporary_reference(db: Session) -> str:
    """Issue TMP-YYYY-NNNNNN from a database sequence.

    A sequence, never COUNT(*)+1 or MAX()+1: those race, and two investigators registering
    undocumented people at the same moment must never receive the same reference. The year is
    display only - the sequence runs globally and is never reset, because uniqueness matters
    more than restarting at 000001 each January.
    """
    from datetime import datetime, timezone

    from sqlalchemy import text

    value = db.execute(text("SELECT nextval('tmp_person_reference_seq')")).scalar_one()
    return f"TMP-{datetime.now(timezone.utc).year}-{int(value):06d}"


def repoint_identity(db: Session, *, source_id: uuid.UUID, target: PersonIdentity) -> dict[str, int | list[str]]:
    """Move everything that pointed at one identity onto another.

    Identity-level on purpose: subjects and speakers are repointed whether or not a voice
    print exists, because two identities can need consolidating while neither owns one.

    Current-state rows also take the survivor's reference, so a stale payload cannot keep
    re-submitting one that has been merged away. Enrolment snapshots are left alone - they
    record what was true when the print was taken.
    """
    from app.models import SessionSpeaker, Subject, VoiceEnrollment

    if source_id == target.id:
        return {"enrollment_ids": [], "subjects": 0, "speakers": 0}

    moved = db.scalars(select(VoiceEnrollment).where(VoiceEnrollment.identity_id == source_id)).all()
    for row in moved:
        row.identity_id = target.id

    subjects = db.scalars(select(Subject).where(Subject.identity_id == source_id)).all()
    for subject in subjects:
        subject.identity_id = target.id
        subject.reference_number = target.reference_display

    speakers = db.scalars(select(SessionSpeaker).where(SessionSpeaker.identity_id == source_id)).all()
    for speaker in speakers:
        speaker.identity_id = target.id
        speaker.reference_number = target.reference_display

    db.flush()
    return {
        "enrollment_ids": [str(row.id) for row in moved],
        "subjects": len(subjects),
        "speakers": len(speakers),
    }
