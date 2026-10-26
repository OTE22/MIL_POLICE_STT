"""Explicit record, review, insert/dismiss workflow for report dictation."""
import copy
import uuid
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.reports import _require_draft, _guard_editable, _lock_session, _check_token, _audit, TokenInput
from app.core.deps import get_accessible_session, require_permission
from app.core.processing_tokens import issue_processing_token, ALLOWED_ACTION
from app.db.session import get_db
from app.models import AudioRecording, LocalProcessingJob, InvestigationSession, User, JobStatus, RecordingUploadStatus, AuditAction
from app.schemas.processing import ProcessingTokenRequest, ProcessingTokenOut
from app.schemas.report_html import HtmlReportUpdate
from app.services import report_html, report_dictation as service
from app.services.participant_requirements import require_ready
from app.services.storage import validate_declared, sanitize_filename, InvalidAudioError
from app.services.workflow import guard_mutation

router = APIRouter(tags=["report-dictation"])


class StartInput(ProcessingTokenRequest):
    expected_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    block_id: uuid.UUID
    field: str = Field(min_length=1, max_length=50)


class AcceptInput(TokenInput):
    text: str = Field(min_length=1, max_length=20000)
    mode: Literal["APPEND", "REPLACE"] = "APPEND"
    expected_text_token: str = Field(pattern=r"^[a-f0-9]{64}$")


