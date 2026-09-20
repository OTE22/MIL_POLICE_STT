"""Voice enrolment registry and identity-suggestion decisions.

Two separate permissions guard this area because voice templates are biometric data:

* `voice.identify` - see suggestions, confirm or reject them
* `voice.enroll`   - create or delete enrolments

A suggestion NEVER becomes a speaker's name by itself. `display_name` is written only
when an investigator confirms, and the decision (who, when) is audited.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import accessible_sessions_stmt, client_ip, get_accessible_session, require_permission
from app.db.session import get_db
from app.models import (
    AuditAction,
    AuditLog,
    AudioRecording,
    IdentificationStatus,
    InvestigationSession,
    PersonIdentity,
    SessionSpeaker,
    SpeakerRole,
    Subject,
    Transcript,
    TranscriptSegment,
    User,
    VoiceEnrollment,
)
from app.config import get_settings
from app.schemas.voice import (
    BiometricCheckOut,
    BiometricGroupOut,
    BiometricPairOut,
    BiometricPrintCheckOut,
    EnrollmentCandidateOut,
    IdentityConsolidateIn,
    PersonSearchOut,
    SpeakerDecisionIn,
    VoiceEnrollmentCreate,
    VoiceEnrollmentOut,
    VoiceEnrollmentUpdate,
    VoiceReviewIn,
    VoiceReviewOut,
    VoiceSourceOut,
    VoiceSourceSegmentOut,
    VoiceIdentityConfirmationIn,
    VoiceIdentityConfirmationOut,
    VoiceConfirmationReopenIn,
)
from app.services.audit import record_audit
from app.services.person_identity import (
    IdentityMergeConflict,
    merge_identities,
    repoint_identity,
    resolve_identity,
)
from app.services.voice_matching import rematch_speakers
from app.services.voice_review import CONFIRMED, REOPENED, identity_confirmations

log = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])

REVIEW_ACTION = "VOICE_PRINT_REVIEWED"


@router.post("/voice-enrollments/people/{identity_id}/identity-confirmations", response_model=VoiceIdentityConfirmationOut)
def confirm_voice_identity_set(
    identity_id: uuid.UUID, body: VoiceIdentityConfirmationIn, request: Request,
    user: User = Depends(require_permission("voice.enroll")), db: Session = Depends(get_db),
) -> VoiceIdentityConfirmationOut:
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(422, detail="voice_review_reason_required")
    expected = {p.enrollment_id: p.expected_updated_at for p in body.prints}
    if len(expected) != len(body.prints):
        raise HTTPException(422, detail="voice_confirmation_duplicate_prints")
    # Deterministic lock order serializes overlapping selections and print edits.
    prints = list(db.scalars(select(VoiceEnrollment).where(
        VoiceEnrollment.id.in_(expected)).order_by(VoiceEnrollment.id).with_for_update()).all())
    if len(prints) != len(expected) or any(
        p.identity_id != identity_id or not p.is_active or p.updated_at != expected[p.id] for p in prints
    ):
        raise HTTPException(409, detail="voice_review_stale")
    # Numeric component labels change with thresholds. Persist only explicit print IDs.
    for previous in identity_confirmations(db, identity_id, prints):
        if previous.status == "ACTIVE" and set(previous.enrollment_ids) == set(expected):
            raise HTTPException(409, detail="voice_confirmation_exists")
    entry = record_audit(db, action=CONFIRMED, user_id=user.id,
        entity_type="person_identity", entity_id=identity_id,
        metadata={"reason": reason, "print_versions": {str(p.id): p.updated_at.isoformat() for p in prints}},
        ip_address=client_ip(request))
    db.commit()
    db.refresh(entry)
    return next(c for c in identity_confirmations(db, identity_id, prints) if c.id == entry.id)


@router.post("/voice-enrollments/people/{identity_id}/identity-confirmations/{confirmation_id}/reopen",
             response_model=VoiceIdentityConfirmationOut)
def reopen_voice_identity_set(
    identity_id: uuid.UUID, confirmation_id: uuid.UUID, body: VoiceConfirmationReopenIn, request: Request,
    user: User = Depends(require_permission("voice.enroll")), db: Session = Depends(get_db),
) -> VoiceIdentityConfirmationOut:
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(422, detail="voice_review_reason_required")
    entry = db.scalar(select(AuditLog).where(AuditLog.id == confirmation_id,
        AuditLog.action == CONFIRMED, AuditLog.entity_type == "person_identity",
        AuditLog.entity_id == str(identity_id)).with_for_update())
    if entry is None:
        raise HTTPException(404, detail="voice_confirmation_not_found")
    existing = db.scalar(select(AuditLog.id).where(AuditLog.action == REOPENED,
        AuditLog.entity_id == str(identity_id),
        AuditLog.safe_metadata["confirmation_id"].astext == str(confirmation_id)))
    if existing:
        raise HTTPException(409, detail="voice_confirmation_reopened")
    record_audit(db, action=REOPENED, user_id=user.id, entity_type="person_identity", entity_id=identity_id,
        metadata={"confirmation_id": str(confirmation_id), "reason": reason}, ip_address=client_ip(request))
    db.commit()
    return next(c for c in identity_confirmations(db, identity_id, []) if c.id == confirmation_id)


def _review_out(db: Session, entry: AuditLog) -> VoiceReviewOut:
    reviewer = db.get(User, entry.user_id) if entry.user_id else None
    meta = entry.safe_metadata or {}
    return VoiceReviewOut(
        id=entry.id, enrollment_id=entry.entity_id,
        action=meta["review_action"], reason=meta["reason"],
        reviewer_name=(reviewer.profile.full_name if reviewer.profile else reviewer.username) if reviewer else None,
        created_at=entry.created_at,
    )


@router.get("/voice-enrollments/people/{identity_id}/reviews", response_model=list[VoiceReviewOut])
def voice_review_history(
    identity_id: uuid.UUID,
    _: User = Depends(require_permission("voice.identify")),
    db: Session = Depends(get_db),
) -> list[VoiceReviewOut]:
    identity = resolve_identity(db, db.get(PersonIdentity, identity_id))
    if identity is None:
        raise HTTPException(404, detail="person_not_found")
    # Only dedicated review events are exposed, never unrelated audit metadata.
    entries = db.scalars(select(AuditLog).where(
        AuditLog.action == REVIEW_ACTION,
        AuditLog.safe_metadata["identity_id"].astext == str(identity.id),
    ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(100)).all()
    return [_review_out(db, entry) for entry in entries]


@router.post("/voice-enrollments/{enrollment_id}/reviews", response_model=VoiceReviewOut)
def review_voice_print(
    enrollment_id: uuid.UUID, body: VoiceReviewIn, request: Request,
    user: User = Depends(require_permission("voice.enroll")),
    db: Session = Depends(get_db),
) -> VoiceReviewOut:
    enrollment = db.scalar(select(VoiceEnrollment).where(
        VoiceEnrollment.id == enrollment_id).with_for_update())
    if enrollment is None:
        raise HTTPException(404, detail="enrollment_not_found")
    if enrollment.updated_at != body.expected_updated_at or enrollment.identity_id != body.identity_id:
        raise HTTPException(409, detail="voice_review_stale")
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(422, detail="voice_review_reason_required")
    if body.action == "DEACTIVATE":
        if not enrollment.is_active:
            raise HTTPException(409, detail="voice_review_stale")
        enrollment.is_active = False
        _invalidate_pending(db, enrollment.id)
    # Serialize review decisions as well as print edits; stale panels must refresh.
    enrollment.updated_at = datetime.now(timezone.utc)
    entry = record_audit(
        db, action=REVIEW_ACTION, user_id=user.id,
        entity_type="voice_enrollment", entity_id=enrollment.id,
        metadata={"identity_id": str(enrollment.identity_id), "review_action": body.action,
                  "reason": reason, "is_active": enrollment.is_active},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(entry)
    return _review_out(db, entry)


@router.get("/voice-enrollments/{enrollment_id}/source", response_model=VoiceSourceOut)
def voice_print_source(
    enrollment_id: uuid.UUID,
    user: User = Depends(require_permission("voice.identify")),
    db: Session = Depends(get_db),
) -> VoiceSourceOut:
    if "transcripts.read" not in user.permission_codes:
        raise HTTPException(403, detail="forbidden")
    enrollment = db.get(VoiceEnrollment, enrollment_id)
    if enrollment is None or enrollment.source_session_id is None:
        raise HTTPException(404, detail="voice_source_unavailable")
    get_accessible_session(enrollment.source_session_id, user, db)
    speaker = db.scalar(select(SessionSpeaker).where(
        SessionSpeaker.session_id == enrollment.source_session_id,
        SessionSpeaker.speaker_label == enrollment.source_speaker_label,
    ))
    if speaker is None or speaker.recording_id is None:
        raise HTTPException(404, detail="voice_source_unavailable")
    # Never substitute the latest session recording: labels are recording-local.
    # Avoid later reprocessing transcripts, which may have different speaker turns.
    transcript = db.scalar(select(Transcript).where(
        Transcript.session_id == enrollment.source_session_id,
        Transcript.recording_id == speaker.recording_id,
        Transcript.created_at <= enrollment.created_at,
    ).order_by(Transcript.created_at.desc(), Transcript.id.desc()).limit(1))
    recording = db.get(AudioRecording, speaker.recording_id)
    if transcript is None or recording is None or not recording.storage_path or recording.upload_status.value != "UPLOADED":
        raise HTTPException(404, detail="voice_source_unavailable")
    segments = [VoiceSourceSegmentOut(start_seconds=float(s.start_seconds), end_seconds=float(s.end_seconds))
                for s in transcript.segments if s.speaker_label == enrollment.source_speaker_label
                and s.end_seconds > s.start_seconds]
    if not segments:
        raise HTTPException(404, detail="voice_source_unavailable")
    return VoiceSourceOut(recording_id=recording.id, transcript_id=transcript.id, segments=segments)


def _out(db: Session, e: VoiceEnrollment) -> VoiceEnrollmentOut:
    user = db.get(User, e.enrolled_by) if e.enrolled_by else None
    name = user.profile.full_name if user and user.profile else (user.username if user else None)
    identity = db.get(PersonIdentity, e.identity_id) if e.identity_id else None
    identity = resolve_identity(db, identity)
    return VoiceEnrollmentOut(
        id=e.id,
        identity_id=identity.id if identity else None,
        # ONLY the registry answers "who is this". A print whose identity cannot be resolved
        # reports no current person rather than presenting its enrolment-time snapshot as one:
        # that snapshot may be years old, may carry a rank, and may name someone who has since
        # been merged away. The snapshot is still returned below, labelled as history.
        person_name=identity.person_name if identity else "",
        enrolled_person_name=e.person_name,
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
        # Search the CURRENT canonical identity, not the enrolment-time snapshot: after a
        # person is renamed, searching their new name has to find their prints. The snapshot
        # is still matched so an old name a user remembers keeps working.
        identity_match = select(PersonIdentity.id).where(
            PersonIdentity.person_name.ilike(like)
        )
        stmt = stmt.where(
            VoiceEnrollment.person_name.ilike(like)
            | VoiceEnrollment.identity_id.in_(identity_match)
        )
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

    # Enrollment requires a previously selected person; it never infers or creates one.
    if speaker.identity_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="speaker_identity_required")

    # The stored id may point at a row that has since been merged away. Follow the alias to
    # the survivor and converge the speaker onto it, so the print is filed under the person
    # who actually survives rather than under a dead alias.
    identity = resolve_identity(db, db.get(PersonIdentity, speaker.identity_id))
    if identity is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="speaker_identity_required")
    speaker.identity_id = identity.id
    if not speaker.voice_embedding_model:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="voice_provenance_missing")

    # Several prints per person are intended - different recording conditions give better
    # coverage, and the matcher groups them by canonical identity so they reinforce each
    # other rather than competing.
    #
    # The registry owns the enrollment name snapshot; client names are not consulted:
    # it is a session label that may carry a rank, so trusting it filed "الرائد علي عباس"
    # as a person.
    person_name = identity.person_name

    # Only one ACTIVE print per (session, speaker, model). Asked here so a second attempt
    # gets an answer it can act on, naming the print that already holds the slot, instead of
    # reaching the partial unique index and returning an unexplained 500.
    existing = _active_print_for_source(
        db,
        session_id=session.id,
        speaker_label=speaker.speaker_label,
        model=speaker.voice_embedding_model,
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "speaker_already_enrolled",
                "enrollment_id": str(existing.id),
                "person_name": existing.person_name,
                "enrolled_at": existing.created_at.isoformat() if existing.created_at else None,
            },
        )

    enrollment = VoiceEnrollment(
        identity_id=identity.id,
        person_name=person_name,
        notes=body.notes,
        embedding=list(speaker.voice_embedding),
        embedding_dim=len(speaker.voice_embedding),
        model=speaker.voice_embedding_model,
        model_revision=speaker.voice_embedding_revision,
        provider=speaker.voice_embedding_provider,
        sample_seconds=speaker.voice_embedding_seconds,
        source_session_id=session.id,
        source_speaker_label=speaker.speaker_label,
        consent_recorded=True,
        enrolled_by=user.id,
    )
    db.add(enrollment)
    # Two concurrent requests can both pass the check above and only one can win the index.
    # The loser must still get the same 409 as the sequential case, not a 500.
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "speaker_already_enrolled"},
        ) from exc
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
            "model": enrollment.model,
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
    enrollment = db.scalar(select(VoiceEnrollment).where(VoiceEnrollment.id == enrollment_id).with_for_update())
    if enrollment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="enrollment_not_found")

    data = body.model_dump(exclude_unset=True)
    wants_identity_change = "person_name" in data
    if wants_identity_change and not body.apply_to_person:
        # Refusing is the point: a per-print rename would let one person's prints disagree
        # about who they belong to.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="apply_to_person_required")

    identity = resolve_identity(db, db.get(PersonIdentity, enrollment.identity_id)) if enrollment.identity_id else None
    before = {"person_name": identity.person_name} if identity else {}
    affected: list[uuid.UUID] = []

    if wants_identity_change:
        if identity is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="enrollment_has_no_identity")
        new_name = (data.get("person_name") or identity.person_name).strip()
        if not new_name:
            raise HTTPException(400, detail="person_name_required")
        identity.person_name = new_name
        affected = [e.id for e in db.scalars(
            select(VoiceEnrollment).where(VoiceEnrollment.identity_id == identity.id)
        ).all()]

    if "is_active" in data and data["is_active"] and not enrollment.is_active:
        _guard_reactivation(db, enrollment)

    for field in ("notes", "is_active"):
        if field in data:
            setattr(enrollment, field, data[field])

    if data.get("is_active") is False:
        _invalidate_pending(db, enrollment.id)

    record_audit(
        db,
        action=AuditAction.VOICE_ENROLLMENT_UPDATED if wants_identity_change else AuditAction.VOICE_ENROLLED,
        user_id=user.id,
        entity_type="voice_enrollment",
        entity_id=enrollment.id,
        metadata={
            "updated": list(data.keys()),
            "is_active": enrollment.is_active,
            **({"identity_before": before,
                "identity_after": {"person_name": identity.person_name},
                "affected_enrollment_ids": affected} if wants_identity_change and identity else {}),
        },
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(enrollment)
    return _out(db, enrollment)


def _invalidate_pending(db: Session, enrollment_id: uuid.UUID) -> None:
    """Retire pending suggestions, preserving all completed human decisions and audits."""
    db.execute(update(SessionSpeaker).where(
        SessionSpeaker.suggested_enrollment_id == enrollment_id,
        SessionSpeaker.identification_status == IdentificationStatus.SUGGESTED,
    ).values(identification_status=IdentificationStatus.NONE, suggested_name=None,
             suggested_enrollment_id=None, suggested_score=None, suggested_model=None,
             suggested_model_revision=None, suggested_at=None))


def _active_print_for_source(
    db: Session,
    *,
    session_id: uuid.UUID | None,
    speaker_label: str,
    model: str,
    exclude_id: uuid.UUID | None = None,
) -> VoiceEnrollment | None:
    """The active print already filed against this (session, speaker, model), if any.

    `uq_voice_enrollment_active_source` enforces one of these. Both the creation and the
    reactivation path have to ask the same question, and asking it in one place is what stops
    them drifting - the creation path did not ask at all, so a second enrolment reached the
    index and came back as a raw IntegrityError, i.e. a 500 with no usable message.
    """
    stmt = select(VoiceEnrollment).where(
        VoiceEnrollment.is_active.is_(True),
        VoiceEnrollment.source_session_id == session_id,
        VoiceEnrollment.source_speaker_label == speaker_label,
        VoiceEnrollment.model == model,
    )
    if exclude_id is not None:
        stmt = stmt.where(VoiceEnrollment.id != exclude_id)
    return db.scalar(stmt)


def _guard_reactivation(db: Session, enrollment: VoiceEnrollment) -> None:
    """Reactivating must respect the one-active-print-per-source guarantee."""
    if _active_print_for_source(
        db,
        session_id=enrollment.source_session_id,
        speaker_label=enrollment.source_speaker_label,
        model=enrollment.model,
        exclude_id=enrollment.id,
    ) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="enrollment_already_active",
        )


@router.delete("/voice-enrollments/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_enrollment(
    enrollment_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("voice.enroll")),
    db: Session = Depends(get_db),
) -> Response:
    enrollment = db.scalar(select(VoiceEnrollment).where(VoiceEnrollment.id == enrollment_id).with_for_update())
    if enrollment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="enrollment_not_found")
    record_audit(
        db,
        action=AuditAction.VOICE_ENROLLMENT_DELETED,
        user_id=user.id,
        entity_type="voice_enrollment",
        entity_id=enrollment.id,
        metadata={
            "person_name": enrollment.person_name,
            # Recorded because suggested_enrollment_id is ON DELETE SET NULL: without this
            # a confirmed identification could no longer name the print it rested on.
            "enrollment_id": enrollment.id,
            "model": enrollment.model,
        },
        ip_address=client_ip(request),
    )
    _invalidate_pending(db, enrollment.id)
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
        # Lock the supporting print against concurrent deactivation/deletion, then reload
        # the suggestion in case a retiring transaction invalidated it while we waited.
        matched = db.scalar(select(VoiceEnrollment).where(
            VoiceEnrollment.id == speaker.suggested_enrollment_id).with_for_update())
        db.refresh(speaker, with_for_update=True)
        identity = resolve_identity(db, db.get(PersonIdentity, matched.identity_id)) if matched and matched.identity_id else None
        if (speaker.identification_status != IdentificationStatus.SUGGESTED
                or speaker.identity_id is not None
                or matched is None or not matched.is_active or identity is None
                or speaker.suggested_enrollment_id != matched.id
                or matched.model != speaker.voice_embedding_model
                or matched.embedding_dim != len(speaker.voice_embedding or [])
                or matched.model_revision != speaker.voice_embedding_revision
                or matched.provider != speaker.voice_embedding_provider):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="voice_suggestion_stale")
        speaker.display_name = identity.person_name
        if speaker.speaker_role == SpeakerRole.UNKNOWN:
            speaker.speaker_role = SpeakerRole.SUBJECT
        speaker.identification_status = IdentificationStatus.CONFIRMED
        # Confirming a match means "this speaker IS that person", so link the canonical
        # identity of the print that matched. Without this the speaker would carry a name but
        # no identity - it could never be enrolled, and the link back to the person would be
        # lost. No new identity is created: the matched one is reused.
        speaker.identity_id = identity.id
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
            "enrollment_id": speaker.suggested_enrollment_id,
            "score": float(speaker.suggested_score) if speaker.suggested_score is not None else None,
            "accepted": body.accept,
            "display_name": speaker.display_name,
            "identity_id": speaker.identity_id,
        },
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(speaker)
    current_identity = resolve_identity(db, db.get(PersonIdentity, speaker.identity_id)) if speaker.identity_id else None
    return {
        "speaker_id": str(speaker.id),
        "identification_status": speaker.identification_status.value,
        "display_name": speaker.display_name,
        "identity_id": str(current_identity.id) if current_identity else None,
        "identity_name": current_identity.person_name if current_identity else None,
        "speaker_role": speaker.speaker_role.value,
    }


@router.post("/investigations/{session_id}/voice-rematch")
def rematch_session(
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("voice.identify")),
    db: Session = Depends(get_db),
) -> dict:
    """Re-run voice matching for one session from the embeddings already stored.

    Matching normally happens once, when the agent submits its result, so a voice
    enrolled afterwards is never applied to an existing session. This closes that gap
    without reprocessing any audio. Confirmed and rejected speakers are left untouched.
    """
    _, scanned, suggested = rematch_speakers(db, session_ids=[session.id], user_id=user.id)
    record_audit(
        db,
        action=AuditAction.VOICE_REMATCH_RUN,
        user_id=user.id,
        entity_type="investigation_session",
        entity_id=session.id,
        metadata={"scope": "session", "scanned": scanned, "suggested": suggested},
        ip_address=client_ip(request),
    )
    db.commit()
    return {"scanned": scanned, "suggested": suggested}


@router.post("/voice-enrollments/rematch")
def rematch_all(
    request: Request,
    user: User = Depends(require_permission("voice.identify")),
    db: Session = Depends(get_db),
) -> dict:
    """Re-scan every still-unidentified speaker across all sessions.

    Restricted to speakers currently at NONE: a re-scan must never disturb a session an
    investigator has already decided.
    """
    sessions, scanned, suggested = rematch_speakers(
        db, session_ids=None, user_id=user.id, only_undecided=True
    )
    record_audit(
        db,
        action=AuditAction.VOICE_REMATCH_RUN,
        user_id=user.id,
        entity_type="voice_enrollment",
        entity_id=None,
        metadata={"scope": "all", "sessions": sessions, "scanned": scanned, "suggested": suggested},
        ip_address=client_ip(request),
    )
    db.commit()
    return {"sessions": sessions, "scanned": scanned, "suggested": suggested}


def _speaker_seconds(db: Session, speaker: SessionSpeaker) -> float | None:
    """How much speech this speaker contributed, summed from the transcript segments."""
    total = db.scalar(
        select(func.coalesce(func.sum(TranscriptSegment.end_seconds - TranscriptSegment.start_seconds), 0))
        .select_from(TranscriptSegment)
        .join(Transcript, Transcript.id == TranscriptSegment.transcript_id)
        .where(
            Transcript.session_id == speaker.session_id,
            TranscriptSegment.speaker_label == speaker.speaker_label,
        )
    )
    return round(float(total), 2) if total else None

@router.get("/voice-enrollments/people", response_model=list[PersonSearchOut])
def search_people(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_permission("voice.identify")),
    db: Session = Depends(get_db),
) -> list[PersonSearchOut]:
    """Canonical identities, for reusing a person when identifying an unknown speaker.

    Merged identities are aliases, not people: they resolve to their survivor and are
    de-duplicated, so a reference that was merged away can never appear as a second person.
    """
    stmt = select(PersonIdentity).where(PersonIdentity.merged_into_id.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            PersonIdentity.person_name.ilike(like)
        )
    identities = db.scalars(stmt.order_by(PersonIdentity.person_name).limit(limit)).all()
    if not identities:
        return []

    accessible_ids = set(
        db.scalars(accessible_sessions_stmt(db, user).with_only_columns(InvestigationSession.id)).all()
    )

    out: list[PersonSearchOut] = []
    for identity in identities:
        prints = db.scalars(
            select(VoiceEnrollment).where(
                VoiceEnrollment.identity_id == identity.id, VoiceEnrollment.is_active.is_(True)
            )
        ).all()
        # Scope every total to what this user may see. Otherwise the counts alone would
        # disclose activity in sessions they have no access to.
        visible = [p for p in prints if p.source_session_id in accessible_ids]
        sessions = {p.source_session_id for p in visible if p.source_session_id}
        out.append(
            PersonSearchOut(
                identity_id=identity.id,
                person_name=identity.person_name,
                accessible_session_count=len(sessions),
                accessible_print_count=len(visible),
                accessible_sample_seconds=round(sum(p.sample_seconds or 0.0 for p in visible), 2),
            )
        )
    return out


@router.get("/voice-enrollments/candidates", response_model=list[EnrollmentCandidateOut])
def list_candidates(
    user: User = Depends(require_permission("voice.enroll")),
    db: Session = Depends(get_db),
) -> list[EnrollmentCandidateOut]:
    """بانتظار التسجيل — speakers whose person is known and whose voice is ready to enrol.

    Derived from application state, never copied: identify a speaker anywhere and they appear
    here. A speaker with an INACTIVE print is reported as such rather than as a fresh
    candidate, so the operator reactivates instead of creating a duplicate print.
    """
    speakers = db.scalars(
        select(SessionSpeaker)
        .where(
            SessionSpeaker.session_id.in_(
                accessible_sessions_stmt(db, user).with_only_columns(InvestigationSession.id)
            ),
            SessionSpeaker.identity_id.is_not(None),
            SessionSpeaker.voice_embedding.is_not(None),
            SessionSpeaker.voice_embedding_model.is_not(None),
        )
        .order_by(SessionSpeaker.updated_at.desc())
    ).all()

    out: list[EnrollmentCandidateOut] = []
    for speaker in speakers:
        prints = db.scalars(
            select(VoiceEnrollment).where(
                VoiceEnrollment.source_session_id == speaker.session_id,
                VoiceEnrollment.source_speaker_label == speaker.speaker_label,
                VoiceEnrollment.model == speaker.voice_embedding_model,
            )
        ).all()
        if any(p.is_active for p in prints):
            continue  # already enrolled from this exact sample
        identity = resolve_identity(db, db.get(PersonIdentity, speaker.identity_id))
        if identity is None:
            continue
        session = db.get(InvestigationSession, speaker.session_id)
        inactive = next((p for p in prints if not p.is_active), None)
        out.append(
            EnrollmentCandidateOut(
                speaker_id=speaker.id,
                session_id=speaker.session_id,
                session_number=session.session_number if session else "",
                session_title=session.title if session else None,
                speaker_label=speaker.speaker_label,
                # The session label, exactly as it is - empty when the speaker was never
                # labelled. It must not borrow the canonical name: the two mean different
                # things, and conflating them is what put a rank into the registry.
                display_name=speaker.display_name or "",
                person_name=identity.person_name,
                speaker_role=speaker.speaker_role.value,
                identity_id=identity.id,
                sample_seconds=float(speaker.voice_embedding_seconds) if speaker.voice_embedding_seconds is not None else None,
                enrollment_state="enrolled_inactive" if inactive else "never_enrolled",
                inactive_enrollment_id=inactive.id if inactive else None,
                created_at=speaker.updated_at,
            )
        )
    return out


@router.post("/voice-enrollments/people/{identity_id}/consolidate")
def consolidate_identity(
    identity_id: uuid.UUID,
    body: IdentityConsolidateIn,
    request: Request,
    user: User = Depends(require_permission("voice.enroll")),
    db: Session = Depends(get_db),
) -> dict:
    """Merge one canonical person into another, prints or no prints.

    PATCH /voice-enrollments/{id} cannot express this: it is reached through an enrolment, and
    two identities can need consolidating while neither owns one - both may be referenced only
    by subjects and speakers. This is the smallest route that addresses an identity directly,
    and it reuses the same merge and repoint implementation as the print-originated path.

    Guarded by investigations.read_all as well, which only ADMIN holds: consolidation rewrites
    canonical ownership across sessions the caller may not be able to open, so the ability to
    enrol a voice must not confer it.
    """
    if "investigations.read_all" not in user.permission_codes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")

    source = resolve_identity(db, db.get(PersonIdentity, identity_id))
    target = resolve_identity(db, db.get(PersonIdentity, body.into_identity_id))
    if source is None or target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="identity_not_found")

    before = {"person_name": source.person_name}
    try:
        merged, survivor = merge_identities(db, source.id, target.id)
    except IdentityMergeConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="identity_merge_conflict") from exc

    affected = repoint_identity(db, source_id=merged.id, target=survivor)

    record_audit(
        db,
        action=AuditAction.VOICE_ENROLLMENT_UPDATED,
        user_id=user.id,
        entity_type="person_identity",
        entity_id=survivor.id,
        metadata={
            "scope": "identity_consolidation",
            "source_identity_id": merged.id,
            "target_identity_id": survivor.id,
            "identity_before": before,
            "identity_after": {
                "person_name": survivor.person_name,
            },
            # Zero prints is a normal outcome, not a failure.
            "affected_enrollment_ids": affected["enrollment_ids"],
            "affected_enrollments": len(affected["enrollment_ids"]),
            "affected_subjects": affected["subjects"],
            "affected_speakers": affected["speakers"],
        },
        ip_address=client_ip(request),
    )
    db.commit()
    return {
        "identity_id": str(survivor.id),
        "person_name": survivor.person_name,
        **{k: v for k, v in affected.items() if k != "enrollment_ids"},
        "affected_enrollments": len(affected["enrollment_ids"]),
    }



@router.post(
    "/voice-enrollments/people/{identity_id}/biometric-check",
    response_model=BiometricCheckOut,
)
def biometric_check(
    identity_id: uuid.UUID,
    _: User = Depends(require_permission("voice.identify")),
    db: Session = Depends(get_db),
) -> BiometricCheckOut:
    """Manual, advisory coherence review of ONE person's active prints.

    Runs only when the operator presses فحص البصمات الصوتية - never on page load, never at
    enrolment, never across the registry. It compares the selected person's active prints
    with EACH OTHER (one pgvector statement for all pairs), groups them into connected
    components at the coherence threshold, and reports. It changes nothing: which prints
    are really this person's voice is a human judgement, made with the deactivate/delete
    controls that already exist.

    Why components and not just max-similarity: two internally-coherent sets that do not
    match each other (A~B at 0.84, C~D at 0.86, cross ~0.40) give every print a good peer,
    yet the identity may contain two different speakers. Components make that visible;
    the check never says which component is "right".
    """
    identity = resolve_identity(db, db.get(PersonIdentity, identity_id))
    if identity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="person_not_found")

    settings = get_settings()
    coherence = settings.voice_match_threshold
    near_dup = settings.voice_near_duplicate_threshold

    prints = list(
        db.scalars(
            select(VoiceEnrollment)
            .where(VoiceEnrollment.identity_id == identity.id, VoiceEnrollment.is_active.is_(True))
            .order_by(VoiceEnrollment.created_at)
        ).all()
    )

    # ALL pairwise similarities in one statement. The join conditions make incompatible
    # prints (different model or dimension) simply never meet.
    pair_rows = db.execute(
        text(
            """SELECT a.id AS a_id, b.id AS b_id,
                      1 - (a.embedding <=> b.embedding) AS sim
               FROM voice_enrollments a
               JOIN voice_enrollments b
                 ON b.identity_id = a.identity_id
                AND b.model = a.model AND b.embedding_dim = a.embedding_dim
                AND b.model_revision IS NOT DISTINCT FROM a.model_revision
                AND b.provider IS NOT DISTINCT FROM a.provider
                AND a.is_active AND b.is_active AND a.id < b.id
               WHERE a.identity_id = :identity_id"""
        ),
        {"identity_id": str(identity.id)},
    ).all()
    sims: dict[tuple[uuid.UUID, uuid.UUID], float] = {}
    for row in pair_rows:
        value = round(float(row.sim), 4)
        sims[(row.a_id, row.b_id)] = value
        sims[(row.b_id, row.a_id)] = value

    groups: list[BiometricGroupOut] = []
    total_components = 0
    review_states: dict[str, str] = {}
    review_entries = db.scalars(select(AuditLog).where(
        AuditLog.action == REVIEW_ACTION,
        AuditLog.entity_id.in_([str(e.id) for e in prints]),
    ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())).all()
    for entry in review_entries:
        action = (entry.safe_metadata or {}).get("review_action")
        if action in ("FLAG", "RESOLVE") and entry.entity_id not in review_states:
            review_states[entry.entity_id] = "FLAGGED" if action == "FLAG" else "RESOLVED"
    by_group: dict[tuple[str, int, str | None, str | None], list[VoiceEnrollment]] = {}
    for e in prints:
        by_group.setdefault((e.model, e.embedding_dim, e.model_revision, e.provider), []).append(e)

    for (model, dim, revision, provider), members in by_group.items():
        ids = [e.id for e in members]
        # Connected components over "matches at the coherence threshold" edges: plain
        # union-find; galleries are deliberate enrolments, never large.
        parent = {i: i for i in ids}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a in ids:
            for b in ids:
                if a < b and sims.get((a, b), 0.0) >= coherence:
                    parent[find(a)] = find(b)

        roots: dict[uuid.UUID, int] = {}
        for e in members:  # created_at order -> stable 1-based component numbering
            root = find(e.id)
            if root not in roots:
                roots[root] = len(roots) + 1
        component_count = len(roots)
        total_components += component_count

        out_prints = []
        for e in members:
            peer_sims = [sims[(e.id, other)] for other in ids if other != e.id and (e.id, other) in sims]
            coherent_peers = sum(1 for v in peer_sims if v >= coherence)
            if len(members) == 1:
                status_ = "SINGLE_PRINT"
            elif any(v >= near_dup for v in peer_sims):
                status_ = "NEAR_DUPLICATE"
            elif coherent_peers > 0:
                status_ = "COHERENT"
            else:
                status_ = "ISOLATED"
            out_prints.append(
                BiometricPrintCheckOut(
                    enrollment_id=e.id,
                    created_at=e.created_at,
                    source_session_id=e.source_session_id,
                    source_speaker_label=e.source_speaker_label,
                    model=model,
                    embedding_dim=dim,
                    sample_seconds=e.sample_seconds,
                    peer_similarity_max=max(peer_sims) if peer_sims else None,
                    peer_similarity_min=min(peer_sims) if peer_sims else None,
                    coherent_peer_count=coherent_peers,
                    component_id=roots[find(e.id)],
                    status=status_,
                    updated_at=e.updated_at,
                    review_status=review_states.get(str(e.id), "NONE"),
                )
            )
        groups.append(
            BiometricGroupOut(
                model=model, embedding_dim=dim, model_revision=revision, provider=provider,
                component_count=component_count, prints=out_prints,
                pairs=[BiometricPairOut(first_id=a, second_id=b, similarity=sims[(a, b)])
                       for a in ids for b in ids if a < b and (a, b) in sims],
            )
        )

    if not prints:
        overall = "NO_PRINTS"
    elif len(prints) == 1:
        overall = "SINGLE_PRINT"
    elif total_components > 1:
        # Several components (including any isolated print, which is its own component) or
        # several incompatible model groups: only a human can say which set is the person.
        overall = "REVIEW_REQUIRED"
    else:
        overall = "COHERENT"

    # The check is advisory and read-only; its record is the log line (which the context
    # filter stamps with the acting user and request id - no vectors, ever).
    log.info(
        "biometric check identity=%s person=%s prints=%d components=%d status=%s thresholds=%.2f/%.2f",
        identity.id, identity.person_name, len(prints), total_components, overall, coherence, near_dup,
    )

    return BiometricCheckOut(
        identity_id=identity.id,
        person_name=identity.person_name,
        total_active_prints=len(prints),
        number_of_components=total_components,
        overall_status=overall,
        coherence_threshold=coherence,
        near_duplicate_threshold=near_dup,
        groups=groups,
        identity_confirmations=identity_confirmations(db, identity.id, prints),
    )
