"""Voice enrolment registry and identity-suggestion decisions.

Two separate permissions guard this area because voice templates are biometric data:

* `voice.identify` - see suggestions, confirm or reject them
* `voice.enroll`   - create or delete enrolments

A suggestion NEVER becomes a speaker's name by itself. `display_name` is written only
when an investigator confirms, and the decision (who, when) is audited.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import client_ip, get_accessible_session, require_permission
from app.db.session import get_db
from app.models import (
    AuditAction,
    IdentificationStatus,
    InvestigationSession,
    SessionSpeaker,
    SpeakerRole,
    User,
    VoiceEnrollment,
)
from app.schemas.voice import (
    SpeakerDecisionIn,
    VoiceEnrollmentCreate,
    VoiceEnrollmentOut,
    VoiceEnrollmentUpdate,
)
from app.services.audit import record_audit

router = APIRouter(tags=["voice"])


def _out(db: Session, e: VoiceEnrollment) -> VoiceEnrollmentOut:
    user = db.get(User, e.enrolled_by) if e.enrolled_by else None
    name = user.profile.full_name if user and user.profile else (user.username if user else None)
    return VoiceEnrollmentOut(
        id=e.id,
        person_name=e.person_name,
        person_reference=e.person_reference,
        notes=e.notes,
        model=e.model,
        model_revision=e.model_revision,
        provider=e.provider,
        embedding_dim=e.embedding_dim,
        sample_seconds=e.sample_seconds,
        source_session_id=e.source_session_id,
        source_speaker_label=e.source_speaker_label,
        consent_recorded=e.consent_recorded,
        is_active=e.is_active,
        enrolled_by=e.enrolled_by,
        enrolled_by_name=name,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


@router.get("/voice-enrollments", response_model=list[VoiceEnrollmentOut])
def list_enrollments(
    q: str | None = Query(default=None, max_length=100),
    include_inactive: bool = Query(default=False),
    _: User = Depends(require_permission("voice.identify")),
    db: Session = Depends(get_db),
) -> list[VoiceEnrollmentOut]:
    """Enrolment metadata. The embeddings themselves are never returned to a browser."""
    stmt = select(VoiceEnrollment)
    if not include_inactive:
        stmt = stmt.where(VoiceEnrollment.is_active.is_(True))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(VoiceEnrollment.person_name.ilike(like) | VoiceEnrollment.person_reference.ilike(like))
    return [_out(db, e) for e in db.scalars(stmt.order_by(VoiceEnrollment.person_name)).all()]


@router.post(
    "/investigations/{session_id}/speakers/{speaker_id}/enroll",
    response_model=VoiceEnrollmentOut,
    status_code=status.HTTP_201_CREATED,
)
def enroll_from_speaker(
    speaker_id: uuid.UUID,
    body: VoiceEnrollmentCreate,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("voice.enroll")),
    db: Session = Depends(get_db),
) -> VoiceEnrollmentOut:
    """Create a voice template from a speaker whose identity is already established."""
    speaker = db.get(SessionSpeaker, speaker_id)
    if speaker is None or speaker.session_id != session.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="speaker_not_found")
    if not speaker.voice_embedding:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="speaker_has_no_voice_embedding")
    if not body.consent_recorded:
        # Enrolling a biometric template without recorded consent is refused outright.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="consent_required")

    # Check identity collisions first: "already enrolled" is the more specific and more
    # actionable answer than "you did not supply a name".
    existing = db.scalar(
        select(VoiceEnrollment).where(
            VoiceEnrollment.person_reference == body.person_reference,
            VoiceEnrollment.model == body.model,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="person_already_enrolled")

    person_name = (body.person_name or speaker.display_name or "").strip()
    if not person_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="person_name_required")

    enrollment = VoiceEnrollment(
        person_name=person_name,
        person_reference=body.person_reference,
        notes=body.notes,
        embedding=list(speaker.voice_embedding),
        embedding_dim=len(speaker.voice_embedding),
        model=body.model,
        model_revision=body.model_revision or speaker.suggested_model_revision,
        provider=body.provider,
        sample_seconds=body.sample_seconds,
        source_session_id=session.id,
        source_speaker_label=speaker.speaker_label,
        consent_recorded=True,
        enrolled_by=user.id,
    )
    db.add(enrollment)
    db.flush()
    record_audit(
        db,
        action=AuditAction.VOICE_ENROLLED,
        user_id=user.id,
        entity_type="voice_enrollment",
        entity_id=enrollment.id,
        metadata={
            "session_id": session.id,
            "speaker_label": speaker.speaker_label,
            "person_name": person_name,
            "person_reference": body.person_reference,
            "model": body.model,
            "consent_recorded": True,
        },
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(enrollment)
    return _out(db, enrollment)


@router.patch("/voice-enrollments/{enrollment_id}", response_model=VoiceEnrollmentOut)
def update_enrollment(
    enrollment_id: uuid.UUID,
    body: VoiceEnrollmentUpdate,
    request: Request,
    user: User = Depends(require_permission("voice.enroll")),
    db: Session = Depends(get_db),
) -> VoiceEnrollmentOut:
    enrollment = db.get(VoiceEnrollment, enrollment_id)
    if enrollment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="enrollment_not_found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(enrollment, field, value)
    record_audit(
        db,
        action=AuditAction.VOICE_ENROLLED,
        user_id=user.id,
        entity_type="voice_enrollment",
        entity_id=enrollment.id,
        metadata={"updated": list(body.model_dump(exclude_unset=True).keys()), "is_active": enrollment.is_active},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(enrollment)
    return _out(db, enrollment)


@router.delete("/voice-enrollments/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_enrollment(
    enrollment_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("voice.enroll")),
    db: Session = Depends(get_db),
) -> Response:
    enrollment = db.get(VoiceEnrollment, enrollment_id)
    if enrollment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="enrollment_not_found")
    record_audit(
        db,
        action=AuditAction.VOICE_ENROLLMENT_DELETED,
        user_id=user.id,
        entity_type="voice_enrollment",
        entity_id=enrollment.id,
        metadata={"person_name": enrollment.person_name, "person_reference": enrollment.person_reference},
        ip_address=client_ip(request),
    )
    db.delete(enrollment)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/investigations/{session_id}/speakers/{speaker_id}/identification")
def decide_suggestion(
    speaker_id: uuid.UUID,
    body: SpeakerDecisionIn,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("voice.identify")),
    db: Session = Depends(get_db),
) -> dict:
    """Confirm or reject a voice suggestion.

    Confirming is the ONLY path by which a voice comparison can reach `display_name`,
    and it requires `speakers.assign` as well - the same permission as typing the name
    by hand.
    """
    speaker = db.get(SessionSpeaker, speaker_id)
    if speaker is None or speaker.session_id != session.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="speaker_not_found")
    if speaker.identification_status != IdentificationStatus.SUGGESTED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="no_pending_suggestion")

    now = datetime.now(timezone.utc)
    if body.accept:
        if "speakers.assign" not in user.permission_codes:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
        speaker.display_name = speaker.suggested_name
        if speaker.speaker_role == SpeakerRole.UNKNOWN:
            speaker.speaker_role = SpeakerRole.SUBJECT
        speaker.identification_status = IdentificationStatus.CONFIRMED
        action = AuditAction.VOICE_IDENTITY_CONFIRMED
    else:
        speaker.identification_status = IdentificationStatus.REJECTED
        action = AuditAction.VOICE_IDENTITY_REJECTED
    speaker.decided_by = user.id
    speaker.decided_at = now
    record_audit(
        db,
        action=action,
        user_id=user.id,
        entity_type="session_speaker",
        entity_id=speaker.id,
        metadata={
            "session_id": session.id,
            "speaker_label": speaker.speaker_label,
            "suggested_name": speaker.suggested_name,
            "score": float(speaker.suggested_score) if speaker.suggested_score is not None else None,
            "accepted": body.accept,
            "display_name": speaker.display_name,
        },
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(speaker)
    return {
        "speaker_id": str(speaker.id),
        "identification_status": speaker.identification_status.value,
        "display_name": speaker.display_name,
    }
