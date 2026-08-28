"""Investigation sessions: CRUD, list/filter, dashboard."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import accessible_sessions_stmt, client_ip, get_accessible_session, get_current_user, require_permission
from app.db.session import get_db
from app.models import (
    AssignmentRole,
    PersonType,
    AudioRecording,
    AuditAction,
    InvestigationSession,
    InvestigatorProfile,
    LocalProcessingJob,
    PersonIdentity,
    SessionInvestigator,
    SessionStatus,
    Subject,
    SubjectDocument,
    Transcript,
    User,
)
from app.schemas.investigations import (
    MAX_SUPPORTED_SPEAKERS,
    SubjectDocumentOut,
    SubjectOut,
    DashboardOut,
    InvestigationCreate,
    InvestigationListItem,
    InvestigationListOut,
    InvestigationOut,
    InvestigationUpdate,
    InvestigatorBrief,
    RecordingOut,
    SessionPersonOut,
)
from app.services.audit import record_audit
from app.services.person_identity import (
    InvestigatorProfileIncomplete,
    ReferenceNameMismatch,
    ensure_investigator_identity,
    get_or_create_identity,
    normalize_reference,
    resolve_identity,
)

router = APIRouter(prefix="/investigations", tags=["investigations"])

# Status transitions a user may request manually. Processing-related transitions
# are driven by the Local Agent synchronization endpoints.
_MANUAL_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.DRAFT: {SessionStatus.RECORDING, SessionStatus.ARCHIVED},
    SessionStatus.RECORDING: {SessionStatus.DRAFT, SessionStatus.ARCHIVED},
    SessionStatus.PROCESSING: {SessionStatus.ARCHIVED},
    SessionStatus.COMPLETED: {SessionStatus.ARCHIVED, SessionStatus.RECORDING},
    SessionStatus.FAILED: {SessionStatus.RECORDING, SessionStatus.DRAFT, SessionStatus.ARCHIVED},
    SessionStatus.ARCHIVED: {SessionStatus.DRAFT},
}


def _next_session_number(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"INV-{year}-"
    last = db.scalar(
        select(InvestigationSession.session_number)
        .where(InvestigationSession.session_number.like(f"{prefix}%"))
        .order_by(InvestigationSession.session_number.desc())
        .limit(1)
    )
    seq = 1
    if last:
        try:
            seq = int(last.rsplit("-", 1)[1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:05d}"


def _investigator_briefs(session: InvestigationSession) -> list[InvestigatorBrief]:
    out = []
    for link in session.investigators:
        p = link.investigator
        out.append(
            InvestigatorBrief(
                id=p.id,
                full_name=p.full_name,
                rank=p.rank,
                military_id=p.military_id,
                security_branch=p.security_branch,
                # What lets a speaker be bound to this person, and through them a voice print.
                reference_number=p.reference_number,
                unit=p.unit,
                department=p.department,
                job_title=p.job_title,
                assignment_role=link.assignment_role,
            )
        )
    return out


def _lead_name(session: InvestigationSession) -> str | None:
    leads = [l.investigator.full_name for l in session.investigators if l.assignment_role == AssignmentRole.LEAD]
    if leads:
        return leads[0]
    if session.investigators:
        return session.investigators[0].investigator.full_name
    return None


def _duration(db: Session, session_id: uuid.UUID) -> float | None:
    value = db.scalar(
        select(func.max(AudioRecording.duration_seconds)).where(AudioRecording.session_id == session_id)
    )
    return float(value) if value is not None else None


def _list_item(db: Session, s: InvestigationSession) -> InvestigationListItem:
    return InvestigationListItem(
        id=s.id,
        session_number=s.session_number,
        title=s.title,
        location=s.location,
        session_date=s.session_date,
        status=s.status,
        lead_investigator=_lead_name(s),
        duration_seconds=_duration(db, s.id),
        created_at=s.created_at,
    )


def serialize_session(db: Session, s: InvestigationSession) -> InvestigationOut:
    creator = db.get(User, s.created_by)
    creator_name = creator.profile.full_name if creator and creator.profile else (creator.username if creator else None)
    recordings = db.scalars(
        select(AudioRecording).where(AudioRecording.session_id == s.id).order_by(AudioRecording.created_at.desc())
    ).all()
    latest_job = db.scalar(
        select(LocalProcessingJob)
        .where(LocalProcessingJob.session_id == s.id)
        .order_by(LocalProcessingJob.created_at.desc())
        .limit(1)
    )
    has_transcript = db.scalar(select(Transcript.id).where(Transcript.session_id == s.id).limit(1)) is not None
    return InvestigationOut(
        id=s.id,
        session_number=s.session_number,
        title=s.title,
        description=s.description,
        location=s.location,
        session_date=s.session_date,
        start_time=s.start_time,
        end_time=s.end_time,
        status=s.status,
        notes=s.notes,
        expected_speaker_count=s.expected_speaker_count,
        speaker_limit_warning=s.expected_speaker_count > MAX_SUPPORTED_SPEAKERS,
        created_by=s.created_by,
        created_by_name=creator_name,
        created_at=s.created_at,
        updated_at=s.updated_at,
        investigators=_investigator_briefs(s),
        subjects=[_subject_out(db, sub) for sub in s.subjects],
        recordings=[RecordingOut.model_validate(r) for r in recordings],
        latest_job_status=latest_job.status.value if latest_job else None,
        has_transcript=has_transcript,
        duration_seconds=_duration(db, s.id),
    )


def _apply_investigators(db: Session, session: InvestigationSession, items) -> None:
    seen: set[uuid.UUID] = set()
    session.investigators.clear()
    db.flush()
    for item in items:
        if item.investigator_id in seen:
            continue
        profile = db.get(InvestigatorProfile, item.investigator_id)
        if profile is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="investigator_not_found")
        # Assignment is the moment an investigator can actually speak in a recording, so it is
        # where they become a person in the registry - identifiable, and eligible for a voice
        # print, exactly like a subject.
        #
        # A profile predating the requirement cannot yield a reference, and a serial without
        # its force is not identity evidence - inventing one could merge two real people. So
        # such a profile is left UNREGISTERED rather than refused: the creator is auto-assigned
        # as lead, and failing here would stop them creating a session at all. The gap is not
        # silent - the picker lists them disabled, saying which fields are missing.
        try:
            ensure_investigator_identity(db, profile)
        except InvestigatorProfileIncomplete:
            pass
        seen.add(item.investigator_id)
        session.investigators.append(
            SessionInvestigator(investigator_id=profile.id, assignment_role=item.assignment_role)
        )


SUBJECT_FIELDS = (
    "subject_name",
    "reference_number",
    "person_type",
    "military_id",
    "rank",
    "unit",
    "department",
    "security_branch",
    "nationality_code",
    "nationality_name",
    "register_number",
    "place_of_registration",
    "caza_code",
    "is_unregistered",
    "is_undocumented",
    "undocumented_reason",
    "identity_confidence",
    "notes",
)
DOCUMENT_FIELDS = ("document_type", "document_number", "issuing_country", "issue_date", "expiry_date", "notes")


def _subject_is_empty(item) -> bool:  # noqa: ANN001
    """A subject row is only kept when it carries some real information."""
    if item.documents or item.is_undocumented or item.person_type != PersonType.CIVILIAN:
        return False
    return not any(
        getattr(item, f) for f in SUBJECT_FIELDS if f not in ("person_type", "identity_confidence")
    )


# References WE issue rather than derive. They cannot be recomputed from anything on the row,
# so losing the handle to one loses the person - unlike MIL-*, which the identifiers rebuild.
ISSUED_REFERENCE_PREFIXES = ("CIV-", "TMP-")


class ParticipantReferenceRequired(Exception):
    """An existing system-referenced participant could not be reconciled. Nothing mutated.

    Raised when the payload appears to KEEP a participant whose reference WE issued (CIV or
    TMP), but has lost the stable handle to them, while also asking for a new issued
    reference. We cannot tell whether that new row IS the lost person or a genuinely different
    one, and guessing by name, rank, role or position is what splits one human into two
    canonical identities. So it fails closed.
    """


class ReferenceChangeRequired(Exception):
    """One or more people would change canonical identity. Nothing was mutated."""

    def __init__(self, changes: list[dict]) -> None:
        self.changes = changes
        super().__init__("person_reference_change_required")


def _reconcile_participants(session: InvestigationSession, items, removed_keys: set[uuid.UUID]) -> None:
    """Account for every existing participant BEFORE anything is allocated or written.

    Under replacement semantics a participant missing from the payload is ambiguous: the
    operator may have deleted them, or the client may simply have lost the row. Deletion is
    therefore stated explicitly, and only one combination is genuinely unanswerable.

    Rejects, before any mutation:
      * a participant_key that belongs to no participant of THIS session (unknown or foreign);
      * duplicate participant_keys within one payload;
      * removed keys that are also present in the surviving list;
      * a participant holding an ISSUED reference that is neither kept nor explicitly removed,
        while the payload also asks for a fresh issued reference.
    """
    known = {sub.participant_key: sub for sub in session.subjects}

    submitted_keys: list[uuid.UUID] = []
    for item in items:
        key = getattr(item, "participant_key", None)
        if key is None:
            continue
        if key not in known:
            # Never adopt a key we did not issue for this session: it would let a client
            # graft one session's participation state onto another's.
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="unknown_participant_key")
        submitted_keys.append(key)

    if len(submitted_keys) != len(set(submitted_keys)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="duplicate_participant_key")

    unknown_removed = removed_keys - set(known)
    if unknown_removed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="unknown_participant_key")
    if removed_keys & set(submitted_keys):
        # "Delete this person" and "here they are" cannot both be true.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="conflicting_participant_removal")

    # A participant whose reference WE issued is the only one that cannot be recovered from
    # the payload: it derives from nothing, so losing it loses the person.
    unaccounted = [
        sub for key, sub in known.items()
        if key not in submitted_keys
        and key not in removed_keys
        and (sub.reference_number or "").upper().startswith(ISSUED_REFERENCE_PREFIXES)
    ]
    if not unaccounted:
        return

    # Would this save also issue a fresh reference? Then the new row and the lost one are
    # indistinguishable, and only the operator knows which is which.
    wants_new_issue = any(
        getattr(i, "participant_key", None) is None
        and not (getattr(i, "reference_number", None) or "").strip()
        and str(getattr(i, "person_type", "")).endswith(("CIVILIAN", "UNKNOWN"))
        for i in items
    )
    if wants_new_issue:
        raise ParticipantReferenceRequired()


def _resolve_references(
    db: Session, session: InvestigationSession, items, user: User, removed_keys: set[uuid.UUID]
) -> dict[int, str | None]:
    """Decide every subject's canonical reference BEFORE anything is written.

    A session PUT carries many people. Resolving them one at a time would mutate the first and
    only then discover that the third needs review, so this runs as a preflight: derive and
    check everything, and if any person needs an operator decision, raise before a single row
    is touched. The caller's transaction therefore stays all-or-nothing.
    """
    from app.services.person_identity import (
        allocate_civilian_reference,
        allocate_temporary_reference,
        derive_reference,
        find_identity,
        normalize_reference,
    )

    # Existing participants, keyed by the only handle that survives a rebuild. There is no
    # `id` fallback: `Subject.id` is destroyed and re-minted on every save, so falling back to
    # it would reconcile correctly once and then start issuing second references.
    existing_by_key = {sub.participant_key: sub for sub in session.subjects}
    _reconcile_participants(session, items, removed_keys)

    resolved: dict[int, str | None] = {}
    changes: list[dict] = []
    overrides: list[tuple[str, str, str | None]] = []

    for index, item in enumerate(items):
        if _subject_is_empty(item):
            continue

        submitted = (getattr(item, "reference_number", None) or "").strip() or None
        # participant_key ONLY. `Subject.id` is destroyed and re-minted by the rebuild, so
        # falling back to it would silently succeed for one save and then start issuing second
        # references - the exact failure this key exists to remove.
        previous = existing_by_key.get(getattr(item, "participant_key", None))
        previous_reference = (previous.reference_number or "").strip() or None if previous else None

        if submitted:
            # An explicit value always wins - real paperwork does not always fit the rules -
            # but hand-assigning a canonical business key is a privileged act, not part of
            # ordinary data entry.
            #
            # The test is deliberately narrow, because the client round-trips
            # reference_number on EVERY save: a value that matches what the identifiers
            # derive, or what this participant already carries, is a normal save and needs
            # nothing. Only a value that matches neither is an override.
            implied_now = derive_reference(item)
            unchanged = previous_reference and normalize_reference(submitted) == normalize_reference(previous_reference)
            matches_derived = implied_now and normalize_reference(submitted) == normalize_reference(implied_now)
            # Selecting someone who ALREADY exists is not hand-assignment: تحديد الهوية adds
            # a known person to this session by carrying their registry reference. What the
            # permission guards is MINTING a canonical key, not reusing one.
            already_canonical = find_identity(db, submitted) is not None

            # A value in a namespace WE allocate is never hand-assignable, whatever permission
            # the caller holds. CIV-* and TMP-* come from sequences: typing CIV-00009999 would
            # squat a number the sequence has not reached, and the day it does, that person is
            # either refused or silently attached to the squatter. Reusing one that already
            # exists is a different thing - that is selecting a person, and it is allowed.
            if not already_canonical and not unchanged and submitted.upper().startswith(
                ISSUED_REFERENCE_PREFIXES
            ):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, detail="issued_reference_not_assignable"
                )

            if (
                not unchanged
                and not matches_derived
                and not already_canonical
                and "subjects.reference.override" not in user.permission_codes
            ):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, detail="reference_override_not_permitted"
                )
            # The value the identifiers imply must not stay free for someone else to claim:
            # reserve it as an alias so a later investigator entering the same structured
            # person lands on THIS identity instead of creating a second one.
            resolved[id(item)] = submitted
            implied = implied_now
            if implied and normalize_reference(implied) != normalize_reference(submitted):
                overrides.append((implied, submitted, item.subject_name))
            continue

        # Issue a system reference ONLY to a participant we have not issued one to. Subject
        # rows are rebuilt on every save, so allocating again here would mint a second CIV or
        # TMP for the same person every time Save is pressed - the participant_key lookup
        # above is what makes "already issued" knowable.
        issuing = previous_reference is None
        derived = derive_reference(
            item,
            allocate_temporary=(lambda: allocate_temporary_reference(db)) if issuing else None,
            allocate_civilian=(lambda: allocate_civilian_reference(db)) if issuing else None,
        )

        if previous_reference and derived and normalize_reference(derived) != normalize_reference(previous_reference):
            # The structured identifiers now imply a different canonical person. Never switch
            # silently and never quietly mint a second identity - ask the operator, and keep
            # the current reference until they confirm.
            changes.append(
                {
                    # The stable handle, not Subject.id: the row this refers to is destroyed
                    # by the very save the operator is about to confirm.
                    "participant_key": str(previous.participant_key),
                    "subject_index": index,
                    "subject_name": item.subject_name,
                    "current_reference": previous_reference,
                    "derived_reference": derived,
                }
            )
            resolved[id(item)] = previous_reference
        else:
            resolved[id(item)] = derived or previous_reference

    if changes:
        raise ReferenceChangeRequired(changes)

    # Reserve each overridden derived reference against the identity the operator chose.
    for implied, chosen, name in overrides:
        _reserve_derived_alias(db, implied=implied, chosen=chosen, person_name=name)

    return resolved


def _reserve_derived_alias(db: Session, *, implied: str, chosen: str, person_name: str | None) -> None:
    """Point the reference the identifiers imply at the reference the operator chose.

    Without this, investigator A overriding MIL-ARMY-4471 to SPECIAL-4471 would leave
    MIL-ARMY-4471 unclaimed, and investigator B entering the same soldier would create a
    second canonical person.
    """
    from app.services.person_identity import (
        IdentityMergeConflict,
        find_identity,
        get_or_create_identity,
        merge_identities,
    )

    canonical = get_or_create_identity(db, chosen, person_name)
    if canonical is None:
        return

    existing = find_identity(db, implied)
    if existing is not None:
        if existing.id == canonical.id:
            return  # already resolves here
        # The implied reference is someone else's. Never quietly move a real person onto
        # this identity; make the operator resolve it.
        raise ReferenceNameMismatch(implied, existing.person_name, person_name or chosen)

    alias = get_or_create_identity(db, implied, person_name)
    if alias is None or alias.id == canonical.id:
        return
    try:
        merge_identities(db, alias.id, canonical.id)
    except IdentityMergeConflict:
        # A concurrent writer got there first; the reference is claimed either way.
        pass


def _apply_subjects(
    db: Session, session: InvestigationSession, items, user: User,
    removed_keys: set[uuid.UUID] | None = None,
) -> None:
    """Replace the subject list, preserving already uploaded document scans by id."""
    from app.services.document_storage import delete_document_file
    from app.services.person_identifiers import attach_from_documents
    from app.services.person_identity import find_identity

    existing_docs: dict[uuid.UUID, SubjectDocument] = {
        doc.id: doc for subject in session.subjects for doc in subject.documents
    }
    kept: set[uuid.UUID] = set()
    new_subjects: list[Subject] = []

    existing_by_key = {sub.participant_key: sub for sub in session.subjects}
    resolved_references = _resolve_references(db, session, items, user, removed_keys or set())

    for item in items:
        if _subject_is_empty(item):
            continue
        subject = Subject(**{f: getattr(item, f) for f in SUBJECT_FIELDS})
        # Carry the participation handle onto the rebuilt row - regenerating it here would
        # defeat the whole point, since the row itself is deleted and re-inserted every save.
        # A brand-new participant gets one from the column default.
        carried = existing_by_key.get(getattr(item, "participant_key", None))
        if carried is not None:
            subject.participant_key = carried.participant_key
        reference = resolved_references[id(item)]
        # Assert the name only when this participant is NEWLY claiming the reference. Editing
        # someone who already owns it is a rename of a session-local record, not a claim on a
        # stranger, and refusing it meant a name spelling could never be corrected. The guard
        # still fires where it matters: a participant reaching for a reference that is not
        # already theirs must present a matching name.
        #
        # Structural, not a name comparison: it asks whose identity this reference is, not
        # whether two strings look alike.
        already_theirs = (
            carried is not None
            and carried.identity_id is not None
            and (found := find_identity(db, reference)) is not None
            and found.id == carried.identity_id
        )
        identity = get_or_create_identity(db, reference, None if already_theirs else item.subject_name)
        if identity is not None:
            subject.identity_id = identity.id
            # Keyable documents become external identifiers on the person, so the same human
            # is found rather than entered twice next time. A number belonging to someone else
            # refuses the whole save: quietly moving a passport between people is how two
            # records of two humans become one.
            attach_from_documents(db, identity=identity, documents=item.documents, user_id=user.id)
            # A stale client may still submit a reference that has since been merged away.
            # Store the survivor's reference so the row converges instead of re-submitting
            # a dead one forever.
            subject.reference_number = identity.reference_display
        else:
            subject.reference_number = reference
        for doc_in in item.documents:
            if doc_in.id and doc_in.id in existing_docs:
                doc = existing_docs[doc_in.id]
                kept.add(doc.id)
                for f in DOCUMENT_FIELDS:
                    setattr(doc, f, getattr(doc_in, f))
                subject.documents.append(doc)
            else:
                subject.documents.append(SubjectDocument(**{f: getattr(doc_in, f) for f in DOCUMENT_FIELDS}))
        new_subjects.append(subject)

    for doc_id, doc in existing_docs.items():
        if doc_id not in kept and doc.storage_path:
            delete_document_file(doc.storage_path)
    session.subjects = new_subjects


def _document_out(db: Session, doc: SubjectDocument) -> SubjectDocumentOut:
    uploader = db.get(User, doc.uploaded_by) if doc.uploaded_by else None
    name = uploader.profile.full_name if uploader and uploader.profile else (uploader.username if uploader else None)
    return SubjectDocumentOut(
        id=doc.id,
        subject_id=doc.subject_id,
        document_type=doc.document_type,
        document_number=doc.document_number,
        issuing_country=doc.issuing_country,
        issue_date=doc.issue_date,
        expiry_date=doc.expiry_date,
        notes=doc.notes,
        has_file=bool(doc.storage_path),
        original_filename=doc.original_filename,
        mime_type=doc.mime_type,
        size_bytes=doc.size_bytes,
        sha256=doc.sha256,
        uploaded_by=doc.uploaded_by,
        uploaded_by_name=name,
        created_at=doc.created_at,
        is_expired=bool(doc.expiry_date and doc.expiry_date < date.today()),
    )


def _duplicate_sessions(db: Session, subject: Subject) -> list[str]:
    """Warn (never block) when a document number was already recorded in another session."""
    numbers = [d.document_number for d in subject.documents if d.document_number]
    if not numbers:
        return []
    rows = db.execute(
        select(InvestigationSession.session_number)
        .join(Subject, Subject.session_id == InvestigationSession.id)
        .join(SubjectDocument, SubjectDocument.subject_id == Subject.id)
        .where(SubjectDocument.document_number.in_(numbers), Subject.session_id != subject.session_id)
        .distinct()
        .limit(5)
    ).all()
    return [r[0] for r in rows]


def _subject_out(db: Session, subject: Subject) -> SubjectOut:
    return SubjectOut(
        **{f: getattr(subject, f) for f in SUBJECT_FIELDS},
        id=subject.id,
        # Echoed so the form can send it back: it is what identifies this participant across
        # the rebuild, where `id` cannot.
        participant_key=subject.participant_key,
        documents=[_document_out(db, d) for d in subject.documents],
        duplicate_of_sessions=_duplicate_sessions(db, subject),
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DashboardOut:
    base = accessible_sessions_stmt(db, user)
    sub = base.subquery()
    total = db.scalar(select(func.count()).select_from(sub)) or 0
    today = date.today()
    sessions_today = db.scalar(select(func.count()).select_from(sub).where(sub.c.session_date == today)) or 0
    processing = db.scalar(
        select(func.count()).select_from(sub).where(sub.c.status == SessionStatus.PROCESSING.value)
    ) or 0
    completed = db.scalar(
        select(func.count()).select_from(sub).where(sub.c.status == SessionStatus.COMPLETED.value)
    ) or 0
    recent = db.scalars(base.order_by(InvestigationSession.created_at.desc()).limit(8)).all()
    return DashboardOut(
        total_sessions=total,
        sessions_today=sessions_today,
        processing=processing,
        completed=completed,
        recent=[_list_item(db, s) for s in recent],
    )


@router.get("", response_model=InvestigationListOut)
def list_investigations(
    q: str | None = Query(default=None, max_length=200),
    status_filter: SessionStatus | None = Query(default=None, alias="status"),
    investigator_id: uuid.UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvestigationListOut:
    stmt = accessible_sessions_stmt(db, user)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                InvestigationSession.title.ilike(like),
                InvestigationSession.session_number.ilike(like),
                InvestigationSession.location.ilike(like),
            )
        )
    if status_filter:
        stmt = stmt.where(InvestigationSession.status == status_filter)
    if investigator_id:
        stmt = stmt.where(
            InvestigationSession.id.in_(
                select(SessionInvestigator.session_id).where(SessionInvestigator.investigator_id == investigator_id)
            )
        )
    if date_from:
        stmt = stmt.where(InvestigationSession.session_date >= date_from)
    if date_to:
        stmt = stmt.where(InvestigationSession.session_date <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(InvestigationSession.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return InvestigationListOut(items=[_list_item(db, s) for s in rows], total=total, page=page, page_size=page_size)


@router.post("", response_model=InvestigationOut, status_code=status.HTTP_201_CREATED)
def create_investigation(
    body: InvestigationCreate,
    request: Request,
    user: User = Depends(require_permission("investigations.create")),
    db: Session = Depends(get_db),
) -> InvestigationOut:
    number = body.session_number.strip() if body.session_number else _next_session_number(db)
    if db.scalar(select(InvestigationSession.id).where(InvestigationSession.session_number == number)):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="session_number_taken")
    session = InvestigationSession(
        session_number=number,
        title=body.title.strip(),
        description=body.description,
        location=body.location,
        session_date=body.session_date,
        start_time=body.start_time,
        end_time=body.end_time,
        notes=body.notes,
        expected_speaker_count=body.expected_speaker_count,
        status=SessionStatus.DRAFT,
        created_by=user.id,
    )
    db.add(session)
    db.flush()
    investigators = list(body.investigators)
    if not investigators and user.profile is not None:
        # The creator is the lead investigator by default.
        from app.schemas.investigations import InvestigatorAssignmentIn

        investigators = [InvestigatorAssignmentIn(investigator_id=user.profile.id, assignment_role=AssignmentRole.LEAD)]
    _apply_investigators(db, session, investigators)
    _apply_subjects(db, session, body.subjects, user)
    record_audit(
        db,
        action=AuditAction.INVESTIGATION_CREATED,
        user_id=user.id,
        entity_type="investigation_session",
        entity_id=session.id,
        metadata={"session_number": session.session_number, "title": session.title},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(session)
    return serialize_session(db, session)


@router.get("/{session_id}", response_model=InvestigationOut)
def get_investigation(
    session: InvestigationSession = Depends(get_accessible_session), db: Session = Depends(get_db)
) -> InvestigationOut:
    return serialize_session(db, session)


@router.put("/{session_id}", response_model=InvestigationOut)
def update_investigation(
    body: InvestigationUpdate,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("investigations.update")),
    db: Session = Depends(get_db),
) -> InvestigationOut:
    changed: list[str] = []
    for field in ("title", "description", "location", "session_date", "start_time", "end_time", "notes", "expected_speaker_count"):
        value = getattr(body, field)
        if value is not None and value != getattr(session, field):
            setattr(session, field, value.strip() if isinstance(value, str) else value)
            changed.append(field)
    if body.status is not None and body.status != session.status:
        if body.status == SessionStatus.ARCHIVED and "investigations.archive" not in user.permission_codes:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
        if body.status not in _MANUAL_TRANSITIONS.get(session.status, set()):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="invalid_status_transition")
        session.status = body.status
        changed.append("status")
    if body.investigators is not None:
        _apply_investigators(db, session, body.investigators)
        changed.append("investigators")
    if body.subjects is not None:
        _apply_subjects(db, session, body.subjects, user, set(body.removed_participant_keys))
        changed.append("subjects")
    if changed:
        record_audit(
            db,
            action=AuditAction.INVESTIGATION_UPDATED,
            user_id=user.id,
            entity_type="investigation_session",
            entity_id=session.id,
            metadata={"fields": changed, "status": session.status},
            ip_address=client_ip(request),
        )
    db.commit()
    db.refresh(session)
    return serialize_session(db, session)


@router.get("/{session_id}/people", response_model=list[SessionPersonOut])
def list_session_people(
    session: InvestigationSession = Depends(get_accessible_session),
    _: User = Depends(require_permission("transcripts.read")),
    db: Session = Depends(get_db),
) -> list[SessionPersonOut]:
    """Everyone on this session, in one shape - the single source the picker renders from.

    Subjects and investigators are different rows with different columns, and letting the UI
    flatten each one itself is what produced the same human twice under two different names.
    The name here is always the CANONICAL one from `person_identities`, resolved through merges,
    so a renamed or consolidated person reads correctly everywhere at once.

    A row with no reference is still returned, marked `selectable: false`. Omitting it would
    hide a real participant - which is exactly the bug where a subject saved without a name
    vanished from مشاركو الجلسة while still appearing in the registry search.
    """
    out: list[SessionPersonOut] = []

    def canonical(identity_id, fallback_name: str | None, fallback_ref: str | None):
        """The registry's answer where there is one, the row's own copy otherwise."""
        if identity_id is not None:
            identity = resolve_identity(db, db.get(PersonIdentity, identity_id))
            if identity is not None:
                return identity.id, identity.person_name, identity.reference_display
        return None, (fallback_name or "").strip() or None, fallback_ref

    for sub in session.subjects:
        ident_id, name, ref = canonical(sub.identity_id, sub.subject_name, sub.reference_number)
        out.append(
            SessionPersonOut(
                identity_id=ident_id,
                person_name=name or "",
                rank=sub.rank,
                reference_number=ref,
                source="SUBJECT",
                participant_key=sub.participant_key,
                selectable=bool(ref),
                blocked_reason=None if ref else "no_reference",
            )
        )

    for link in session.investigators:
        p = link.investigator
        ident_id, name, ref = canonical(p.identity_id, p.full_name, p.reference_number)
        out.append(
            SessionPersonOut(
                identity_id=ident_id,
                person_name=name or "",
                rank=p.rank,
                reference_number=ref,
                source="INVESTIGATOR",
                participant_key=None,
                selectable=bool(ref),
                # Their profile predates the requirement, so no MIL-<BRANCH>-<serial> derives.
                blocked_reason=None if ref else "profile_incomplete",
            )
        )

    return out
