"""Investigator narration is report provenance, never interview testimony."""
import hashlib
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from app.models import AudioRecording, AuditAction, JobStatus, RecordingUploadStatus
from app.schemas.processing import ProcessingResultOut
from app.services.audit import record_audit


def require_investigator(session, user):
    if "reports.generate" not in user.permission_codes or not any(
        link.investigator.user_id == user.id for link in session.investigators
    ):
        raise HTTPException(403, detail="dictation_assigned_investigator_required")


def target(document, block_id, field):
    block = next((b for b in document["blocks"] if b["id"] == str(block_id)), None)
    if block is None:
        raise HTTPException(409, detail="dictation_destination_changed")
    if block["type"] == "note" and field == "note_text" and not block.get("template_id"):
        return block, block["values"], field
    if block["type"] == "conclusion":
        if field in {"facts", "inference", "proposals"}:
            return block, block["values"], field
        if field.startswith("finding:"):
            finding = next((f for f in block["findings"] if f["id"] == field[8:]), None)
            if finding:
                return block, finding, "text"
    raise HTTPException(422, detail="dictation_field_not_allowed")


def text_token(text):
    return hashlib.sha256(text.encode()).hexdigest()


def receive_result(db, session, recording, job, body, user_id):
    context = dict(recording.report_context or {})
    if context.get("result"):
        if job.idempotency_key == body.idempotency_key:
            return ProcessingResultOut(job_id=job.id, status=job.status, duplicate=True)
        raise HTTPException(409, detail="result_already_submitted")
    if job.status == JobStatus.CANCELLED:
        raise HTTPException(409, detail="job_cancelled")
    if body.audio:
        if body.audio.sha256:
            if recording.storage_path and recording.sha256 != body.audio.sha256:
                raise HTTPException(409, detail="verified_audio_hash_conflict")
            recording.sha256 = body.audio.sha256
        recording.duration_seconds = body.audio.duration_seconds
    # Keep the complete machine result separately from the investigator's accepted wording.
    context["result"] = body.model_dump(mode="json", exclude={"voice_identification"})
    context["machine_text"] = "\n".join(s.text for s in sorted(body.segments, key=lambda s: s.start_seconds)).strip()
    context["status"] = "DISMISSED" if context.get("status") == "DISMISSED" else "READY"
    recording.report_context = context
    job.status = JobStatus.COMPLETED
    job.agent_state = "COMPLETED"
    job.idempotency_key = body.idempotency_key
    job.completed_at = datetime.now(timezone.utc)
    record_audit(db, action=AuditAction.LOCAL_PROCESSING_COMPLETED, user_id=user_id,
                 entity_type="report_dictation", entity_id=recording.id,
                 metadata={"session_id": str(session.id), "purpose": recording.purpose,
                           "block_id": context["block_id"], "field": context["field"]})
    db.commit()
    return ProcessingResultOut(job_id=job.id, status=job.status)


def rows(db, session_id):
    return db.scalars(select(AudioRecording).where(AudioRecording.session_id == session_id,
        AudioRecording.purpose == "REPORT_DICTATION").order_by(AudioRecording.created_at)).all()


def blockers(db, session, draft, verify_hashes=False):
    reasons = []
    from app.services.storage import absolute_path
    for recording in rows(db, session.id):
        context = recording.report_context or {}
        if context.get("draft_id") == str(draft.id) and context.get("status") not in {"ACCEPTED", "DISMISSED"}:
            reasons.append("report_dictation_pending")
        if context.get("status") == "ACCEPTED":
            path = absolute_path(recording.storage_path) if recording.storage_path else None
            if not path or not recording.sha256 or recording.upload_status != RecordingUploadStatus.UPLOADED:
                reasons.append("dictation_audio_missing")
            elif verify_hashes:
                try:
                    with path.open("rb") as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() != recording.sha256:
                            reasons.append("dictation_audio_integrity_failed")
                except OSError:
                    reasons.append("dictation_audio_missing")
    return reasons
