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
    # Serialize edits/finalization for a session, including structured-form review.
    return db.scalar(select(ReportDraft).where(ReportDraft.session_id == session_id).with_for_update())


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


