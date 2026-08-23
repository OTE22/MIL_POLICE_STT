"""Investigation sessions: CRUD, list/filter, dashboard."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import client_ip, get_accessible_session, get_current_user, require_permission
from app.db.session import get_db
from app.models import (
    AssignmentRole,
    PersonType,
    AudioRecording,
    AuditAction,
    InvestigationSession,
    InvestigatorProfile,
    LocalProcessingJob,
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
)
from app.services.audit import record_audit

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
                unit=p.unit,
                department=p.department,
                job_title=p.job_title,
                assignment_role=link.assignment_role,
            )
        )
    return out


def _accessible_sessions_stmt(db: Session, user: User):
    stmt = select(InvestigationSession)
    if "investigations.read_all" in user.permission_codes:
        return stmt
    profile_id = db.scalar(select(InvestigatorProfile.id).where(InvestigatorProfile.user_id == user.id))
    conditions = [InvestigationSession.created_by == user.id]
    if profile_id is not None:
        conditions.append(
            InvestigationSession.id.in_(
                select(SessionInvestigator.session_id).where(SessionInvestigator.investigator_id == profile_id)
            )
        )
    return stmt.where(or_(*conditions))


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


def _apply_subjects(db: Session, session: InvestigationSession, items) -> None:
    """Replace the subject list, preserving already uploaded document scans by id."""
    from app.services.document_storage import delete_document_file

    existing_docs: dict[uuid.UUID, SubjectDocument] = {
        doc.id: doc for subject in session.subjects for doc in subject.documents
    }
    kept: set[uuid.UUID] = set()
    new_subjects: list[Subject] = []
    for item in items:
        if _subject_is_empty(item):
            continue
        subject = Subject(**{f: getattr(item, f) for f in SUBJECT_FIELDS})
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
        documents=[_document_out(db, d) for d in subject.documents],
        duplicate_of_sessions=_duplicate_sessions(db, subject),
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DashboardOut:
    base = _accessible_sessions_stmt(db, user)
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
    stmt = _accessible_sessions_stmt(db, user)
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
    _apply_subjects(db, session, body.subjects)
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
        _apply_subjects(db, session, body.subjects)
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
