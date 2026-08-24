"""Match speaker voice embeddings against the enrolment registry.

This is arithmetic, not inference: the model runs on the workstation and only the
resulting embedding reaches the central server. The outcome is always a *suggestion*
recorded on the speaker row; `display_name` is only ever written by a human.

Rules that keep the result defensible:

* embeddings are only compared within the same model (they are not comparable across
  models or providers);
* a match below `VOICE_MATCH_THRESHOLD` produces no suggestion at all (abstain rather
  than guess);
* if the best and second-best candidates are closer together than
  `VOICE_MATCH_MARGIN`, the result is ambiguous and no suggestion is made;
* the score, model and revision are stored with every suggestion.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditAction, IdentificationStatus, SessionSpeaker, VoiceEnrollment
from app.services.audit import record_audit

log = logging.getLogger(__name__)


@dataclass
class MatchResult:
    enrollment: VoiceEnrollment
    score: float
    runner_up: float | None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def best_match(
    embedding: list[float],
    enrollments: list[VoiceEnrollment],
    *,
    model: str,
    threshold: float,
    margin: float,
) -> MatchResult | None:
    """Best enrolled voice for this embedding, or None when uncertain."""
    scored: list[tuple[float, VoiceEnrollment]] = []
    for enr in enrollments:
        if not enr.is_active or enr.model != model or enr.embedding_dim != len(embedding):
            continue
        scored.append((cosine_similarity(embedding, list(enr.embedding)), enr))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score, top = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else None
    if top_score < threshold:
        return None
    # Two enrolled people sound similarly close to this voice: refuse to choose.
    if runner_up is not None and (top_score - runner_up) < margin:
        log.info("voice match ambiguous: %.3f vs %.3f", top_score, runner_up)
        return None
    return MatchResult(enrollment=top, score=top_score, runner_up=runner_up)


def apply_voice_identification(
    db: Session,
    *,
    session_id: uuid.UUID,
    voice: dict | None,
    user_id: uuid.UUID | None,
) -> int:
    """Store embeddings and suggestions for a session's speakers. Returns #suggestions.

    Called when a Local Agent submits a result. Never raises: identification is an
    optional convenience and must not fail the synchronization of a transcript.
    """
    if not voice:
        return 0
    settings = get_settings()
    try:
        model = voice.get("model") or ""
        speakers = voice.get("speakers") or {}
        if not model or not speakers:
            return 0
        enrollments = list(db.scalars(select(VoiceEnrollment).where(VoiceEnrollment.is_active.is_(True))).all())
        rows = {
            s.speaker_label: s
            for s in db.scalars(select(SessionSpeaker).where(SessionSpeaker.session_id == session_id)).all()
        }
        suggested = 0
        now = datetime.now(timezone.utc)
        for label, payload in speakers.items():
            row = rows.get(label)
            if row is None:
                continue
            embedding = list(payload.get("embedding") or [])
            if not embedding:
                continue
            row.voice_embedding = embedding
            # A human decision is final: never overwrite a confirmed/rejected speaker.
            if row.identification_status in (IdentificationStatus.CONFIRMED, IdentificationStatus.REJECTED):
                continue
            match = best_match(
                embedding,
                enrollments,
                model=model,
                threshold=settings.voice_match_threshold,
                margin=settings.voice_match_margin,
            )
            if match is None:
                row.identification_status = IdentificationStatus.NONE
                row.suggested_name = None
                row.suggested_enrollment_id = None
                row.suggested_score = None
                continue
            row.identification_status = IdentificationStatus.SUGGESTED
            row.suggested_name = match.enrollment.person_name
            row.suggested_enrollment_id = match.enrollment.id
            row.suggested_score = round(match.score, 4)
            row.suggested_model = model
            row.suggested_model_revision = voice.get("model_revision")
            row.suggested_at = now
            suggested += 1
            record_audit(
                db,
                action=AuditAction.VOICE_IDENTITY_SUGGESTED,
                user_id=user_id,
                entity_type="session_speaker",
                entity_id=row.id,
                metadata={
                    "session_id": session_id,
                    "speaker_label": label,
                    "suggested_name": match.enrollment.person_name,
                    "score": round(match.score, 4),
                    "runner_up": round(match.runner_up, 4) if match.runner_up is not None else None,
                    "model": model,
                    "model_revision": voice.get("model_revision"),
                    "requires_confirmation": True,
                },
            )
        return suggested
    except Exception:  # noqa: BLE001
        log.exception("voice identification failed for session %s (transcript is unaffected)", session_id)
        return 0
