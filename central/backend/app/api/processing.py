"""Local processing authorization + synchronization endpoints.

Two different callers use this router:

* the logged-in frontend (user JWT) to request a processing token / query jobs;
* the Local AI Agent (processing token, ES256) to report state, submit the
  result and upload the original audio.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import client_ip, get_accessible_session, get_current_user, require_permission
from app.core.processing_tokens import (
    ALLOWED_ACTION,
    ProcessingTokenError,
    issue_processing_token,
    load_public_key,
    verify_processing_token,
)
from app.db.session import get_db
from app.models import (
    AudioRecording,
    AuditAction,
    InvestigationSession,
    JobStatus,
    LocalProcessingJob,
    RecordingUploadStatus,
    SessionSpeaker,
    SessionStatus,
    SpeakerRole,
    Transcript,
    TranscriptSegment,
    TranscriptStatus,
    User,
    Workstation,
    WorkstationStatus,
)
from app.schemas.investigations import MAX_SUPPORTED_SPEAKERS
from app.schemas.processing import (
    JobOut,
    JobStateReport,
    ProcessingResultIn,
    ProcessingResultOut,
    ProcessingTokenOut,
    ProcessingTokenRequest,
    PublicKeyOut,
    WorkstationInfo,
)
from app.services.audit import record_audit
from app.services.storage import InvalidAudioError, store_upload, validate_declared

router = APIRouter(tags=["local-processing"])
_bearer = HTTPBearer(auto_error=False)

_STATE_AUDIT: dict[str, AuditAction] = {
    "RECEIVING_AUDIO": AuditAction.LOCAL_PROCESSING_STARTED,
    "DIARIZING": AuditAction.DIARIZATION_STARTED,
    "TRANSCRIBING": AuditAction.TRANSCRIPTION_STARTED,
    "FAILED": AuditAction.LOCAL_PROCESSING_FAILED,
    "CANCELLED": AuditAction.LOCAL_PROCESSING_CANCELLED,
}
_STAGE_FAILED_AUDIT = {
    "DIARIZING": AuditAction.DIARIZATION_FAILED,
    "TRANSCRIBING": AuditAction.TRANSCRIPTION_FAILED,
}
_STAGE_COMPLETED_AUDIT = {
    "DIARIZING": AuditAction.DIARIZATION_COMPLETED,
    "TRANSCRIBING": AuditAction.TRANSCRIPTION_COMPLETED,
}
_TERMINAL = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


def _job_out(job: LocalProcessingJob) -> JobOut:
    return JobOut(
        id=job.id,
        session_id=job.session_id,
        recording_id=job.recording_id,
        status=job.status,
        agent_state=job.agent_state,
        failure_stage=job.failure_stage,
        error_message=job.error_message,
        idempotency_key=job.idempotency_key,
        token_accept_by=job.token_accept_by,
        token_expires_at=job.token_expires_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        workstation_agent_id=job.workstation.agent_id if job.workstation else None,
    )


# ------------------------------------------------------------------ frontend side


@router.get("/local-processing/public-key", response_model=PublicKeyOut)
def public_key() -> PublicKeyOut:
    """Public verification key. Safe to publish; used by agents at provisioning time."""
    settings = get_settings()
    return PublicKeyOut(
        algorithm="ES256",
        key_id="central-es256-v1",
        issuer=settings.processing_token_issuer,
        audience=settings.processing_token_audience,
        public_key_pem=load_public_key(),
    )


@router.post("/investigations/{session_id}/local-processing-token", response_model=ProcessingTokenOut)
def create_processing_token(
    body: ProcessingTokenRequest,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("processing.request")),
    db: Session = Depends(get_db),
) -> ProcessingTokenOut:
    if session.status == SessionStatus.ARCHIVED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="session_archived")
    try:
        validate_declared(body.original_filename, body.mime_type, body.size_bytes)
    except InvalidAudioError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from exc

    from app.services.storage import sanitize_filename

    recording = AudioRecording(
        session_id=session.id,
        original_filename=sanitize_filename(body.original_filename),
        mime_type=body.mime_type.split(";")[0].strip().lower(),
        size_bytes=body.size_bytes,
        source=body.source,
        upload_status=RecordingUploadStatus.PENDING,
        created_by=user.id,
    )
    db.add(recording)
    db.flush()
    job_id = uuid.uuid4()
    issued = issue_processing_token(
        job_id=job_id,
        session_id=session.id,
        recording_id=recording.id,
        user_id=user.id,
        session_number=session.session_number,
    )
    job = LocalProcessingJob(
        id=job_id,
        session_id=session.id,
        recording_id=recording.id,
        requested_by=user.id,
        status=JobStatus.REQUESTED,
        token_nonce=issued.nonce,
        token_issued_at=issued.issued_at,
        token_accept_by=issued.accept_by,
        token_expires_at=issued.expires_at,
    )
    db.add(job)
    session.status = SessionStatus.PROCESSING
    ip = client_ip(request)
    record_audit(
        db,
        action=AuditAction.RECORDING_CREATED,
        user_id=user.id,
        entity_type="audio_recording",
        entity_id=recording.id,
        metadata={"session_id": session.id, "filename": recording.original_filename, "source": body.source},
        ip_address=ip,
    )
    record_audit(
        db,
        action=AuditAction.LOCAL_PROCESSING_REQUESTED,
        user_id=user.id,
        entity_type="local_processing_job",
        entity_id=job.id,
        metadata={"session_id": session.id, "recording_id": recording.id, "accept_by": issued.accept_by.isoformat()},
        ip_address=ip,
    )
    db.commit()
    return ProcessingTokenOut(
        job_id=job.id,
        recording_id=recording.id,
        session_id=session.id,
        processing_token=issued.token,
        accept_by=issued.accept_by,
        expires_at=issued.expires_at,
        allowed_action=ALLOWED_ACTION,
        speaker_limit_warning=session.expected_speaker_count > MAX_SUPPORTED_SPEAKERS,
    )


@router.get("/investigations/{session_id}/jobs", response_model=list[JobOut])
def list_session_jobs(
    session: InvestigationSession = Depends(get_accessible_session),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[JobOut]:
    jobs = db.scalars(
        select(LocalProcessingJob)
        .where(LocalProcessingJob.session_id == session.id)
        .order_by(LocalProcessingJob.created_at.desc())
    ).all()
    return [_job_out(j) for j in jobs]


@router.post("/local-processing/{job_id}/cancel", response_model=JobOut)
def cancel_job_by_user(
    job_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("processing.request")),
    db: Session = Depends(get_db),
) -> JobOut:
    job = db.get(LocalProcessingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job_not_found")
    session = get_accessible_session(job.session_id, user, db)
    if job.status in _TERMINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="job_finished")
    job.status = JobStatus.CANCELLED
    job.agent_state = "CANCELLED"
    job.completed_at = datetime.now(timezone.utc)
    if session.status == SessionStatus.PROCESSING:
        session.status = SessionStatus.RECORDING
    record_audit(
        db,
        action=AuditAction.LOCAL_PROCESSING_CANCELLED,
        user_id=user.id,
        entity_type="local_processing_job",
        entity_id=job.id,
        metadata={"by_user": True, "session_id": job.session_id},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(job)
    return _job_out(job)


# --------------------------------------------------------------- agent side


def get_agent_job(
    job_id: uuid.UUID,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> tuple[LocalProcessingJob, dict]:
    """Authenticate the Local Agent with the processing token and load the job."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="processing_token_missing")
    try:
        claims = verify_processing_token(credentials.credentials)
    except ProcessingTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=f"processing_token_{exc}") from exc
    if claims.get("job_id") != str(job_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="processing_token_job_mismatch")
    job = db.get(LocalProcessingJob, job_id)
    if job is None or job.token_nonce != claims.get("jti"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job_not_found")
    return job, claims


def _upsert_workstation(db: Session, info: WorkstationInfo | None, user_id: uuid.UUID | None) -> Workstation | None:
    if info is None:
        return None
    ws = db.scalar(select(Workstation).where(Workstation.agent_id == info.agent_id))
    created = ws is None
    if ws is None:
        ws = Workstation(agent_id=info.agent_id, registered_by=user_id)
        db.add(ws)
    for field in (
        "device_name",
        "agent_version",
        "stt_provider",
        "stt_model",
        "stt_model_revision",
        "diarization_provider",
        "diarization_model",
        "diarization_model_revision",
        "processing_device",
        "gpu_name",
    ):
        value = getattr(info, field)
        if value is not None:
            setattr(ws, field, value)
    ready = (info.stt_ready is not False) and (info.diarization_ready is not False)
    ws.status = WorkstationStatus.ONLINE if ready else WorkstationStatus.DEGRADED
    ws.last_seen_at = datetime.now(timezone.utc)
    db.flush()
    if created:
        record_audit(
            db,
            action=AuditAction.WORKSTATION_REGISTERED,
            user_id=user_id,
            entity_type="workstation",
            entity_id=ws.id,
            metadata={"agent_id": ws.agent_id, "device_name": ws.device_name},
        )
    return ws


@router.post("/local-processing/{job_id}/state", response_model=JobOut)
def report_job_state(
    body: JobStateReport,
    auth: tuple[LocalProcessingJob, dict] = Depends(get_agent_job),
    db: Session = Depends(get_db),
) -> JobOut:
    job, claims = auth
    user_id = uuid.UUID(claims["user_id"])
    if job.status in _TERMINAL and body.state not in ("COMPLETED",):
        # Terminal jobs do not regress. Cancellation by user wins.
        return _job_out(job)
    previous_state = job.agent_state
    ws = _upsert_workstation(db, body.workstation, user_id)
    if ws is not None:
        job.workstation_id = ws.id
    job.agent_state = body.state
    if body.state in ("CREATED", "RECEIVING_AUDIO"):
        job.status = JobStatus.ACCEPTED
    elif body.state in ("PREPROCESSING", "DIARIZING", "TRANSCRIBING", "FINALIZING", "SYNCING"):
        job.status = JobStatus.PROCESSING
    elif body.state == "FAILED":
        job.status = JobStatus.FAILED
        job.failure_stage = body.failure_stage or previous_state
        job.error_message = (body.message or "")[:2000]
        job.completed_at = datetime.now(timezone.utc)
        session = db.get(InvestigationSession, job.session_id)
        if session is not None and session.status == SessionStatus.PROCESSING:
            session.status = SessionStatus.FAILED
    elif body.state == "CANCELLED":
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(timezone.utc)
        session = db.get(InvestigationSession, job.session_id)
        if session is not None and session.status == SessionStatus.PROCESSING:
            session.status = SessionStatus.RECORDING
    metadata = {"state": body.state, "progress": body.progress, "previous": previous_state, "session_id": job.session_id}
    # Stage completion events are derived from transitions.
    if previous_state in _STAGE_COMPLETED_AUDIT and body.state not in ("FAILED", "CANCELLED") and body.state != previous_state:
        record_audit(db, action=_STAGE_COMPLETED_AUDIT[previous_state], user_id=user_id, entity_type="local_processing_job", entity_id=job.id, metadata=metadata)
    if body.state == "FAILED" and (body.failure_stage or previous_state) in _STAGE_FAILED_AUDIT:
        record_audit(db, action=_STAGE_FAILED_AUDIT[body.failure_stage or previous_state], user_id=user_id, entity_type="local_processing_job", entity_id=job.id, metadata={**metadata, "message": (body.message or "")[:500]})
    if body.state in _STATE_AUDIT and body.state != previous_state:
        record_audit(db, action=_STATE_AUDIT[body.state], user_id=user_id, entity_type="local_processing_job", entity_id=job.id, metadata={**metadata, "message": (body.message or "")[:500]})
    db.commit()
    db.refresh(job)
    return _job_out(job)


@router.post("/local-processing/{job_id}/result", response_model=ProcessingResultOut)
def submit_result(
    body: ProcessingResultIn,
    auth: tuple[LocalProcessingJob, dict] = Depends(get_agent_job),
    db: Session = Depends(get_db),
) -> ProcessingResultOut:
    job, claims = auth
    user_id = uuid.UUID(claims["user_id"])
    settings = get_settings()

    existing = db.scalar(select(Transcript).where(Transcript.job_id == job.id))
    if existing is not None:
        if job.idempotency_key == body.idempotency_key:
            # Safe retry after a lost response: return the same answer.
            return ProcessingResultOut(job_id=job.id, transcript_id=existing.id, status=job.status, duplicate=True)
        raise HTTPException(status.HTTP_409_CONFLICT, detail="result_already_submitted")
    if job.status == JobStatus.CANCELLED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="job_cancelled")

    session = db.get(InvestigationSession, job.session_id)
    recording = db.get(AudioRecording, job.recording_id)
    if session is None or recording is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job_not_found")

    ws = _upsert_workstation(db, body.workstation, user_id)
    if ws is not None:
        job.workstation_id = ws.id

    if body.audio is not None:
        if body.audio.duration_seconds is not None:
            recording.duration_seconds = body.audio.duration_seconds
        if body.audio.sha256:
            recording.sha256 = body.audio.sha256
        if body.audio.size_bytes:
            recording.size_bytes = body.audio.size_bytes
        if body.audio.mime_type:
            recording.mime_type = body.audio.mime_type[:100]

    transcript = Transcript(
        session_id=session.id,
        recording_id=recording.id,
        job_id=job.id,
        status=TranscriptStatus.RECEIVED,
        language=body.language,
        stt_provider=body.stt_provider,
        stt_model=body.stt_model,
        stt_model_revision=body.stt_model_revision,
        diarization_provider=body.diarization_provider,
        diarization_model=body.diarization_model,
        diarization_model_revision=body.diarization_model_revision,
        vad_model=body.vad_model,
        agent_version=body.agent_version,
        processing_device=body.processing_device,
        speaker_count=body.speaker_count,
        warnings=list(body.warnings),
        processing_metadata=body.processing_metadata,
        completed_at=body.completed_at or datetime.now(timezone.utc),
    )
    db.add(transcript)
    db.flush()
    ordered = sorted(body.segments, key=lambda s: (s.start_seconds, s.end_seconds, s.speaker_label))
    for index, seg in enumerate(ordered):
        db.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                sequence=index,
                speaker_label=seg.speaker_label,
                start_seconds=round(seg.start_seconds, 3),
                end_seconds=round(seg.end_seconds, 3),
                original_text=seg.text,
                confidence=seg.confidence,
                is_overlap=seg.is_overlap,
            )
        )
    labels = sorted({s.speaker_label for s in body.segments})
    existing_labels = {
        s.speaker_label for s in db.scalars(select(SessionSpeaker).where(SessionSpeaker.session_id == session.id)).all()
    }
    for label in labels:
        if label not in existing_labels:
            db.add(SessionSpeaker(session_id=session.id, speaker_label=label, speaker_role=SpeakerRole.UNKNOWN))

    db.flush()
    # Optional: turn the locally computed voice embeddings into name SUGGESTIONS.
    # Never fails the sync - a transcript must land even if identification does not.
    from app.services.voice_matching import apply_voice_identification

    suggested = apply_voice_identification(
        db,
        session_id=session.id,
        voice=body.voice_identification.model_dump() if body.voice_identification else None,
        user_id=user_id,
    )

    job.status = JobStatus.COMPLETED
    job.agent_state = "COMPLETED"
    job.idempotency_key = body.idempotency_key
    job.completed_at = datetime.now(timezone.utc)
    job.agent_metadata = {"speaker_count": body.speaker_count, "warnings": body.warnings}
    session.status = SessionStatus.COMPLETED
    if recording.upload_status == RecordingUploadStatus.PENDING and not settings.storage_root:
        recording.upload_status = RecordingUploadStatus.DISABLED

    record_audit(db, action=AuditAction.LOCAL_PROCESSING_COMPLETED, user_id=user_id, entity_type="local_processing_job", entity_id=job.id, metadata={"session_id": session.id, "segments": len(body.segments), "speakers": labels, "device": body.processing_device, "voice_suggestions": suggested})
    record_audit(db, action=AuditAction.TRANSCRIPT_RECEIVED, user_id=user_id, entity_type="transcript", entity_id=transcript.id, metadata={"session_id": session.id, "job_id": job.id, "stt_model": body.stt_model, "stt_model_revision": body.stt_model_revision, "diarization_model": body.diarization_model, "diarization_model_revision": body.diarization_model_revision, "agent_version": body.agent_version})
    db.commit()
    return ProcessingResultOut(job_id=job.id, transcript_id=transcript.id, status=JobStatus.COMPLETED, duplicate=False)