class DismissInput(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("dictation_dismiss_reason_required")
        return value.strip()


def _recording(db, session, recording_id):
    row = db.scalar(select(AudioRecording).where(AudioRecording.id == recording_id,
        AudioRecording.session_id == session.id, AudioRecording.purpose == "REPORT_DICTATION").with_for_update())
    if row is None:
        raise HTTPException(404, detail="dictation_not_found")
    return row


@router.get("/investigations/{session_id}/report/dictations")
def list_dictations(session: InvestigationSession = Depends(get_accessible_session),
                    user: User = Depends(require_permission("reports.read", "reports.generate")), db: Session = Depends(get_db)):
    draft = _require_draft(db, session)
    document = report_html.document_for(draft)
    result = []
    for row in service.rows(db, session.id):
        context = row.report_context or {}
        if context.get("draft_id") != str(draft.id):
            continue
        current_text = None
        try:
            _, values, key = service.target(document, context["block_id"], context["field"])
            current_text = values.get(key, "")
        except HTTPException:
            pass
        job = db.scalar(select(LocalProcessingJob).where(LocalProcessingJob.recording_id == row.id)
                        .order_by(LocalProcessingJob.created_at.desc()).limit(1))
        result.append({"id": str(row.id), "block_id": context["block_id"], "field": context["field"],
            "status": context["status"], "machine_text": context.get("machine_text", ""),
            "author": str(row.created_by), "audio_ready": row.upload_status == RecordingUploadStatus.UPLOADED,
            "current_text": current_text, "text_token": service.text_token(current_text) if current_text is not None else None,
            "destination_changed": current_text is None or service.text_token(current_text) != context["initial_text_token"],
            "job_id": str(job.id) if job else None, "job_status": job.status.value if job else None,
            "error": job.error_message if job else None})
    return result


@router.post("/investigations/{session_id}/report/dictations", response_model=ProcessingTokenOut)
def start(body: StartInput, request: Request, session: InvestigationSession = Depends(get_accessible_session),
          user: User = Depends(require_permission("reports.generate")), db: Session = Depends(get_db)):
    session = _lock_session(db, session)
    service.require_investigator(session, user)
    guard_mutation(session)
    require_ready(session)
    draft = _require_draft(db, session)
    _guard_editable(draft)
    _check_token(body, draft)
    _, values, key = service.target(report_html.document_for(draft), body.block_id, body.field)
    try:
        validate_declared(body.original_filename, body.mime_type, body.size_bytes)
    except InvalidAudioError as exc:
        raise HTTPException(400, detail=exc.code) from exc
    if body.recording_id:
        row = _recording(db, session, body.recording_id)
        ctx = row.report_context
        if row.created_by != user.id or ctx["draft_id"] != str(draft.id) or ctx["block_id"] != str(body.block_id) or ctx["field"] != body.field or ctx["status"] != "PENDING":
            raise HTTPException(409, detail="dictation_retry_mismatch")
        if (row.original_filename != sanitize_filename(body.original_filename) or row.size_bytes != body.size_bytes
            or row.mime_type != body.mime_type.split(";")[0].strip().lower()):
            raise HTTPException(409, detail="recording_retry_metadata_mismatch")
        if db.scalar(select(LocalProcessingJob.id).where(LocalProcessingJob.recording_id == row.id,
                LocalProcessingJob.status.in_([JobStatus.REQUESTED, JobStatus.ACCEPTED, JobStatus.PROCESSING])).limit(1)):
            raise HTTPException(409, detail="recording_already_processing")
    else:
        row = AudioRecording(session_id=session.id, original_filename=sanitize_filename(body.original_filename),
            mime_type=body.mime_type.split(";")[0].strip().lower(), size_bytes=body.size_bytes, source=body.source,
            upload_status=RecordingUploadStatus.PENDING, created_by=user.id, purpose="REPORT_DICTATION",
            report_context={"draft_id": str(draft.id), "block_id": str(body.block_id), "field": body.field,
                "initial_text_token": service.text_token(values.get(key, "")), "status": "PENDING"})
        db.add(row)
        db.flush()
    job_id = uuid.uuid4()
    issued = issue_processing_token(job_id=job_id, session_id=session.id, recording_id=row.id,
        user_id=user.id, session_number=session.session_number, purpose="REPORT_DICTATION")
    db.add(LocalProcessingJob(id=job_id, session_id=session.id, recording_id=row.id, requested_by=user.id,
        status=JobStatus.REQUESTED, token_nonce=issued.nonce, token_issued_at=issued.issued_at,
        token_accept_by=issued.accept_by, token_expires_at=issued.expires_at))
    _audit(db, request, user, AuditAction.LOCAL_PROCESSING_REQUESTED, session, row.id,
           purpose="REPORT_DICTATION", block_id=str(body.block_id), field=body.field)
    db.commit()
    return ProcessingTokenOut(job_id=job_id, recording_id=row.id, session_id=session.id,
        processing_token=issued.token, accept_by=issued.accept_by, expires_at=issued.expires_at,
        allowed_action=ALLOWED_ACTION, speaker_limit_warning=False)


@router.post("/investigations/{session_id}/report/dictations/{recording_id}/accept")
def accept(recording_id: uuid.UUID, body: AcceptInput, request: Request,
           session: InvestigationSession = Depends(get_accessible_session),
           user: User = Depends(require_permission("reports.generate")), db: Session = Depends(get_db)):
    session = _lock_session(db, session)
    service.require_investigator(session, user)
    guard_mutation(session)
    require_ready(session)
    draft = _require_draft(db, session)
    _guard_editable(draft)
    row = _recording(db, session, recording_id)
    context = dict(row.report_context)
    if context["draft_id"] != str(draft.id) or row.created_by != user.id:
        raise HTTPException(403, detail="dictation_author_required")
    if context["status"] == "ACCEPTED":
        if context["accepted_text"] == body.text and context["mode"] == body.mode:
            return report_html.state_for(draft, db, session)
        raise HTTPException(409, detail="dictation_already_accepted")
    _check_token(body, draft)
    if context["status"] != "READY" or not context.get("machine_text"):
        raise HTTPException(409, detail="dictation_not_ready")
    if row.upload_status != RecordingUploadStatus.UPLOADED or not row.sha256:
        raise HTTPException(409, detail="dictation_audio_missing")
    document = copy.deepcopy(report_html.document_for(draft))
    block, values, key = service.target(document, context["block_id"], context["field"])
    if service.text_token(values.get(key, "")) != body.expected_text_token:
        raise HTTPException(409, detail="dictation_destination_changed")
    if not body.text.strip():
        raise HTTPException(422, detail="dictation_empty_text")
    before = values.get(key, "")
    values[key] = ((before.rstrip() + "\n") if before.strip() and body.mode == "APPEND" else "") + body.text.strip()
    if context["field"] == "proposals":
        block["proposal_mode"] = "TEXT"
    # Validate accepted prose with the same limits/bidi rules as typed report content.
    from app.services.report_html import editable_document
    try:
        validated = HtmlReportUpdate(expected_token=body.expected_token, document=editable_document(document))
        document = report_html.prepare_document(validated, draft, session, db, populate_untouched=False)
    except ValueError as exc:
        raise HTTPException(422, detail="dictation_invalid_text") from exc
    block = next(b for b in document["blocks"] if b["id"] == context["block_id"])
    now = datetime.now(timezone.utc).isoformat()
    block["authorship"] = {**block.get("authorship", {}), "updated_by": str(user.id), "updated_at": now}
    block["dictation_sources"] = [*block.get("dictation_sources", []), str(row.id)]
    context.update(status="ACCEPTED", accepted_text=body.text, mode=body.mode, accepted_by=str(user.id), accepted_at=now)
    row.report_context = context
    draft.official_form = {**draft.official_form, "html_report": document}
    draft.revision += 1
    draft.updated_by = user.id
    _audit(db, request, user, AuditAction.REPORT_DRAFT_UPDATED, session, draft.id,
           dictation_id=str(row.id), field=context["field"], mode=body.mode, before=before, after=values[key])
    db.commit()
    return report_html.state_for(draft, db, session)


@router.post("/investigations/{session_id}/report/dictations/{recording_id}/dismiss")
def dismiss(recording_id: uuid.UUID, body: DismissInput, request: Request,
            session: InvestigationSession = Depends(get_accessible_session),
            user: User = Depends(require_permission("reports.generate")), db: Session = Depends(get_db)):
    session = _lock_session(db, session)
    service.require_investigator(session, user)
    guard_mutation(session)
    row = _recording(db, session, recording_id)
    if row.report_context["status"] == "ACCEPTED":
        raise HTTPException(409, detail="dictation_already_accepted")
    if row.created_by != user.id and not any(i.assignment_role.value == "LEAD" and i.investigator.user_id == user.id for i in session.investigators):
        raise HTTPException(403, detail="dictation_author_required")
    row.report_context = {**row.report_context, "status": "DISMISSED", "dismiss_reason": body.reason,
        "dismissed_by": str(user.id), "dismissed_at": datetime.now(timezone.utc).isoformat()}
    _audit(db, request, user, AuditAction.REPORT_DRAFT_UPDATED, session, row.id,
           purpose="REPORT_DICTATION", decision="DISMISSED", reason=body.reason)
    db.commit()
    return {"status": "DISMISSED"}
