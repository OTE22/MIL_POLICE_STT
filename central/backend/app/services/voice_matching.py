"""Match speaker voice embeddings against the enrolment registry.

This is arithmetic, not inference: the model runs on the workstation and only the
resulting embedding reaches the central server. The outcome is always a *suggestion*
recorded on the speaker row; `display_name` is only ever written by a human.

Rules that keep the result defensible:

* embeddings are only compared within the same model (they are not comparable across
  models or providers);
* a match below `VOICE_MATCH_THRESHOLD` produces no suggestion at all (abstain rather
  than guess);
* candidates are grouped by `person_reference` and each person is represented by their
  best print, so several prints of the SAME person reinforce each other instead of
  looking like two rival candidates;
* if the best and second-best *people* are closer together than `VOICE_MATCH_MARGIN`,
  the result is ambiguous and no suggestion is made;
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
    # How many prints of the winning person were compared. Recorded in the audit so a
    # decision can be re-read later knowing how much evidence backed it.
    person_print_count: int = 1


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

    # Group by person. Identity is `person_reference` - never the display name, because
    # two different people share a common name often enough that merging them would let
    # the matcher confidently suggest the wrong person.
    by_person: dict[str, tuple[float, VoiceEnrollment, int]] = {}
    for score, enr in scored:
        key = enr.person_reference
        best = by_person.get(key)
        if best is None:
            by_person[key] = (score, enr, 1)
        else:
            prev_score, prev_enr, count = best
            # The person's score is their BEST print; several prints of one person must
            # reinforce each other rather than compete.
            by_person[key] = (
                (score, enr, count + 1) if score > prev_score else (prev_score, prev_enr, count + 1)
            )

    ranked = sorted(by_person.values(), key=lambda x: x[0], reverse=True)
    top_score, top, print_count = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else None
    if top_score < threshold:
        return None
    # Two different enrolled PEOPLE sound similarly close to this voice: refuse to choose.
    if runner_up is not None and (top_score - runner_up) < margin:
        log.info("voice match ambiguous: %.3f vs %.3f (different people)", top_score, runner_up)
        return None
    return MatchResult(
        enrollment=top, score=top_score, runner_up=runner_up, person_print_count=print_count
    )


def _identify_row(
    db: Session,
    *,
    row: SessionSpeaker,
    embedding: list[float],
    enrollments: list[VoiceEnrollment],
    model: str,
    model_revision: str | None,
    session_id: uuid.UUID,
    user_id: uuid.UUID | None,
    now: datetime,
) -> bool:
    """Compare one speaker against the registry and record the outcome.

    Shared by result submission and re-scan so the two can never drift apart.
    Returns True when a suggestion was written. Callers must skip CONFIRMED/REJECTED
    rows before calling this - a human decision is final.
    """
    settings = get_settings()
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
        return False

    row.identification_status = IdentificationStatus.SUGGESTED
    row.suggested_name = match.enrollment.person_name
    row.suggested_enrollment_id = match.enrollment.id
    row.suggested_score = round(match.score, 4)
    row.suggested_model = model
    row.suggested_model_revision = model_revision
    row.suggested_at = now
    record_audit(
        db,
        action=AuditAction.VOICE_IDENTITY_SUGGESTED,
        user_id=user_id,
        entity_type="session_speaker",
        entity_id=row.id,
        metadata={
            "session_id": session_id,
            "speaker_label": row.speaker_label,
            "suggested_name": match.enrollment.person_name,
            # The enrolment id is recorded here because the column is ON DELETE SET NULL:
            # deleting a print must not erase which print a confirmation rested on.
            "enrollment_id": match.enrollment.id,
            "person_reference": match.enrollment.person_reference,
            "person_print_count": match.person_print_count,
            "score": round(match.score, 4),
            "runner_up": round(match.runner_up, 4) if match.runner_up is not None else None,
            "model": model,
            "model_revision": model_revision,
            "requires_confirmation": True,
        },
    )
    return True


def _active_enrollments(db: Session) -> list[VoiceEnrollment]:
    return list(db.scalars(select(VoiceEnrollment).where(VoiceEnrollment.is_active.is_(True))).all())


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
    try:
        model = voice.get("model") or ""
        speakers = voice.get("speakers") or {}
        if not model or not speakers:
            return 0
        enrollments = _active_enrollments(db)
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
            row.voice_embedding_model = model
            # A human decision is final: never overwrite a confirmed/rejected speaker.
            if row.identification_status in (IdentificationStatus.CONFIRMED, IdentificationStatus.REJECTED):
                continue
            if _identify_row(
                db,
                row=row,
                embedding=embedding,
                enrollments=enrollments,
                model=model,
                model_revision=voice.get("model_revision"),
                session_id=session_id,
                user_id=user_id,
                now=now,
            ):
                suggested += 1
        return suggested
    except Exception:  # noqa: BLE001
        log.exception("voice identification failed for session %s (transcript is unaffected)", session_id)
        return 0


def rematch_speakers(
    db: Session,
    *,
    session_ids: list[uuid.UUID] | None,
    user_id: uuid.UUID | None,
    only_undecided: bool = False,
) -> tuple[int, int, int]:
    """Re-run matching from embeddings already stored. Returns (sessions, scanned, suggested).

    Matching normally happens once, when the Local Agent submits its result. A voice
    enrolled afterwards would therefore never be applied to an existing session. This
    re-scan closes that gap using only data already in the database - no agent call, no
    audio, and no model inference.

    CONFIRMED and REJECTED rows are never touched: a human decision stands.
    """
    stmt = select(SessionSpeaker).where(SessionSpeaker.voice_embedding.is_not(None))
    if session_ids is not None:
        stmt = stmt.where(SessionSpeaker.session_id.in_(session_ids))
    if only_undecided:
        stmt = stmt.where(SessionSpeaker.identification_status == IdentificationStatus.NONE)

    rows = list(db.scalars(stmt).all())
    enrollments = _active_enrollments(db)
    now = datetime.now(timezone.utc)
    scanned = 0
    suggested = 0
    skipped_unknown_model = 0
    touched: set[uuid.UUID] = set()

    for row in rows:
        if row.identification_status in (IdentificationStatus.CONFIRMED, IdentificationStatus.REJECTED):
            continue
        embedding = list(row.voice_embedding or [])
        if not embedding:
            continue
        # An embedding is only comparable within the model that produced it, so a row
        # whose producing model was never recorded is skipped rather than guessed at.
        model = row.voice_embedding_model or row.suggested_model
        if not model:
            skipped_unknown_model += 1
            continue
        scanned += 1
        touched.add(row.session_id)
        if _identify_row(
            db,
            row=row,
            embedding=embedding,
            enrollments=enrollments,
            model=model,
            model_revision=row.suggested_model_revision,
            session_id=row.session_id,
            user_id=user_id,
            now=now,
        ):
            suggested += 1

    if skipped_unknown_model:
        log.info("re-scan skipped %d speaker(s) with no recorded embedding model", skipped_unknown_model)
    return len(touched), scanned, suggested
