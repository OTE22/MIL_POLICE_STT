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
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import accessible_sessions_stmt, client_ip, get_accessible_session, require_permission
from app.db.session import get_db
from app.models import (
    AuditAction,
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
    BiometricPrintCheckOut,
    EnrollmentCandidateOut,
    IdentityConsolidateIn,
    PersonSearchOut,
    SpeakerDecisionIn,
    VoiceEnrollmentCreate,
    VoiceEnrollmentOut,
    VoiceEnrollmentUpdate,
)
from app.services.audit import record_audit
from app.services.person_identity import (
    IdentityMergeConflict,
    merge_identities,
    repoint_identity,
    resolve_identity,
)
from app.services.voice_matching import rematch_speakers

log = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])


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
        model=body.model,
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
    enrollment = db.get(VoiceEnrollment, enrollment_id)
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
        # Confirming a match means "this speaker IS that person", so link the canonical
        # identity of the print that matched. Without this the speaker would carry a name but
        # no identity - it could never be enrolled, and the link back to the person would be
        # lost. No new identity is created: the matched one is reused.
        matched = db.get(VoiceEnrollment, speaker.suggested_enrollment_id) if speaker.suggested_enrollment_id else None
        identity = resolve_identity(db, db.get(PersonIdentity, matched.identity_id)) if matched and matched.identity_id else None
        if identity is not None:
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
    return {
        "speaker_id": str(speaker.id),
        "identification_status": speaker.identification_status.value,
        "display_name": speaker.display_name,
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
                sample_seconds=_speaker_seconds(db, speaker),
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
    by_group: dict[tuple[str, int], list[VoiceEnrollment]] = {}
    for e in prints:
        by_group.setdefault((e.model, e.embedding_dim), []).append(e)

    for (model, dim), members in by_group.items():
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
                )
            )
        groups.append(
            BiometricGroupOut(model=model, embedding_dim=dim, component_count=component_count, prints=out_prints)
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
    )
