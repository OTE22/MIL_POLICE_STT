"""Match speaker voice embeddings against the enrolment registry.

This is arithmetic, not inference: the model runs on the workstation and only the
resulting embedding reaches the central server. The outcome is always a *suggestion*
recorded on the speaker row; `display_name` is only ever written by a human.

Matching itself runs INSIDE PostgreSQL (pgvector): all probes of one recording go into a
single statement against every eligible enrolled print - one database operation for N
speakers, instead of N Python passes over the gallery.

Rules that keep the result defensible:

* embeddings are only compared within the same model (they are not comparable across
  models or providers);
* the gallery is GLOBAL: every active print with a canonical identity is a candidate,
  never filtered by session, subjects or recording - a person does not have to be on the
  case to be recognised;
* a match below `VOICE_MATCH_THRESHOLD` produces no suggestion at all (abstain rather
  than guess);
* candidates are grouped by canonical `identity_id` and each person is represented by their
  best print, so several prints of the SAME person reinforce each other instead of
  looking like two rival candidates;
* if the best and second-best *people* are closer together than `VOICE_MATCH_MARGIN`,
  the result is AMBIGUOUS and no suggestion is made;
* the score, model and revision are stored with every suggestion.

Every decision is logged with its scores (never the vectors): MATCHed, UNKNOWN, or
AMBIGUOUS, so a transcript's identification history can be reconstructed from the logs.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditAction, IdentificationStatus, PersonIdentity, SessionSpeaker, VoiceEnrollment
from app.services.audit import record_audit
from app.services.person_identity import resolve_identity

log = logging.getLogger(__name__)

# Decision outcomes. AMBIGUOUS and UNKNOWN persist identically (status NONE, no suggestion) -
# the distinction exists for the logs and for callers, not for storage.
DECISION_SUGGESTED = "SUGGESTED"
DECISION_UNKNOWN = "UNKNOWN"
DECISION_AMBIGUOUS = "AMBIGUOUS"


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


def _decide(top_score: float, runner_up: float | None, *, threshold: float, margin: float) -> str:
    """The one decision policy, shared by the SQL batch path and the in-memory path.

    Living in a single function is what stops the two paths drifting: the same scores must
    yield the same verdict whether they came from pgvector or from `best_match`.
    """
    if top_score < threshold:
        return DECISION_UNKNOWN
    # Two different enrolled PEOPLE sound similarly close to this voice: refuse to choose.
    if runner_up is not None and (top_score - runner_up) < margin:
        return DECISION_AMBIGUOUS
    return DECISION_SUGGESTED


def best_match(
    embedding: list[float],
    enrollments: list[VoiceEnrollment],
    *,
    model: str,
    threshold: float,
    margin: float,
) -> MatchResult | None:
    """Best enrolled voice for this embedding, or None when uncertain.

    In-memory reference implementation of exactly what the pgvector batch computes; kept
    because the decision rules are unit-tested through it with hand-built enrolments.
    """
    scored: list[tuple[float, VoiceEnrollment]] = []
    for enr in enrollments:
        if not enr.is_active or enr.model != model or enr.embedding_dim != len(embedding):
            continue
        if enr.identity_id is None:
            # Biometric evidence attributed to nobody. It cannot name a speaker, so it must
            # not compete in the ranking either - a rival with no person behind it can only
            # push a real match below the margin and turn a correct answer into an abstention.
            continue
        scored.append((cosine_similarity(embedding, list(enr.embedding)), enr))
    if not scored:
        return None

    # Group by canonical person. The key is `identity_id` from the person registry - never a
    # display name, and never the enrolment's own person_reference, which is only a snapshot
    # of what was recorded at enrolment time. Prints with no identity were dropped above, so
    # there is no other case to key on.
    by_person: dict[str, tuple[float, VoiceEnrollment, int]] = {}
    for score, enr in scored:
        key = str(enr.identity_id)
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
    decision = _decide(top_score, runner_up, threshold=threshold, margin=margin)
    if decision == DECISION_AMBIGUOUS:
        log.info("voice match ambiguous: %.3f vs %.3f (different people)", top_score, runner_up)
    if decision != DECISION_SUGGESTED:
        return None
    return MatchResult(
        enrollment=top, score=top_score, runner_up=runner_up, person_print_count=print_count
    )


@dataclass(frozen=True)
class VoiceMatchResult:
    """One probe's outcome from the batch matcher. Scores are None only for UNKNOWN
    with an empty candidate set (nothing eligible to score against)."""

    key: str
    decision: str  # DECISION_SUGGESTED | DECISION_UNKNOWN | DECISION_AMBIGUOUS
    identity_id: uuid.UUID | None
    enrollment_id: uuid.UUID | None
    score: float | None
    runner_up_identity_id: uuid.UUID | None
    runner_up_score: float | None
    print_count: int
    # How many enrolled IDENTITIES were eligible to compete for this probe.
    identity_candidates: int = 0


def batch_match_voice_embeddings(
    db: Session,
    probes: list[tuple[str, list[float]]],
    *,
    model: str,
    threshold: float | None = None,
    margin: float | None = None,
) -> list[VoiceMatchResult]:
    """All probes against the whole eligible gallery, in ONE SQL statement.

    The gallery filter is exactly: active, canonical identity present, same model, same
    dimension as the probe. Nothing session-, subject- or recording-shaped belongs in it -
    recognition is global within the deployment, and a person outside the current case must
    still be suggestible.

    pgvector's `<=>` is cosine distance, so similarity is `1 - distance` - the same number
    `cosine_similarity` computes (embeddings are stored L2-normalised; pgvector holds
    float4, so values agree to ~1e-7). Prints collapse to their best per identity, then
    identities are ranked and the top two returned per probe; the decision policy is the
    shared `_decide`, so this path and `best_match` cannot disagree.

    Probes may carry different dimensions (the contract allows 16-1024); each is only ever
    joined against prints of its own dimension, so `<=>` never sees a dim mismatch.
    """
    settings = get_settings()
    threshold = settings.voice_match_threshold if threshold is None else threshold
    margin = settings.voice_match_margin if margin is None else margin

    if not probes:
        return []

    values_sql = ", ".join(f"(:k{i}, :d{i}, CAST(:e{i} AS vector))" for i in range(len(probes)))
    params: dict[str, object] = {"model": model}
    for i, (key, emb) in enumerate(probes):
        params[f"k{i}"] = str(key)
        params[f"d{i}"] = len(emb)
        # vector's text input form. repr keeps full float precision through the cast.
        params[f"e{i}"] = "[" + ",".join(repr(float(x)) for x in emb) + "]"

    stmt = text(
        f"""
        WITH probes(key, dim, embedding) AS (VALUES {values_sql}),
        prints AS (
            SELECT p.key,
                   ve.identity_id,
                   ve.id AS enrollment_id,
                   1 - (ve.embedding <=> p.embedding) AS similarity,
                   ROW_NUMBER() OVER (
                       PARTITION BY p.key, ve.identity_id
                       ORDER BY ve.embedding <=> p.embedding ASC, ve.id
                   ) AS print_rank,
                   COUNT(*) OVER (PARTITION BY p.key, ve.identity_id) AS print_count
            FROM probes p
            JOIN voice_enrollments ve
              ON ve.is_active
             AND ve.identity_id IS NOT NULL
             AND ve.model = :model
             AND ve.embedding_dim = p.dim
        ),
        best_prints AS (SELECT * FROM prints WHERE print_rank = 1),
        ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY key ORDER BY similarity DESC, identity_id
                   ) AS identity_rank
            FROM best_prints
        )
        SELECT key, identity_id, enrollment_id, similarity, print_count, identity_rank
        FROM ranked
        ORDER BY key, identity_rank
        """
    )

    # The FULL ranking is fetched, not just the top two: the decision needs two, but the
    # logs need the whole field - "who else was close, and how close" is exactly what an
    # investigator asks when a suggestion surprises them. Galleries are small (deliberate
    # enrolments, not bulk data), so this costs nothing measurable.
    started = time.perf_counter()
    top: dict[str, tuple] = {}
    second: dict[str, tuple] = {}
    ranking: dict[str, list[tuple]] = {}
    pairs_scored = 0
    for key, identity_id, enrollment_id, similarity, print_count, identity_rank in db.execute(
        stmt, params
    ):
        ranking.setdefault(key, []).append((int(identity_rank), identity_id, float(similarity)))
        pairs_scored += int(print_count) if identity_rank == 1 else 0
        if identity_rank == 1:
            top[key] = (identity_id, enrollment_id, float(similarity), int(print_count))
        elif identity_rank == 2:
            second[key] = (identity_id, float(similarity))
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    identities = len({identity_id for rows in ranking.values() for _, identity_id, _ in rows})
    log.info(
        "voice batch: %d probe(s) x %d candidate identit%s (%d print comparison(s)) "
        "model=%s threshold=%.2f margin=%.2f in %dms",
        len(probes), identities, "y" if identities == 1 else "ies", pairs_scored,
        model, threshold, margin, elapsed_ms,
    )
    if log.isEnabledFor(logging.DEBUG):
        # The complete field per probe - identity ids and scores only, never vectors.
        for key, rows in ranking.items():
            listing = ", ".join(f"{rank}) {identity_id} {score:.4f}" for rank, identity_id, score in rows)
            log.debug("voice ranking probe=%s: %s", key, listing)

    results: list[VoiceMatchResult] = []
    for key, _emb in probes:
        key = str(key)
        if key not in top:
            # Nothing eligible to compare against - no candidates is UNKNOWN, never a
            # fabricated runner-up and never a fallback to anyone.
            results.append(
                VoiceMatchResult(key, DECISION_UNKNOWN, None, None, None, None, None, 0)
            )
            continue
        identity_id, enrollment_id, score, print_count = top[key]
        runner_identity, runner_score = second.get(key, (None, None))
        decision = _decide(score, runner_score, threshold=threshold, margin=margin)
        results.append(
            VoiceMatchResult(
                key=key,
                decision=decision,
                identity_id=identity_id,
                enrollment_id=enrollment_id,
                score=score,
                runner_up_identity_id=runner_identity,
                runner_up_score=runner_score,
                print_count=print_count,
                identity_candidates=len(ranking.get(key, [])),
            )
        )
    return results


def _apply_match_outcome(
    db: Session,
    *,
    row: SessionSpeaker,
    result: VoiceMatchResult,
    model: str,
    model_revision: str | None,
    user_id: uuid.UUID | None,
    now: datetime,
) -> bool:
    """Record one probe's outcome on its speaker row. Returns True when a suggestion landed.

    Shared by result submission and re-scan so the two can never drift apart. Callers must
    skip CONFIRMED/REJECTED rows before calling this - a human decision is final, and a
    biometric verdict (including a non-match) must never touch `identity_id`,
    `display_name` or `reference_number`: those belong to the human workflow.
    """
    settings = get_settings()
    log.info(
        "voice decision session=%s recording=%s speaker=%s source=%s decision=%s "
        "best_identity=%s best=%s runner_up=%s threshold=%.2f margin=%.2f prints=%d candidates=%d",
        row.session_id,
        row.recording_id,
        row.speaker_label,
        row.source_label,
        result.decision,
        result.identity_id,
        f"{result.score:.4f}" if result.score is not None else "-",
        f"{result.runner_up_score:.4f}" if result.runner_up_score is not None else "-",
        settings.voice_match_threshold,
        settings.voice_match_margin,
        result.print_count,
        result.identity_candidates,
    )

    if result.decision != DECISION_SUGGESTED:
        row.identification_status = IdentificationStatus.NONE
        row.suggested_name = None
        row.suggested_enrollment_id = None
        row.suggested_score = None
        return False

    # Matching dropped prints without an identity, so there is one here - and it is resolved
    # through any merge, so a suggestion never offers the name of an alias that has since been
    # consolidated into someone else.
    identity = resolve_identity(db, db.get(PersonIdentity, result.identity_id))
    if identity is None:  # pragma: no cover - the row would have to vanish mid-request
        row.identification_status = IdentificationStatus.NONE
        return False
    canonical_name = identity.person_name

    row.identification_status = IdentificationStatus.SUGGESTED
    row.suggested_name = canonical_name
    row.suggested_enrollment_id = result.enrollment_id
    row.suggested_score = round(result.score, 4)
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
            "session_id": row.session_id,
            "recording_id": row.recording_id,
            "speaker_label": row.speaker_label,
            "source_label": row.source_label,
            "suggested_name": canonical_name,
            # The enrolment id is recorded here because the column is ON DELETE SET NULL:
            # deleting a print must not erase which print a confirmation rested on.
            "enrollment_id": result.enrollment_id,
            "identity_id": result.identity_id,
            "person_reference": identity.reference_display,
            "person_print_count": result.print_count,
            "score": round(result.score, 4),
            "runner_up": round(result.runner_up_score, 4) if result.runner_up_score is not None else None,
            "model": model,
            "model_revision": model_revision,
            "requires_confirmation": True,
        },
    )
    return True


def apply_voice_identification(
    db: Session,
    *,
    session_id: uuid.UUID,
    recording_id: uuid.UUID | None,
    label_map: dict[str, str] | None,
    voice: dict | None,
    user_id: uuid.UUID | None,
) -> int:
    """Store this recording's probe embeddings and batch-match them. Returns #suggestions.

    Called when a Local Agent submits a result. Never raises: identification is an
    optional convenience and must not fail the synchronization of a transcript.

    `label_map` translates the agent's recording-local labels (its SPEAKER_00) to the
    session-wide labels the server allocated for THIS recording's observations. Resolving
    through it is what guarantees a probe can only ever land on a row that belongs to this
    recording - recording B's SPEAKER_00 no longer even resolves to recording A's row, let
    alone overwrites its embedding.
    """
    if not voice:
        return 0
    try:
        model = voice.get("model") or ""
        speakers = voice.get("speakers") or {}
        if not model or not speakers:
            return 0
        rows_by_label = {
            s.speaker_label: s
            for s in db.scalars(
                select(SessionSpeaker).where(SessionSpeaker.session_id == session_id)
            ).all()
        }
        now = datetime.now(timezone.utc)
        probes: list[tuple[str, list[float]]] = []
        probe_rows: dict[str, SessionSpeaker] = {}
        for local_label, payload in speakers.items():
            visible = (label_map or {}).get(local_label, local_label)
            row = rows_by_label.get(visible)
            if row is None:
                continue
            # Defence in depth behind the label_map: even if resolution ever regressed, a
            # probe from this recording must not touch an observation owned by another.
            if (
                recording_id is not None
                and row.recording_id is not None
                and row.recording_id != recording_id
            ):
                log.warning(
                    "voice probe for %s ignored: row %s belongs to recording %s, not %s",
                    local_label,
                    row.speaker_label,
                    row.recording_id,
                    recording_id,
                )
                continue
            embedding = list(payload.get("embedding") or [])
            if not embedding:
                continue
            # A human decision is final: never overwrite a confirmed/rejected speaker -
            # including its stored voiceprint, which by then may back an enrolment.
            if row.identification_status in (IdentificationStatus.CONFIRMED, IdentificationStatus.REJECTED):
                log.debug(
                    "probe skipped speaker=%s (source=%s): human decision %s is final",
                    row.speaker_label, local_label, row.identification_status.value,
                )
                continue
            row.voice_embedding = embedding
            row.voice_embedding_model = model
            log.debug(
                "probe stored session=%s recording=%s speaker=%s (source=%s) dim=%d model=%s seconds=%s",
                session_id, recording_id, row.speaker_label, local_label,
                len(embedding), model, payload.get("seconds"),
            )
            probes.append((str(row.id), embedding))
            probe_rows[str(row.id)] = row

        if not probes:
            return 0
        results = batch_match_voice_embeddings(db, probes, model=model)
        suggested = 0
        for result in results:
            if _apply_match_outcome(
                db,
                row=probe_rows[result.key],
                result=result,
                model=model,
                model_revision=voice.get("model_revision"),
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
    audio, and no model inference. Rows are batched per producing model through the same
    pgvector statement as submission, so the two paths cannot drift.

    CONFIRMED and REJECTED rows are never touched: a human decision stands.
    """
    stmt = select(SessionSpeaker).where(SessionSpeaker.voice_embedding.is_not(None))
    if session_ids is not None:
        stmt = stmt.where(SessionSpeaker.session_id.in_(session_ids))
    if only_undecided:
        stmt = stmt.where(SessionSpeaker.identification_status == IdentificationStatus.NONE)

    rows = list(db.scalars(stmt).all())
    now = datetime.now(timezone.utc)
    scanned = 0
    suggested = 0
    skipped_unknown_model = 0
    touched: set[uuid.UUID] = set()
    by_model: dict[str, list[SessionSpeaker]] = {}

    for row in rows:
        if row.identification_status in (IdentificationStatus.CONFIRMED, IdentificationStatus.REJECTED):
            continue
        if not list(row.voice_embedding or []):
            continue
        # An embedding is only comparable within the model that produced it, so a row
        # whose producing model was never recorded is skipped rather than guessed at.
        model = row.voice_embedding_model or row.suggested_model
        if not model:
            skipped_unknown_model += 1
            continue
        scanned += 1
        touched.add(row.session_id)
        by_model.setdefault(model, []).append(row)

    for model, group in by_model.items():
        probes = [(str(row.id), list(row.voice_embedding)) for row in group]
        rows_by_key = {str(row.id): row for row in group}
        for result in batch_match_voice_embeddings(db, probes, model=model):
            row = rows_by_key[result.key]
            if _apply_match_outcome(
                db,
                row=row,
                result=result,
                model=model,
                model_revision=row.suggested_model_revision,
                user_id=user_id,
                now=now,
            ):
                suggested += 1

    if skipped_unknown_model:
        log.info("re-scan skipped %d speaker(s) with no recorded embedding model", skipped_unknown_model)
    return len(touched), scanned, suggested
