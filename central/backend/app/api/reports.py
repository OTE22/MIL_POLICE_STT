"""محضر تحقيق: the composer's API (draft, Q&A editing, refresh).

Every route is session-scoped through `get_accessible_session`, so a user who cannot open
the investigation cannot reach its report either, and permission is checked BEFORE anything
is mutated. Finalization, the archive and the template registry live in their own modules.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import client_ip, get_accessible_session, require_permission
from app.db.session import get_db
from app.models import (
    AudioRecording,
    AuditAction,
    FushaStatus,
    GeneratedReport,
    InvestigationSession,
    ReportDraft,
    ReportQABlock,
    ReportStatus,
    Transcript,
    TranscriptSourceMode,
    User,
)
from app.schemas.reports import (
    FushaDecisionIn,
    GeneratedReportOut,
    ReportArchiveOut,
    ReportVerificationOut,
    FushaSuggestIn,
    LLMCapabilitiesBrief,
    QABlockOut,
    QABlockUpdateIn,
    QAExcludeIn,
    QAMergeIn,
    QASplitIn,
    RecordingOptionOut,
    ReportDraftOut,
    ReportDraftUpdateIn,
    ReportSpeakerOut,
    StalePinOut,
)
from app.services.audit import record_audit
from app.services.llm import ArabicFormalizationService, FormalizationUnavailable, source_hash
from app.services.report_finalize import (
    FinalizationRefused,
    Preflight,
    check_ready,
    finalize,
    verify,
)
from app.services.report_storage import absolute_path as report_file_path
from app.services.report_renderer import RenderError
from app.services.report_context import completed_recordings, speaker_map
from app.services.report_draft import (
    DraftIsFinal,
    create_draft,
    draft_is_stale,
    edit_block,
    exclude_block,
    get_draft,
    merge_blocks,
    refresh_draft,
    require_editable,
    restore_block,
    set_recordings,
    set_source_mode,
    split_block,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["reports"])

# Header fields an official محضر cannot be issued without. Reported while drafting so the
# gap is visible early, and enforced again at finalization.
REQUIRED_FIELD_LABELS = {
    "report_number": "رقم المحضر",
    "case_subject": "موضوع القضية",
    "location": "مكان التحقيق",
}


def _missing_fields(draft: ReportDraft) -> list[str]:
    return [
        label
        for field, label in REQUIRED_FIELD_LABELS.items()
        if not (getattr(draft, field) or "").strip()
    ]


def _block_out(block: ReportQABlock, speakers_by_id: dict) -> QABlockOut:
    q_info = speakers_by_id.get(block.question_speaker_id)
    a_info = speakers_by_id.get(block.answer_speaker_id)
    return QABlockOut(
        id=block.id,
        sequence=block.sequence,
        question_source_text=block.question_source_text,
        answer_source_text=block.answer_source_text,
        report_question_text=block.report_question_text,
        report_answer_text=block.report_answer_text,
        question_speaker_id=block.question_speaker_id,
        answer_speaker_id=block.answer_speaker_id,
        question_speaker_name=q_info.report_name() if q_info else None,
        answer_speaker_name=a_info.report_name() if a_info else None,
        answer_speaker_resolved=bool(a_info and a_info.resolved),
        source_segment_ids=[str(s) for s in (block.source_segment_ids or [])],
        source_recording_ids=[str(r) for r in (block.source_recording_ids or [])],
        start_seconds=block.start_seconds,
        end_seconds=block.end_seconds,
        included_in_report=block.included_in_report,
        exclusion_reason=block.exclusion_reason,
        fusha_status=block.fusha_status,
        llm_suggested_question=block.llm_suggested_question,
        llm_suggested_answer=block.llm_suggested_answer,
        edited_at=block.edited_at,
    )


def _draft_out(db: Session, session: InvestigationSession, draft: ReportDraft) -> ReportDraftOut:
    speakers = speaker_map(db, session.id)
    by_id = {info.speaker_id: info for info in speakers.values()}
    selected = {str(r) for r in (draft.selected_recording_ids or [])}

    transcribed = set(
        db.scalars(select(Transcript.recording_id).where(Transcript.session_id == session.id)).all()
    )
    recordings = []
    for index, rec in enumerate(
        db.scalars(
            select(AudioRecording)
            .where(AudioRecording.session_id == session.id)
            .order_by(AudioRecording.created_at)
        ).all(),
        start=1,
    ):
        recordings.append(
            RecordingOptionOut(
                id=rec.id,
                index=index,
                original_filename=rec.original_filename,
                duration_seconds=float(rec.duration_seconds) if rec.duration_seconds is not None else None,
                created_at=rec.created_at,
                has_transcript=rec.id in transcribed,
                selected=str(rec.id) in selected,
            )
        )

    speaker_rows = [
        ReportSpeakerOut(
            id=info.speaker_id,
            speaker_label=info.speaker_label,
            source_label=info.source_label,
            recording_id=info.recording_id,
            role=info.role.value,
            display_name=info.display_name,
            person_name=info.person_name,
            resolved=info.resolved,
            legacy=info.legacy,
            report_name=info.report_name(),
        )
        for info in sorted(speakers.values(), key=lambda i: i.speaker_label)
    ]

    # Only speakers who actually SAY something in the selected recordings matter here - an
    # unidentified voice in a recording nobody included cannot block this report.
    speaking_ids = {
        sid
        for block in draft.qa_blocks
        if block.included_in_report
        for sid in (block.question_speaker_id, block.answer_speaker_id)
        if sid
    }
    unresolved = sorted(
        by_id[sid].speaker_label for sid in speaking_ids if sid in by_id and not by_id[sid].resolved
    )

    version_count = int(
        db.scalar(
            select(func.count(GeneratedReport.id)).where(GeneratedReport.session_id == session.id)
        )
        or 0
    )

    # Cheap: hardware detection is cached at startup, so this is a couple of attribute reads.
    fusha = ArabicFormalizationService()
    fusha_info = fusha.info()

    return ReportDraftOut(
        id=draft.id,
        session_id=draft.session_id,
        status=draft.status,
        report_number=draft.report_number,
        case_subject=draft.case_subject,
        report_date=draft.report_date,
        report_time=draft.report_time,
        location=draft.location,
        intro_text=draft.intro_text,
        closing_text=draft.closing_text,
        transcript_source_mode=draft.transcript_source_mode,
        unresolved_ack=draft.unresolved_ack,
        updated_at=draft.updated_at,
        qa_blocks=[
            _block_out(b, by_id) for b in sorted(draft.qa_blocks, key=lambda b: b.sequence)
        ],
        recordings=recordings,
        speakers=speaker_rows,
        stale=[
            StalePinOut(
                recording_id=uuid.UUID(p["recording_id"]),
                transcript_id=uuid.UUID(p["transcript_id"]),
                reason=p["reason"],
            )
            for p in draft_is_stale(db, draft)
        ],
        missing_fields=_missing_fields(draft),
        unresolved_speaker_labels=unresolved,
        report_version_count=version_count,
        llm=LLMCapabilitiesBrief(
            available=fusha.available(),
            provider=fusha_info.provider,
            model=fusha_info.model,
            fallback_reason=fusha_info.fallback_reason,
        ),
    )


def _require_draft(db: Session, session: InvestigationSession) -> ReportDraft:
    draft = get_draft(db, session.id)
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="report_draft_not_found")
    return draft


def _require_block(db: Session, draft: ReportDraft, block_id: uuid.UUID) -> ReportQABlock:
    block = db.get(ReportQABlock, block_id)
    if block is None or block.draft_id != draft.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="report_block_not_found")
    return block


def _guard_editable(draft: ReportDraft) -> None:
    try:
        require_editable(draft)
    except DraftIsFinal as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="report_is_final") from exc


# --------------------------------------------------------------------------- draft


@router.get("/investigations/{session_id}/report", response_model=ReportDraftOut)
def get_report_draft(
    session: InvestigationSession = Depends(get_accessible_session),
    _: User = Depends(require_permission("reports.read", "reports.generate")),
    db: Session = Depends(get_db),
) -> ReportDraftOut:
    return _draft_out(db, session, _require_draft(db, session))


@router.post("/investigations/{session_id}/report", response_model=ReportDraftOut, status_code=201)
def create_report_draft(
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.generate")),
    db: Session = Depends(get_db),
) -> ReportDraftOut:
    """Open the composer for the first time: select every transcribed recording and build
    the س/ج draft. Opening it again returns what is already there - never a second draft."""
    existing = get_draft(db, session.id)
    if existing is not None:
        return _draft_out(db, session, existing)

    if not completed_recordings(db, session.id):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="report_no_transcripts")

    draft = create_draft(db, session.id, user.id)
    record_audit(
        db,
        action=AuditAction.REPORT_DRAFT_CREATED,
        user_id=user.id,
        entity_type="report_draft",
        entity_id=draft.id,
        metadata={
            "session_id": session.id,
            "recordings": len(draft.selected_recording_ids or []),
            "qa_blocks": len(draft.qa_blocks),
        },
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(draft)
    log.info(
        "report draft created session=%s draft=%s recordings=%d blocks=%d",
        session.session_number, draft.id, len(draft.selected_recording_ids or []), len(draft.qa_blocks),
    )
    return _draft_out(db, session, draft)


@router.put("/investigations/{session_id}/report", response_model=ReportDraftOut)
def update_report_draft(
    body: ReportDraftUpdateIn,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.generate")),
    db: Session = Depends(get_db),
) -> ReportDraftOut:
    draft = _require_draft(db, session)
    _guard_editable(draft)

    fields = body.model_dump(exclude_unset=True)
    for field in ("report_number", "case_subject", "report_date", "report_time", "location", "intro_text", "closing_text"):
        if field in fields:
            value = fields[field]
            setattr(draft, field, value.strip() if isinstance(value, str) else value)

    if "unresolved_ack" in fields:
        draft.unresolved_ack = bool(fields["unresolved_ack"])
        draft.unresolved_ack_by = user.id if draft.unresolved_ack else None
        draft.unresolved_ack_at = func.now() if draft.unresolved_ack else None

    # Selection and text mode change WHAT is quoted, so each rebuilds the dialogue. Applied
    # after the header fields so one request can do both.
    if fields.get("selected_recording_ids") is not None:
        chosen = [uuid.UUID(str(r)) for r in fields["selected_recording_ids"]]
        available = {r.id for r in completed_recordings(db, session.id)}
        unknown = [str(r) for r in chosen if r not in available]
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "report_recording_not_available", "recording_ids": unknown},
            )
        if not chosen:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="report_no_recordings_selected")
        set_recordings(db, draft, chosen, user.id)

    if fields.get("transcript_source_mode") is not None:
        set_source_mode(db, draft, TranscriptSourceMode(fields["transcript_source_mode"]), user.id)

    draft.updated_by = user.id
    record_audit(
        db,
        action=AuditAction.REPORT_DRAFT_UPDATED,
        user_id=user.id,
        entity_type="report_draft",
        entity_id=draft.id,
        metadata={"fields": sorted(fields.keys()), "session_id": session.id},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(draft)
    return _draft_out(db, session, draft)


@router.post("/investigations/{session_id}/report/refresh", response_model=ReportDraftOut)
def refresh_report_draft(
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.generate")),
    db: Session = Depends(get_db),
) -> ReportDraftOut:
    """تحديث من النص المنقح - rebuild from the current transcripts, discarding the wording
    in the draft. Explicit and audited: a transcript edit never does this by itself."""
    draft = _require_draft(db, session)
    _guard_editable(draft)
    before = len(draft.qa_blocks)
    refresh_draft(db, draft, user.id)
    record_audit(
        db,
        action=AuditAction.REPORT_DRAFT_REFRESHED,
        user_id=user.id,
        entity_type="report_draft",
        entity_id=draft.id,
        metadata={"blocks_before": before, "blocks_after": len(draft.qa_blocks), "session_id": session.id},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(draft)
    log.info("report draft refreshed draft=%s blocks %d -> %d", draft.id, before, len(draft.qa_blocks))
    return _draft_out(db, session, draft)


# --------------------------------------------------------------------------- Q&A blocks


@router.patch("/investigations/{session_id}/report/blocks/{block_id}", response_model=ReportDraftOut)
def update_block(
    block_id: uuid.UUID,
    body: QABlockUpdateIn,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.generate")),
    db: Session = Depends(get_db),
) -> ReportDraftOut:
    draft = _require_draft(db, session)
    _guard_editable(draft)
    block = _require_block(db, draft, block_id)
    fields = body.model_dump(exclude_unset=True)
    edit_block(
        db,
        block,
        question=fields.get("report_question_text"),
        answer=fields.get("report_answer_text"),
        user_id=user.id,
    )
    record_audit(
        db,
        action=AuditAction.REPORT_QA_EDITED,
        user_id=user.id,
        entity_type="report_qa_block",
        entity_id=block.id,
        metadata={"draft_id": draft.id, "sequence": block.sequence, "fields": sorted(fields.keys())},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(draft)
    return _draft_out(db, session, draft)


@router.post("/investigations/{session_id}/report/blocks/{block_id}/exclude", response_model=ReportDraftOut)
def exclude_qa_block(
    block_id: uuid.UUID,
    body: QAExcludeIn,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.generate")),
    db: Session = Depends(get_db),
) -> ReportDraftOut:
    """Leave this exchange out of the printed document. The transcript keeps every word."""
    draft = _require_draft(db, session)
    _guard_editable(draft)
    block = _require_block(db, draft, block_id)
    exclude_block(db, block, body.reason, user.id)
    record_audit(
        db,
        action=AuditAction.REPORT_QA_EXCLUDED,
        user_id=user.id,
        entity_type="report_qa_block",
        entity_id=block.id,
        metadata={"draft_id": draft.id, "sequence": block.sequence, "reason": body.reason},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(draft)
    return _draft_out(db, session, draft)


@router.post("/investigations/{session_id}/report/blocks/{block_id}/restore", response_model=ReportDraftOut)
def restore_qa_block(
    block_id: uuid.UUID,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.generate")),
    db: Session = Depends(get_db),
) -> ReportDraftOut:
    draft = _require_draft(db, session)
    _guard_editable(draft)
    block = _require_block(db, draft, block_id)
    restore_block(db, block, user.id)
    record_audit(
        db,
        action=AuditAction.REPORT_QA_RESTORED,
        user_id=user.id,
        entity_type="report_qa_block",
        entity_id=block.id,
        metadata={"draft_id": draft.id, "sequence": block.sequence},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(draft)
    return _draft_out(db, session, draft)


@router.post("/investigations/{session_id}/report/blocks/{block_id}/merge", response_model=ReportDraftOut)
def merge_qa_blocks(
    block_id: uuid.UUID,
    body: QAMergeIn,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.generate")),
    db: Session = Depends(get_db),
) -> ReportDraftOut:
    draft = _require_draft(db, session)
    _guard_editable(draft)
    first = _require_block(db, draft, block_id)
    second = _require_block(db, draft, body.with_block_id)
    try:
        merged = merge_blocks(db, first, second, user.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"report_{exc}") from exc
    record_audit(
        db,
        action=AuditAction.REPORT_QA_EDITED,
        user_id=user.id,
        entity_type="report_qa_block",
        entity_id=merged.id,
        metadata={"draft_id": draft.id, "operation": "merge"},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(draft)
    return _draft_out(db, session, draft)


@router.post("/investigations/{session_id}/report/reopen", response_model=ReportDraftOut)
def reopen_report_draft(
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.generate")),
    db: Session = Depends(get_db),
) -> ReportDraftOut:
    """Reopen a FINAL محضر for correction. The issued versions are untouched.

    Correcting an official document does not edit it - it supersedes it. Reopening returns
    the DRAFT to an editable state so the next finalization produces version N+1, while
    every version already issued stays on file, downloadable and hash-verifiable.
    """
    draft = _require_draft(db, session)
    if draft.status is not ReportStatus.FINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="report_not_final")

    issued = int(
        db.scalar(
            select(func.count(GeneratedReport.id)).where(GeneratedReport.session_id == session.id)
        )
        or 0
    )
    draft.status = ReportStatus.DRAFT
    draft.updated_by = user.id
    record_audit(
        db,
        action=AuditAction.REPORT_DRAFT_REOPENED,
        user_id=user.id,
        entity_type="report_draft",
        entity_id=draft.id,
        metadata={"session_id": session.id, "issued_versions": issued},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(draft)
    log.info(
        "report draft reopened session=%s (%d issued version(s) remain immutable)",
        session.session_number, issued,
    )
    return _draft_out(db, session, draft)


# --------------------------------------------------------------------------- الصياغة بالفصحى
#
# The AI never writes the report. It offers a rewording; a human approves, edits or rejects
# it, and only that decision touches `report_*_text`. That order is the invariant here -
# there is deliberately no code path from a suggestion to printed text without a person.


@router.post("/investigations/{session_id}/report/blocks/{block_id}/fusha", response_model=ReportDraftOut)
def suggest_fusha(
    block_id: uuid.UUID,
    body: FushaSuggestIn,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.generate")),
    db: Session = Depends(get_db),
) -> ReportDraftOut:
    """Request a Modern-Standard-Arabic suggestion for this block. Stores it beside the
    current wording; changes nothing that will be printed."""
    draft = _require_draft(db, session)
    _guard_editable(draft)
    block = _require_block(db, draft, block_id)

    service = ArabicFormalizationService()
    if not service.available():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "fusha_unavailable", "reason": service.info().fallback_reason},
        )

    suggestions: dict[str, str] = {}
    provenance: dict | None = None
    try:
        if body.question and (block.report_question_text or "").strip():
            result = service.formalize(block.report_question_text or "")
            suggestions["question"] = result.suggested_text
            provenance = result.provenance()
        if body.answer and (block.report_answer_text or "").strip():
            result = service.formalize(block.report_answer_text or "")
            suggestions["answer"] = result.suggested_text
            provenance = result.provenance()
    except FormalizationUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "fusha_unavailable", "reason": exc.reason},
        ) from exc

    if not suggestions:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="fusha_nothing_to_formalize")

    if "question" in suggestions:
        block.llm_suggested_question = suggestions["question"]
    if "answer" in suggestions:
        block.llm_suggested_answer = suggestions["answer"]
    block.fusha_status = FushaStatus.AI_SUGGESTED
    # Provenance binds the suggestion to the text it was made for; the hashes are per-half,
    # so the composer can tell a stale suggestion from a current one.
    block.llm_provenance = {
        **(provenance or {}),
        "question_source_hash": source_hash(block.report_question_text or ""),
        "answer_source_hash": source_hash(block.report_answer_text or ""),
    }

    record_audit(
        db,
        action=AuditAction.REPORT_FUSHA_REQUESTED,
        user_id=user.id,
        entity_type="report_qa_block",
        entity_id=block.id,
        metadata={
            "draft_id": draft.id,
            "sequence": block.sequence,
            "halves": sorted(suggestions.keys()),
            "provider": (provenance or {}).get("provider"),
            "model": (provenance or {}).get("model"),
        },
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(draft)
    return _draft_out(db, session, draft)


@router.post(
    "/investigations/{session_id}/report/blocks/{block_id}/fusha/decision", response_model=ReportDraftOut
)
def decide_fusha(
    block_id: uuid.UUID,
    body: FushaDecisionIn,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.generate")),
    db: Session = Depends(get_db),
) -> ReportDraftOut:
    """اعتماد / تعديل / رفض. The ONLY way a suggestion can become printed text."""
    draft = _require_draft(db, session)
    _guard_editable(draft)
    block = _require_block(db, draft, block_id)

    if block.fusha_status is FushaStatus.NOT_REQUESTED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="fusha_no_suggestion")

    if not body.accept:
        block.fusha_status = FushaStatus.REJECTED
        # The suggestion stays on the record: the trail shows what was offered and refused.
        record_audit(
            db,
            action=AuditAction.REPORT_FUSHA_REJECTED,
            user_id=user.id,
            entity_type="report_qa_block",
            entity_id=block.id,
            metadata={"draft_id": draft.id, "sequence": block.sequence},
            ip_address=client_ip(request),
        )
        db.commit()
        db.refresh(draft)
        return _draft_out(db, session, draft)

    # Accepting: either the suggestion verbatim, or the human's own edit of it.
    question = body.report_question_text
    answer = body.report_answer_text
    edited = question is not None or answer is not None
    if question is None:
        question = block.llm_suggested_question or block.report_question_text
    if answer is None:
        answer = block.llm_suggested_answer or block.report_answer_text

    block.report_question_text = question
    block.report_answer_text = answer
    block.fusha_status = FushaStatus.HUMAN_EDITED if edited else FushaStatus.APPROVED
    block.edited_by = user.id
    block.edited_at = datetime.now(timezone.utc)
    block.llm_provenance = {
        **(block.llm_provenance or {}),
        "approved_by": str(user.id),
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "approved_with_edit": edited,
    }

    record_audit(
        db,
        action=AuditAction.REPORT_FUSHA_APPROVED,
        user_id=user.id,
        entity_type="report_qa_block",
        entity_id=block.id,
        metadata={"draft_id": draft.id, "sequence": block.sequence, "edited": edited},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(draft)
    return _draft_out(db, session, draft)


@router.post("/investigations/{session_id}/report/blocks/{block_id}/split", response_model=ReportDraftOut)
def split_qa_block(
    block_id: uuid.UUID,
    body: QASplitIn,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.generate")),
    db: Session = Depends(get_db),
) -> ReportDraftOut:
    draft = _require_draft(db, session)
    _guard_editable(draft)
    block = _require_block(db, draft, block_id)
    split_block(db, block, body.answer_head, body.answer_tail, user.id)
    record_audit(
        db,
        action=AuditAction.REPORT_QA_EDITED,
        user_id=user.id,
        entity_type="report_qa_block",
        entity_id=block.id,
        metadata={"draft_id": draft.id, "operation": "split"},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(draft)
    return _draft_out(db, session, draft)


# --------------------------------------------------------------------------- issuing
#
# A finalized محضر is a document that leaves the building. It is rendered from an immutable
# snapshot, hashed, archived, and never overwritten - a correction becomes a new version.


def _report_out(db: Session, report: GeneratedReport) -> GeneratedReportOut:
    from app.models import ReportTemplateVersion

    template = (
        db.get(ReportTemplateVersion, report.template_version_id)
        if report.template_version_id
        else None
    )
    author = db.get(User, report.generated_by) if report.generated_by else None
    return GeneratedReportOut(
        id=report.id,
        report_version=report.report_version,
        report_number=report.report_number,
        template_version=template.version if template else None,
        template_is_development=bool(template and template.is_development),
        docx_sha256=report.docx_sha256,
        context_sha256=report.context_sha256,
        template_sha256=report.template_sha256,
        size_bytes=report.size_bytes,
        qa_block_count=report.qa_block_count,
        transcript_source_mode=report.transcript_source_mode,
        selected_recording_ids=[str(r) for r in (report.selected_recording_ids or [])],
        pinned_transcripts=list(report.pinned_transcripts or []),
        generated_by=report.generated_by,
        generated_by_name=(
            (author.profile.full_name if author and author.profile else None)
            or (author.username if author else None)
        ),
        created_at=report.created_at,
    )


def _archive_out(db: Session, session: InvestigationSession) -> ReportArchiveOut:
    from app.api.report_templates import active_template

    reports = db.scalars(
        select(GeneratedReport)
        .where(GeneratedReport.session_id == session.id)
        .order_by(GeneratedReport.report_version.desc())
    ).all()

    template = active_template(db)
    draft = get_draft(db, session.id)
    if draft is None:
        preflight = Preflight(missing_fields=[], unresolved_labels=[], blocked=["report_draft_not_found"])
    else:
        preflight = check_ready(db, session, draft, template)

    return ReportArchiveOut(
        reports=[_report_out(db, r) for r in reports],
        can_finalize=not (preflight.blocked or preflight.missing_fields),
        blocked_reasons=preflight.blocked,
        missing_fields=preflight.missing_fields,
        unresolved_speaker_labels=preflight.unresolved_labels,
        active_template_version=template.version if template else None,
        active_template_is_development=bool(template and template.is_development),
    )


@router.get("/investigations/{session_id}/reports", response_model=ReportArchiveOut)
def list_reports(
    session: InvestigationSession = Depends(get_accessible_session),
    _: User = Depends(require_permission("reports.read", "reports.generate")),
    db: Session = Depends(get_db),
) -> ReportArchiveOut:
    return _archive_out(db, session)


@router.post("/investigations/{session_id}/reports", response_model=ReportArchiveOut, status_code=201)
def finalize_report(
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.finalize")),
    db: Session = Depends(get_db),
) -> ReportArchiveOut:
    """إنشاء المحضر النهائي - validate, freeze, render, hash, archive."""
    from app.api.report_templates import active_template

    draft = _require_draft(db, session)
    template = active_template(db)
    try:
        report = finalize(db, session, draft, template, user)
    except FinalizationRefused as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": exc.code, **exc.detail}
        ) from exc
    except RenderError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.code) from exc

    record_audit(
        db,
        action=AuditAction.REPORT_GENERATED,
        user_id=user.id,
        entity_type="generated_report",
        entity_id=report.id,
        metadata={
            "session_id": session.id,
            "version": report.report_version,
            "template_version_id": report.template_version_id,
            "docx_sha256": report.docx_sha256,
            "context_sha256": report.context_sha256,
            "qa_blocks": report.qa_block_count,
            "source_mode": report.transcript_source_mode,
        },
        ip_address=client_ip(request),
    )
    db.commit()
    return _archive_out(db, session)


def _require_report(db: Session, session: InvestigationSession, report_id: uuid.UUID) -> GeneratedReport:
    report = db.get(GeneratedReport, report_id)
    if report is None or report.session_id != session.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="report_not_found")
    return report


@router.get("/investigations/{session_id}/reports/{report_id}/file")
def download_report(
    report_id: uuid.UUID,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.read", "reports.generate")),
    db: Session = Depends(get_db),
) -> FileResponse:
    report = _require_report(db, session, report_id)
    path = report_file_path(report.storage_path)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="report_file_missing")

    # Audited and committed BEFORE the file leaves: who took a copy of an official document
    # is part of its record, and a response whose audit failed must not hand one out.
    record_audit(
        db,
        action=AuditAction.REPORT_DOWNLOADED,
        user_id=user.id,
        entity_type="generated_report",
        entity_id=report.id,
        metadata={"session_id": session.id, "version": report.report_version},
        ip_address=client_ip(request),
    )
    db.commit()

    number = (report.report_number or str(report.report_version)).replace("/", "-")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"mahdar-{number}-v{report.report_version}.docx",
        content_disposition_type="attachment",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/investigations/{session_id}/reports/{report_id}/verify", response_model=ReportVerificationOut)
def verify_report(
    report_id: uuid.UUID,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("reports.read", "reports.generate")),
    db: Session = Depends(get_db),
) -> ReportVerificationOut:
    """Recompute the three hashes: سليم / غير مطابق. Integrity, not a signature."""
    report = _require_report(db, session, report_id)
    result = verify(db, report)
    record_audit(
        db,
        action=AuditAction.REPORT_VERIFIED,
        user_id=user.id,
        entity_type="generated_report",
        entity_id=report.id,
        metadata={"session_id": session.id, "version": report.report_version, "ok": result.ok},
        ip_address=client_ip(request),
    )
    db.commit()
    return ReportVerificationOut(
        report_id=report.id,
        ok=result.ok,
        docx_ok=result.docx_ok,
        context_ok=result.context_ok,
        template_ok=result.template_ok,
        detail=result.detail,
    )
