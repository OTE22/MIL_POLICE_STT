"""Investigation sessions: CRUD, list/filter, dashboard."""

from __future__ import annotations

import uuid
import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, text
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
    ensure_investigator_identity,
    identity_for_person,
    resolve_identity,
)

router = APIRouter(prefix="/investigations", tags=["investigations"])

def _next_session_number(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"INV-{year}-"
    seq = int(db.scalar(text("SELECT COALESCE(MAX(substring(session_number FROM :pattern)::numeric), 0) + 1 "
                         "FROM investigation_sessions WHERE session_number ~ :pattern"),
                    {"pattern": f"^{prefix}([0-9]+)$"}))
    number = f"{prefix}{seq:05d}"
    if len(number) > 64:
        raise HTTPException(409, detail="session_number_sequence_exhausted")
    return number


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
                identity_id=p.identity_id,
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
        select(func.sum(AudioRecording.duration_seconds)).where(AudioRecording.session_id == session_id)
    )
    return float(value) if value is not None else None


def _list_item(db: Session, s: InvestigationSession) -> InvestigationListItem:
    return InvestigationListItem(
        workflow_state=s.workflow_state,
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
    from app.services.workflow import processing_summary
    return InvestigationOut(
        revision=s.revision, workflow_state=s.workflow_state, processing_summary=processing_summary(db, s.id),
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
        subjects=[_subject_out(db, sub) for sub in s.subjects if sub.removed_at is None],
        recordings=[RecordingOut.model_validate(r) for r in recordings],
        latest_job_status=latest_job.status.value if latest_job else None,
        has_transcript=has_transcript,
        duration_seconds=_duration(db, s.id),
    )


def _apply_investigators(db: Session, session: InvestigationSession, items) -> None:
    seen: set[uuid.UUID] = set()
    existing = {link.investigator_id: link for link in session.investigators}
    updated = []
    for item in items:
        if item.investigator_id in seen:
            raise HTTPException(422, detail="duplicate_investigator_assignment")
        profile = db.get(InvestigatorProfile, item.investigator_id)
        if profile is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="investigator_not_found")
        # Assignment is the moment an investigator can actually speak in a recording, so it is
        # where they become a person in the registry - identifiable, and eligible for a voice
        # print, exactly like a subject.
        #
        # A legacy profile without a name remains visible but cannot identify a speaker.
        try:
            ensure_investigator_identity(db, profile)
        except InvestigatorProfileIncomplete:
            pass
        seen.add(item.investigator_id)
        link = existing.get(profile.id) or SessionInvestigator(investigator_id=profile.id)
        link.assignment_role = item.assignment_role
        updated.append(link)
    if sum(i.assignment_role == AssignmentRole.LEAD for i in updated) != 1:
        raise HTTPException(422, detail="exactly_one_lead_required")
    session.investigators = updated


