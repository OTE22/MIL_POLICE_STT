"""Transcript retrieval, segment correction, speaker mapping and audio playback."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import client_ip, get_accessible_session, get_current_user, require_permission
from app.db.session import get_db
from app.models import (
    AudioRecording,
    AuditAction,
    InvestigationSession,
    RecordingUploadStatus,
    SessionSpeaker,
    SpeakerRole,
    Transcript,
    TranscriptSegment,
    User,
)
from app.schemas.transcripts import SegmentEditIn, SegmentOut, SpeakerOut, SpeakerUpdateIn, TranscriptOut
from app.services.audit import record_audit
from app.services.storage import absolute_path

router = APIRouter(tags=["transcripts"])


def _user_name(db: Session, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None:
        return None
    return user.profile.full_name if user.profile else user.username


def _segment_out(db: Session, seg: TranscriptSegment) -> SegmentOut:
    return SegmentOut(
        id=seg.id,
        sequence=seg.sequence,
        speaker_label=seg.speaker_label,
        start_seconds=float(seg.start_seconds),
        end_seconds=float(seg.end_seconds),
        original_text=seg.original_text,
        edited_text=seg.edited_text,
        confidence=float(seg.confidence) if seg.confidence is not None else None,
        is_overlap=seg.is_overlap,
        edited_by=seg.edited_by,
        edited_by_name=_user_name(db, seg.edited_by),
        edited_at=seg.edited_at,
    )


def _speakers_out(db: Session, session_id: uuid.UUID, transcript: Transcript | None) -> list[SpeakerOut]:
    speakers = db.scalars(
        select(SessionSpeaker).where(SessionSpeaker.session_id == session_id).order_by(SessionSpeaker.speaker_label)
    ).all()
    stats: dict[str, tuple[int, float]] = {}
    if transcript is not None:
        rows = db.execute(
            select(
                TranscriptSegment.speaker_label,
                func.count(TranscriptSegment.id),
                func.coalesce(func.sum(TranscriptSegment.end_seconds - TranscriptSegment.start_seconds), 0),
            )
            .where(TranscriptSegment.transcript_id == transcript.id)
            .group_by(TranscriptSegment.speaker_label)
        ).all()
        stats = {label: (int(count), float(total)) for label, count, total in rows}
    out = []
    for s in speakers:
        count, total = stats.get(s.speaker_label, (0, 0.0))
        out.append(
            SpeakerOut(
                id=s.id,
                session_id=s.session_id,
                speaker_label=s.speaker_label,
                display_name=s.display_name,
                speaker_role=s.speaker_role,
                reference_number=s.reference_number,
                notes=s.notes,
                segment_count=count,
                total_seconds=round(total, 3),
                updated_at=s.updated_at,
                identification_status=s.identification_status,
                suggested_name=s.suggested_name,
                suggested_score=float(s.suggested_score) if s.suggested_score is not None else None,
                suggested_model=s.suggested_model,
                has_voice_embedding=bool(s.voice_embedding),
            )
        )
    return out


def _latest_transcript(db: Session, session_id: uuid.UUID) -> Transcript | None:
    return db.scalar(
        select(Transcript).where(Transcript.session_id == session_id).order_by(Transcript.created_at.desc()).limit(1)
    )


@router.get("/investigations/{session_id}/transcript", response_model=TranscriptOut)
def get_transcript(
    session: InvestigationSession = Depends(get_accessible_session),
    _: User = Depends(require_permission("transcripts.read")),
    db: Session = Depends(get_db),
) -> TranscriptOut:
    transcript = _latest_transcript(db, session.id)
    if transcript is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="transcript_not_found")
    recording = db.get(AudioRecording, transcript.recording_id)
    audio_available = bool(
        recording and recording.upload_status == RecordingUploadStatus.UPLOADED and recording.storage_path
    )
    return TranscriptOut(
        id=transcript.id,
        session_id=transcript.session_id,
        recording_id=transcript.recording_id,
        job_id=transcript.job_id,
        status=transcript.status,
        language=transcript.language,
        stt_provider=transcript.stt_provider,
        stt_model=transcript.stt_model,
        stt_model_revision=transcript.stt_model_revision,
        diarization_provider=transcript.diarization_provider,
        diarization_model=transcript.diarization_model,
        diarization_model_revision=transcript.diarization_model_revision,
        vad_model=transcript.vad_model,
        agent_version=transcript.agent_version,
        processing_device=transcript.processing_device,
        speaker_count=transcript.speaker_count,
        warnings=list(transcript.warnings or []),
        created_at=transcript.created_at,
        completed_at=transcript.completed_at,
        audio_available=audio_available,
        segments=[_segment_out(db, s) for s in transcript.segments],
        speakers=_speakers_out(db, session.id, transcript),
    )


@router.patch("/transcript-segments/{segment_id}", response_model=SegmentOut)
def edit_segment(
    segment_id: uuid.UUID,
    body: SegmentEditIn,
    request: Request,
    user: User = Depends(require_permission("transcripts.edit")),
    db: Session = Depends(get_db),
) -> SegmentOut:
    segment = db.get(TranscriptSegment, segment_id)
    if segment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="segment_not_found")
    transcript = db.get(Transcript, segment.transcript_id)
    get_accessible_session(transcript.session_id, user, db)  # resource-level check
    new_text = body.edited_text.strip()
    previous = segment.edited_text
    if new_text == segment.original_text.strip():
        # Reverting to the AI text clears the correction but keeps the audit trail.
        segment.edited_text = None
        segment.edited_by = None
        segment.edited_at = None
    else:
        segment.edited_text = new_text
        segment.edited_by = user.id
        segment.edited_at = datetime.now(timezone.utc)
    record_audit(
        db,
        action=AuditAction.TRANSCRIPT_SEGMENT_EDITED,
        user_id=user.id,
        entity_type="transcript_segment",
        entity_id=segment.id,
        metadata={
            "transcript_id": transcript.id,
            "session_id": transcript.session_id,
            "sequence": segment.sequence,
            "speaker_label": segment.speaker_label,
            "previous_edited_text": previous,
            "new_edited_text": segment.edited_text,
            "original_text_preserved": True,
        },
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(segment)
    return _segment_out(db, segment)


@router.get("/investigations/{session_id}/speakers", response_model=list[SpeakerOut])
def list_speakers(
    session: InvestigationSession = Depends(get_accessible_session),
    _: User = Depends(require_permission("transcripts.read")),
    db: Session = Depends(get_db),
) -> list[SpeakerOut]:
    return _speakers_out(db, session.id, _latest_transcript(db, session.id))


@router.patch("/investigations/{session_id}/speakers/{speaker_id}", response_model=SpeakerOut)
def update_speaker(
    speaker_id: uuid.UUID,
    body: SpeakerUpdateIn,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("speakers.assign")),
    db: Session = Depends(get_db),
) -> SpeakerOut:
    speaker = db.get(SessionSpeaker, speaker_id)
    if speaker is None or speaker.session_id != session.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="speaker_not_found")
    previous = {"display_name": speaker.display_name, "speaker_role": speaker.speaker_role.value}
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key == "speaker_role":
            speaker.speaker_role = SpeakerRole(value) if value is not None else SpeakerRole.UNKNOWN
        else:
            setattr(speaker, key, value.strip() if isinstance(value, str) else value)
    if speaker.speaker_role is None:
        speaker.speaker_role = SpeakerRole.UNKNOWN
    record_audit(
        db,
        action=AuditAction.SPEAKER_RENAMED,
        user_id=user.id,
        entity_type="session_speaker",
        entity_id=speaker.id,
        metadata={
            "session_id": session.id,
            "speaker_label": speaker.speaker_label,
            "previous": previous,
            "new": {"display_name": speaker.display_name, "speaker_role": speaker.speaker_role.value},
        },
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(speaker)
    for item in _speakers_out(db, session.id, _latest_transcript(db, session.id)):
        if item.id == speaker.id:
            return item
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail="speaker_not_found")


@router.get("/recordings/{recording_id}/audio")
def stream_recording(
    recording_id: uuid.UUID,
    user: User = Depends(require_permission("transcripts.read")),
    db: Session = Depends(get_db),
) -> FileResponse:
    recording = db.get(AudioRecording, recording_id)
    if recording is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="recording_not_found")
    get_accessible_session(recording.session_id, user, db)
    if recording.upload_status != RecordingUploadStatus.UPLOADED or not recording.storage_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="audio_not_available")
    path = absolute_path(recording.storage_path)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="audio_not_available")
    return FileResponse(path, media_type=recording.mime_type, filename=recording.original_filename)
