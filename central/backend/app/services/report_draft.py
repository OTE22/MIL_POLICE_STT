"""The investigator's working محضر: build it, refresh it deliberately, edit its Q&A.

Every function here writes to report tables ONLY. The evidence - recordings, transcripts,
segments, speakers, identities, voice prints - is read and copied, never modified. That is
the invariant the whole feature rests on, and `tests/test_report_draft.py` asserts it by
hashing the transcript tables around each operation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ReportDraft,
    ReportQABlock,
    ReportStatus,
    TranscriptSourceMode,
)
from app.services.report_context import (
    build_qa_blocks,
    build_turns,
    completed_recordings,
    pin_transcripts,
    speaker_map,
    stale_pins,
)


class DraftIsFinal(Exception):
    """A finalized محضر is immutable - corrections produce a new version, never an edit."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_draft(db: Session, session_id: uuid.UUID) -> ReportDraft | None:
    return db.scalar(select(ReportDraft).where(ReportDraft.session_id == session_id))


def require_editable(draft: ReportDraft) -> None:
    if draft.status is ReportStatus.FINAL:
        raise DraftIsFinal("report_is_final")


def create_draft(
    db: Session,
    session_id: uuid.UUID,
    user_id: uuid.UUID | None,
    *,
    recording_ids: list[uuid.UUID] | None = None,
    mode: TranscriptSourceMode = TranscriptSourceMode.CORRECTED,
) -> ReportDraft:
    """First open of the composer: select every completed recording and build the Q&A draft.

    The zero-config path - the investigator can then narrow the selection, reword, exclude.
    """
    if recording_ids is None:
        recording_ids = [r.id for r in completed_recordings(db, session_id)]

    draft = ReportDraft(
        session_id=session_id,
        transcript_source_mode=mode,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(draft)
    db.flush()
    _populate(db, draft, recording_ids, mode)
    return draft


def _populate(
    db: Session, draft: ReportDraft, recording_ids: list[uuid.UUID], mode: TranscriptSourceMode
) -> None:
    """(Re)build this draft's Q&A from the given recordings. Callers decide when."""
    draft.selected_recording_ids = [str(r) for r in recording_ids]
    draft.pinned_transcripts = pin_transcripts(db, recording_ids, mode)
    turns = build_turns(db, recording_ids, mode, pins=draft.pinned_transcripts)
    speakers = speaker_map(db, draft.session_id)

    # Mutate the RELATIONSHIP, not just the table. SessionLocal runs with
    # expire_on_commit=False, so a collection already loaded on this draft would otherwise
    # stay stale in memory and a caller that commits and then serializes the draft would
    # answer with the pre-rebuild list. delete-orphan turns the clear() into DELETEs.
    draft.qa_blocks.clear()
    db.flush()

    for qa in build_qa_blocks(turns, speakers):
        draft.qa_blocks.append(
            ReportQABlock(
                sequence=qa.sequence,
                question_source_text=qa.question_text,
                answer_source_text=qa.answer_text,
                # The printed text starts as the source text; the investigator takes it from
                # there. Keeping both is what lets the composer show "source vs printed".
                report_question_text=qa.question_text,
                report_answer_text=qa.answer_text,
                question_speaker_id=qa.question_speaker_id,
                answer_speaker_id=qa.answer_speaker_id,
                source_segment_ids=qa.segment_ids,
                source_recording_ids=qa.recording_ids,
                start_seconds=qa.start_seconds,
                end_seconds=qa.end_seconds,
            )
        )
    db.flush()


def refresh_draft(db: Session, draft: ReportDraft, user_id: uuid.UUID | None) -> ReportDraft:
    """تحديث من النص المنقح - an EXPLICIT, confirmed rebuild from the current transcripts.

    Never automatic. A transcript corrected after the draft was built does not silently
    rewrite wording the investigator has already reviewed; they ask for this, and lose their
    edits knowingly.
    """
    require_editable(draft)
    recording_ids = [uuid.UUID(r) for r in (draft.selected_recording_ids or [])]
    _populate(db, draft, recording_ids, draft.transcript_source_mode)
    draft.updated_by = user_id
    return draft


def set_recordings(
    db: Session, draft: ReportDraft, recording_ids: list[uuid.UUID], user_id: uuid.UUID | None
) -> ReportDraft:
    """Changing WHICH recordings are in the report necessarily rebuilds the dialogue."""
    require_editable(draft)
    _populate(db, draft, recording_ids, draft.transcript_source_mode)
    draft.updated_by = user_id
    return draft


def set_source_mode(
    db: Session, draft: ReportDraft, mode: TranscriptSourceMode, user_id: uuid.UUID | None
) -> ReportDraft:
    """Switching corrected/original re-quotes the evidence, so it rebuilds too."""
    require_editable(draft)
    draft.transcript_source_mode = mode
    _populate(db, draft, [uuid.UUID(r) for r in (draft.selected_recording_ids or [])], mode)
    draft.updated_by = user_id
    return draft


def draft_is_stale(db: Session, draft: ReportDraft) -> list[dict]:
    return stale_pins(db, draft.pinned_transcripts, draft.transcript_source_mode)


# --------------------------------------------------------------------- Q&A operations


def _renumber(db: Session, draft: ReportDraft) -> None:
    """Keep `sequence` a dense 1..N run. UNIQUE(draft_id, sequence) makes the order of the
    writes matter: park everything above the range first, then renumber."""
    blocks = sorted(draft.qa_blocks, key=lambda b: b.sequence)
    offset = 10_000
    for i, block in enumerate(blocks, start=1):
        block.sequence = offset + i
    db.flush()
    for i, block in enumerate(blocks, start=1):
        block.sequence = i
    db.flush()


def edit_block(
    db: Session,
    block: ReportQABlock,
    *,
    question: str | None = None,
    answer: str | None = None,
    user_id: uuid.UUID | None = None,
) -> ReportQABlock:
    """Reword what will be printed. The SOURCE text and the transcript are untouched."""
    require_editable(block.draft)
    if question is not None:
        block.report_question_text = question
    if answer is not None:
        block.report_answer_text = answer
    block.edited_by = user_id
    block.edited_at = _now()
    return block


def exclude_block(
    db: Session, block: ReportQABlock, reason: str | None, user_id: uuid.UUID | None
) -> ReportQABlock:
    """Leave a block out of the printed document (mic test, greeting, side conversation).

    The block, its source text and the recording all remain - only `included_in_report`
    changes, and who excluded it is recorded.
    """
    require_editable(block.draft)
    block.included_in_report = False
    block.exclusion_reason = (reason or "").strip() or None
    block.excluded_by = user_id
    block.excluded_at = _now()
    return block


def restore_block(db: Session, block: ReportQABlock, user_id: uuid.UUID | None) -> ReportQABlock:
    require_editable(block.draft)
    block.included_in_report = True
    block.exclusion_reason = None
    block.excluded_by = None
    block.excluded_at = None
    block.edited_by = user_id
    block.edited_at = _now()
    return block


def merge_blocks(
    db: Session, first: ReportQABlock, second: ReportQABlock, user_id: uuid.UUID | None
) -> ReportQABlock:
    """Join two adjacent blocks - diarization split one exchange into two.

    The survivor keeps the first block's question and gains the second's answer text and
    provenance, so no source segment stops being referenced.
    """
    require_editable(first.draft)
    if first.draft_id != second.draft_id:
        raise ValueError("blocks_from_different_drafts")
    if abs(first.sequence - second.sequence) != 1:
        raise ValueError("blocks_not_adjacent")
    a, b = (first, second) if first.sequence < second.sequence else (second, first)

    def _join(x: str | None, y: str | None) -> str | None:
        parts = [p for p in ((x or "").strip(), (y or "").strip()) if p]
        return " ".join(parts) or None

    a.report_question_text = _join(a.report_question_text, b.report_question_text)
    a.report_answer_text = _join(a.report_answer_text, b.report_answer_text)
    a.question_source_text = _join(a.question_source_text, b.question_source_text)
    a.answer_source_text = _join(a.answer_source_text, b.answer_source_text)
    a.source_segment_ids = list(a.source_segment_ids or []) + list(b.source_segment_ids or [])
    a.source_recording_ids = list(
        dict.fromkeys(list(a.source_recording_ids or []) + list(b.source_recording_ids or []))
    )
    a.answer_speaker_id = a.answer_speaker_id or b.answer_speaker_id
    if b.end_seconds is not None:
        a.end_seconds = b.end_seconds
    a.edited_by = user_id
    a.edited_at = _now()
    # A merged block's AI suggestion no longer matches its text.
    a.fusha_status = a.fusha_status.__class__.NOT_REQUESTED
    a.llm_suggested_question = a.llm_suggested_answer = None

    draft = a.draft
    draft.qa_blocks.remove(b)  # delete-orphan removes the row; the collection stays truthful
    db.flush()
    _renumber(db, draft)
    return a


def split_block(
    db: Session, block: ReportQABlock, answer_head: str, answer_tail: str, user_id: uuid.UUID | None
) -> ReportQABlock:
    """Split one block's ANSWER in two - the second half becomes a new block that repeats
    the question, so both halves stay attributable.

    The caller supplies both halves (the composer knows where the cursor was); provenance is
    copied to both, because a split cannot know which segment each half came from.
    """
    require_editable(block.draft)
    draft = block.draft
    tail = ReportQABlock(
        sequence=block.sequence + 1,
        question_source_text=block.question_source_text,
        answer_source_text=block.answer_source_text,
        report_question_text=block.report_question_text,
        report_answer_text=answer_tail,
        question_speaker_id=block.question_speaker_id,
        answer_speaker_id=block.answer_speaker_id,
        source_segment_ids=list(block.source_segment_ids or []),
        source_recording_ids=list(block.source_recording_ids or []),
        start_seconds=block.start_seconds,
        end_seconds=block.end_seconds,
        included_in_report=block.included_in_report,
        edited_by=user_id,
        edited_at=_now(),
    )
    block.report_answer_text = answer_head
    block.edited_by = user_id
    block.edited_at = _now()

    # Make room: everything after the split point moves up one. Shift the whole tail out of
    # the way first - UNIQUE(draft_id, sequence) rejects a collision mid-renumber.
    for other in sorted(draft.qa_blocks, key=lambda b: b.sequence, reverse=True):
        if other.sequence > block.sequence:
            other.sequence += 10_000
    db.flush()
    draft.qa_blocks.append(tail)
    db.flush()
    _renumber(db, draft)
    return tail


def included_blocks(draft: ReportDraft) -> list[ReportQABlock]:
    return [b for b in sorted(draft.qa_blocks, key=lambda b: b.sequence) if b.included_in_report]