SUBJECT_FIELDS = (
    "statement_details",
    "subject_name",
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


class ParticipantIdentityRequired(Exception):
    """An existing participant was lost without an explicit removal."""

def _reconcile_participants(session, items, removed_keys):
    known = {sub.participant_key for sub in session.subjects}
    submitted = [i.participant_key for i in items if i.participant_key is not None]
    if not set(submitted) <= known or not removed_keys <= known:
        raise HTTPException(400, detail="unknown_participant_key")
    if len(submitted) != len(set(submitted)):
        raise HTTPException(400, detail="duplicate_participant_key")
    if removed_keys & set(submitted):
        raise HTTPException(400, detail="conflicting_participant_removal")
    if known - set(submitted) - removed_keys:
        raise ParticipantIdentityRequired()


def _apply_subjects(
    db: Session, session: InvestigationSession, items, user: User,
    removed_keys: set[uuid.UUID] | None = None,
) -> None:
    """Update stable participants; explicit removals retain rows and all evidence."""
    from app.services.person_identifiers import attach_from_documents
    existing = {sub.participant_key: sub for sub in session.subjects if sub.removed_at is None}
    _reconcile_participants(session, items, removed_keys or set())
    for key in removed_keys or set():
        existing[key].removed_at = datetime.now(timezone.utc)
    for item in items:
        if _subject_is_empty(item):
            continue
        carried = existing.get(item.participant_key)
        previous_id = carried.identity_id if carried else None
        if previous_id and item.identity_id:
            previous = resolve_identity(db, db.get(PersonIdentity, previous_id))
            proposed = resolve_identity(db, db.get(PersonIdentity, item.identity_id))
            if proposed is None or previous is None or previous.id != proposed.id:
                raise HTTPException(409, detail="participant_identity_change_not_permitted")
        identity = identity_for_person(db, item, identity_id=previous_id or item.identity_id,
                                       check_name=not bool(previous_id))
        subject = carried or Subject()
        for field in SUBJECT_FIELDS:
            if carried is None or field in item.model_fields_set:
                setattr(subject, field, getattr(item, field))
        subject.identity_id = identity.id
        docs = {doc.id: doc for doc in subject.documents if doc.removed_at is None}
        submitted = {d.id for d in item.documents if d.id}
        removed = set(item.removed_document_ids)
        if not (submitted | removed) <= docs.keys() or submitted & removed:
            raise HTTPException(422, detail="invalid_document_reference")
        if docs.keys() - submitted - removed:
            raise HTTPException(409, detail="explicit_document_removal_required")
        for doc_id in removed:
            docs[doc_id].removed_at = datetime.now(timezone.utc)
        for doc_in in item.documents:
            doc = docs.get(doc_in.id) if doc_in.id else None
            new_document = doc is None
            if doc is None:
                doc = SubjectDocument()
                subject.documents.append(doc)
            for field in DOCUMENT_FIELDS:
                if new_document or field in doc_in.model_fields_set:
                    setattr(doc, field, getattr(doc_in, field))
            if doc.issue_date and doc.expiry_date and doc.expiry_date < doc.issue_date:
                raise HTTPException(422, detail="document_expiry_before_issue")
        attach_from_documents(db, identity=identity, documents=item.documents, user_id=user.id)
        if carried is None:
            session.subjects.append(subject)


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
        file_versions=[{k: v for k, v in version.items() if k != "storage_path"} for version in doc.file_versions or []],
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
    identity = resolve_identity(db, db.get(PersonIdentity, subject.identity_id)) if subject.identity_id else None
    return SubjectOut(
        identity_name=identity.person_name if identity else None,
        **{f: getattr(subject, f) for f in SUBJECT_FIELDS},
        id=subject.id,
        # Echoed so the form can send it back: it is what identifies this participant across
        # edits; the database ID is preserved as well.
        participant_key=subject.participant_key,
        identity_id=subject.identity_id,
        documents=[_document_out(db, d) for d in subject.documents if d.removed_at is None],
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
        select(func.count()).select_from(sub).where(sub.c.workflow_state == "CLOSED")
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
    workflow_state: str | None = Query(default=None, pattern="^(DRAFT|IN_PROGRESS|AWAITING_REVIEW|REVIEWED|CLOSED|ARCHIVED)$"),
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
    if workflow_state:
        stmt = stmt.where(InvestigationSession.workflow_state == workflow_state)
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
    if body.start_time is not None and body.end_time is not None and body.end_time < body.start_time:
        raise HTTPException(422, detail="session_time_range_invalid")
    # Serialize automatic and explicit identifiers before checking their unique owner.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('investigation-session-number', 0))"))
    number = body.session_number.strip() if body.session_number else _next_session_number(db)
    if not number:
        raise HTTPException(422, detail="session_number_required")
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
    session = db.scalar(select(InvestigationSession).where(InvestigationSession.id == session.id)
                        .with_for_update().execution_options(populate_existing=True))
    if body.expected_revision != session.revision:
        raise HTTPException(409, detail="investigation_changed")
    if session.workflow_state in {"CLOSED", "ARCHIVED"}:
        raise HTTPException(409, detail="reopen_investigation_before_editing")
    start = body.start_time if "start_time" in body.model_fields_set else session.start_time
    end = body.end_time if "end_time" in body.model_fields_set else session.end_time
    if start is not None and end is not None and end < start:
        raise HTTPException(422, detail="session_time_range_invalid")
    before = json.loads(serialize_session(db, session).model_dump_json())
    for field in ("title", "description", "location", "session_date", "start_time", "end_time", "notes", "expected_speaker_count"):
        value = getattr(body, field)
        if field in body.model_fields_set and value != getattr(session, field):
            if field in {"title", "expected_speaker_count"} and value is None:
                raise HTTPException(422, detail="required_field_cannot_be_null")
            setattr(session, field, value.strip() if isinstance(value, str) else value)
            changed.append(field)
    if body.status is not None:
        raise HTTPException(409, detail="use_investigation_workflow_endpoint")
    if body.investigators is not None:
        _apply_investigators(db, session, body.investigators)
        changed.append("investigators")
    if body.subjects is not None:
        _apply_subjects(db, session, body.subjects, user, set(body.removed_participant_keys))
        changed.append("subjects")
    if changed:
        session.revision += 1
        if session.workflow_state in {"REVIEWED", "AWAITING_REVIEW"}:
            session.workflow_state = "IN_PROGRESS"
        # New participant/document UUIDs and server timestamps must exist in the audit
        # snapshot. A failed flush rolls back all changes without touching evidence files.
        db.flush()
        record_audit(
            db,
            action=AuditAction.INVESTIGATION_UPDATED,
            user_id=user.id,
            entity_type="investigation_session",
            entity_id=session.id,
            metadata={"fields": changed, "status": session.status, "before": before, "revision": session.revision,
                      "after": json.loads(serialize_session(db, session).model_dump_json())},
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

    A row with no identity is still returned, marked `selectable: false`. Omitting it would
    hide a real participant - which is exactly the bug where a subject saved without a name
    vanished from مشاركو الجلسة while still appearing in the registry search.
    """
    out: list[SessionPersonOut] = []

    def canonical(identity_id, fallback_name: str | None):
        """The registry's answer where there is one, the row's own copy otherwise."""
        if identity_id is not None:
            identity = resolve_identity(db, db.get(PersonIdentity, identity_id))
            if identity is not None:
                return identity.id, identity.person_name
        return None, (fallback_name or "").strip() or None

    for sub in session.subjects:
        ident_id, name = canonical(sub.identity_id, sub.subject_name)
        out.append(
            SessionPersonOut(
                identity_id=ident_id,
                person_name=name or "",
                rank=sub.rank,
                source="SUBJECT",
                participant_key=sub.participant_key,
                selectable=bool(ident_id),
                blocked_reason=None if ident_id else "no_identity",
            )
        )

    for link in session.investigators:
        p = link.investigator
        ident_id, name = canonical(p.identity_id, p.full_name)
        out.append(
            SessionPersonOut(
                identity_id=ident_id,
                person_name=name or "",
                rank=p.rank,
                source="INVESTIGATOR",
                participant_key=None,
                selectable=bool(ident_id),
                # Their profile predates the requirement, so no MIL-<BRANCH>-<serial> derives.
                blocked_reason=None if ident_id else "profile_incomplete",
            )
        )

    return out


from pydantic import BaseModel, Field
from typing import Literal

class WorkflowUpdate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    expected_revision: int = Field(ge=0)
    state: Literal["DRAFT", "IN_PROGRESS", "AWAITING_REVIEW", "REVIEWED", "CLOSED", "ARCHIVED"]
    reason: str = Field(min_length=3, max_length=2000)

@router.post("/{session_id}/workflow", response_model=InvestigationOut)
def update_workflow(body: WorkflowUpdate, request: Request,
                    session: InvestigationSession = Depends(get_accessible_session),
                    user: User = Depends(require_permission("investigations.update")), db: Session = Depends(get_db)):
    from app.services.workflow import transition
    session = db.scalar(select(InvestigationSession).where(InvestigationSession.id == session.id)
                        .with_for_update().execution_options(populate_existing=True))
    if body.expected_revision != session.revision:
        raise HTTPException(409, detail="investigation_changed")
    previous = session.workflow_state
    transition(db, session, body.state, user)
    record_audit(db, action=AuditAction.INVESTIGATION_UPDATED, user_id=user.id,
                 entity_type="investigation_session", entity_id=session.id,
                 metadata={"workflow_before": previous, "workflow_after": body.state,
                           "reason": body.reason, "revision": session.revision}, ip_address=client_ip(request))
    db.commit()
    db.refresh(session)
    return serialize_session(db, session)
