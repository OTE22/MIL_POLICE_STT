"""Human attestations over explicit print sets; never change biometric comparisons."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, User, VoiceEnrollment
from app.schemas.voice import VoiceIdentityConfirmationOut

CONFIRMED = "VOICE_IDENTITY_SET_CONFIRMED"
REOPENED = "VOICE_IDENTITY_SET_REOPENED"


def reviewer_name(db: Session, user_id):
    user = db.get(User, user_id) if user_id else None
    return (user.profile.full_name if user.profile else user.username) if user else None


def identity_confirmations(db: Session, identity_id, prints: list[VoiceEnrollment]):
    events = db.scalars(select(AuditLog).where(
        AuditLog.action.in_([CONFIRMED, REOPENED]),
        AuditLog.entity_type == "person_identity",
        AuditLog.entity_id == str(identity_id),
    ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())).all()
    reopened = {}
    for event in events:
        if event.action == REOPENED:
            reopened.setdefault(event.safe_metadata["confirmation_id"], event)
    current = {str(p.id): p for p in prints if p.is_active and p.identity_id == identity_id}
    result = []
    for event in events:
        if event.action != CONFIRMED:
            continue
        metadata = event.safe_metadata
        undo = reopened.get(str(event.id))
        versions = metadata["print_versions"]
        unchanged = all(key in current and current[key].updated_at.isoformat() == version
                        for key, version in versions.items())
        result.append(VoiceIdentityConfirmationOut(
            id=event.id, enrollment_ids=list(versions), reason=metadata["reason"],
            reviewer_name=reviewer_name(db, event.user_id), created_at=event.created_at,
            status="REOPENED" if undo else "ACTIVE" if unchanged else "STALE",
            reopened_reason=undo.safe_metadata["reason"] if undo else None,
            reopened_by_name=reviewer_name(db, undo.user_id) if undo else None,
            reopened_at=undo.created_at if undo else None,
        ))
    return result