@router.post("/local-processing/{job_id}/audio", status_code=status.HTTP_201_CREATED)
async def upload_original_audio(
    auth: tuple[LocalProcessingJob, dict] = Depends(get_agent_job),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    job, claims = auth
    user_id = uuid.UUID(claims["user_id"])
    recording = db.get(AudioRecording, job.recording_id)
    if recording is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="recording_not_found")
    if recording.upload_status == RecordingUploadStatus.UPLOADED and recording.storage_path:
        return {"recording_id": str(recording.id), "duplicate": True, "sha256": recording.sha256}
    try:
        ext = validate_declared(file.filename or recording.original_filename, file.content_type or recording.mime_type, recording.size_bytes or 1)
        rel, size, sha256 = await store_upload(file, job.session_id, recording.id, ext)
    except InvalidAudioError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from exc
    if recording.sha256 and recording.sha256 != sha256:
        # The agent told us a different hash for the original: refuse to store a mismatched file.
        from app.services.storage import absolute_path

        path = absolute_path(rel)
        if path:
            path.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="sha256_mismatch")
    recording.sha256 = sha256
    recording.size_bytes = size
    recording.storage_path = rel
    recording.upload_status = RecordingUploadStatus.UPLOADED
    record_audit(db, action=AuditAction.RECORDING_UPLOADED, user_id=user_id, entity_type="audio_recording", entity_id=recording.id, metadata={"session_id": job.session_id, "size_bytes": size, "sha256": sha256})
    db.commit()
    return {"recording_id": str(recording.id), "duplicate": False, "sha256": sha256, "size_bytes": size}


@router.get("/local-processing/{job_id}", response_model=JobOut)
def get_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobOut:
    job = db.get(LocalProcessingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job_not_found")
    get_accessible_session(job.session_id, user, db)
    return _job_out(job)
