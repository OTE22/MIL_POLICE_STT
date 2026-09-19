"""Turning a session's evidence into the material a محضر تحقيق is written from.

Read-only with respect to evidence. Nothing in this module writes to transcripts, segments,
speakers, identities or recordings - it selects, orders, merges and COPIES.

The chain it implements:

    selected recordings
        -> newest COMPLETED transcript PER RECORDING        (pin_transcripts)
        -> segments in the chosen text mode                 (effective_text)
        -> chronological speaker TURNS across recordings    (build_turns)
        -> س/ج draft blocks                                 (build_qa_blocks)

Two decisions here carry the legal weight of the feature:

* **Per recording, not per session.** `app.api.transcripts._latest_transcript` returns the
  newest transcript of the whole session, which is right for the transcript tab and wrong
  here: a report over three recordings needs the newest transcript OF EACH.
* **Pinning.** Transcripts have no revision counter, so a pin records the transcript id plus
  a sha256 over its segments' effective text. Editing any line changes that hash, which is
  how a draft learns it has gone stale - it never silently rebuilds.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AudioRecording,
    PersonIdentity,
    SessionSpeaker,
    SpeakerRole,
    Transcript,
    TranscriptSegment,
    TranscriptSourceMode,
)

# A turn ends when the speaker changes or when the gap to the next segment exceeds this.
# Diarizers fragment one utterance into several segments; stitching them back is what makes
# a readable question instead of three broken ones.
TURN_GAP_SECONDS = 3.0


def effective_text(seg: TranscriptSegment, mode: TranscriptSourceMode) -> str:
    """The text this report quotes for one segment.

    CORRECTED: the human's correction where one exists, the AI text elsewhere - the same
    `edited_text ?? original_text` rule the transcript viewer has always shown.
    ORIGINAL: the untouched machine output, whatever was corrected afterwards.
    """
    if mode is TranscriptSourceMode.ORIGINAL:
        return seg.original_text or ""
    return (seg.edited_text if seg.edited_text is not None else seg.original_text) or ""


def segments_digest(segments: list[TranscriptSegment], mode: TranscriptSourceMode) -> str:
    """A transcript's 'revision' - it changes the moment any quoted line changes."""
    h = hashlib.sha256()
    for seg in sorted(segments, key=lambda s: s.sequence):
        h.update(f"{seg.sequence}\x1f{seg.speaker_label}\x1f{effective_text(seg, mode)}\x1e".encode())
    return h.hexdigest()


def completed_recordings(db: Session, session_id: uuid.UUID) -> list[AudioRecording]:
    """Recordings of this session that actually have a transcript, oldest first."""
    with_transcripts = set(
        db.scalars(select(Transcript.recording_id).where(Transcript.session_id == session_id)).all()
    )
    rows = db.scalars(
        select(AudioRecording)
        .where(AudioRecording.session_id == session_id)
        .order_by(AudioRecording.created_at)
    ).all()
    return [r for r in rows if r.id in with_transcripts]


def latest_transcript_for_recording(db: Session, recording_id: uuid.UUID) -> Transcript | None:
    """The newest transcript OF ONE RECORDING (reprocessing produces several)."""
    return db.scalar(
        select(Transcript)
        .where(Transcript.recording_id == recording_id)
        .order_by(Transcript.created_at.desc())
        .limit(1)
    )


def pin_transcripts(
    db: Session, recording_ids: list[uuid.UUID], mode: TranscriptSourceMode
) -> list[dict]:
    """Freeze which transcript revision each recording contributes.

    Stored on the draft and copied onto the generated report, so a document can always name
    the exact evidence it was built from.
    """
    pins = []
    for rid in recording_ids:
        transcript = latest_transcript_for_recording(db, rid)
        if transcript is None:
            continue
        pins.append(
            {
                "recording_id": str(rid),
                "transcript_id": str(transcript.id),
                "segments_sha256": segments_digest(list(transcript.segments), mode),
                "segment_count": len(transcript.segments),
            }
        )
    return pins


def stale_pins(db: Session, pins: list[dict] | None, mode: TranscriptSourceMode) -> list[dict]:
    """Pins whose transcript has been edited (or replaced) since the draft was built.

    Used to WARN. Rebuilding is an explicit, confirmed, audited action - never automatic:
    a draft the investigator has already reworded must not change under them.
    """
    stale = []
    for pin in pins or []:
        transcript = db.get(Transcript, uuid.UUID(pin["transcript_id"]))
        if transcript is None:
            stale.append({**pin, "reason": "transcript_missing"})
            continue
        newest = latest_transcript_for_recording(db, transcript.recording_id)
        if newest is not None and newest.id != transcript.id:
            stale.append({**pin, "reason": "newer_transcript_exists"})
        elif segments_digest(list(transcript.segments), mode) != pin.get("segments_sha256"):
            stale.append({**pin, "reason": "segments_edited"})
    return stale


# --------------------------------------------------------------------------- speakers


@dataclass
class SpeakerInfo:
    """Everything the report needs about one speaker OBSERVATION (recording-local)."""

    speaker_id: uuid.UUID
    speaker_label: str
    recording_id: uuid.UUID | None
    source_label: str | None
    role: SpeakerRole
    identity_id: uuid.UUID | None
    person_name: str | None
    display_name: str | None

    @property
    def resolved(self) -> bool:
        """A real person stands behind this voice."""
        return self.identity_id is not None and bool(self.person_name)

    @property
    def legacy(self) -> bool:
        """Pre-provenance row: which recording it came from was never recorded."""
        return self.recording_id is None

    def report_name(self) -> str:
        """What the document prints for this voice.

        Canonical registry name when known; the session-local display name is clearly marked
        as unverified; and a bare SPEAKER_NN is never dressed up as a person.
        """
        if self.resolved:
            return self.person_name or ""
        if self.display_name:
            return f"{self.display_name} (غير موثّق في السجل)"
        return f"متحدث غير محدد الهوية ({self.speaker_label})"


def speaker_map(db: Session, session_id: uuid.UUID) -> dict[str, SpeakerInfo]:
    """Visible speaker_label -> SpeakerInfo. The label segments actually carry."""
    speakers = db.scalars(select(SessionSpeaker).where(SessionSpeaker.session_id == session_id)).all()
    identity_ids = [s.identity_id for s in speakers if s.identity_id]
    identities = {
        pi.id: pi
        for pi in db.scalars(select(PersonIdentity).where(PersonIdentity.id.in_(identity_ids))).all()
    }
    out: dict[str, SpeakerInfo] = {}
    for s in speakers:
        identity = identities.get(s.identity_id) if s.identity_id else None
        out[s.speaker_label] = SpeakerInfo(
            speaker_id=s.id,
            speaker_label=s.speaker_label,
            recording_id=s.recording_id,
            source_label=s.source_label,
            role=s.speaker_role,
            identity_id=s.identity_id,
            person_name=identity.person_name if identity else None,
            display_name=s.display_name,
        )
    return out


def compose_name(person_name: str | None, rank: str | None) -> str:
    """'الرائد علي عباس' for the page, while the registry keeps name and rank apart."""
    name = (person_name or "").strip()
    rank = (rank or "").strip()
    if rank and name and not name.startswith(rank):
        return f"{rank} {name}"
    return name


# --------------------------------------------------------------------------- turns


@dataclass
class Turn:
    """One continuous stretch of speech by one speaker, stitched from fragmented segments."""

    speaker_label: str
    recording_id: uuid.UUID
    text: str
    start_seconds: float
    end_seconds: float
    segment_ids: list[uuid.UUID] = field(default_factory=list)
    order: tuple = ()

    @property
    def role(self) -> SpeakerRole | None:
        return None


def build_turns(
    db: Session,
    recording_ids: list[uuid.UUID],
    mode: TranscriptSourceMode,
    *,
    pins: list[dict] | None = None,
) -> list[Turn]:
    """Chronological turns across ALL selected recordings.

    Recording order is the session's recording order (creation time), and within a recording
    the segment sequence - so testimony reads in the order it was given. Consecutive segments
    of the same speaker merge when the pause between them is short.
    """
    pinned_by_recording = {p["recording_id"]: p["transcript_id"] for p in (pins or [])}
    turns: list[Turn] = []

    for rec_index, rid in enumerate(recording_ids):
        pinned_id = pinned_by_recording.get(str(rid))
        transcript = (
            db.get(Transcript, uuid.UUID(pinned_id))
            if pinned_id
            else latest_transcript_for_recording(db, rid)
        )
        if transcript is None:
            continue
        current: Turn | None = None
        for seg in sorted(transcript.segments, key=lambda s: s.sequence):
            text = effective_text(seg, mode).strip()
            if not text:
                continue
            start, end = float(seg.start_seconds), float(seg.end_seconds)
            same_speaker = current is not None and current.speaker_label == seg.speaker_label
            close_enough = current is not None and (start - current.end_seconds) <= TURN_GAP_SECONDS
            if same_speaker and close_enough:
                # Fragments of one utterance: "هل تعرف" + "الشخص أحمد" -> one question.
                separator = "" if current.text.endswith(("،", ":", "-")) else " "
                current.text = f"{current.text}{separator}{text}"
                current.end_seconds = end
                current.segment_ids.append(seg.id)
                continue
            current = Turn(
                speaker_label=seg.speaker_label,
                recording_id=rid,
                text=text,
                start_seconds=start,
                end_seconds=end,
                segment_ids=[seg.id],
                order=(rec_index, seg.sequence),
            )
            turns.append(current)
    return turns


# --------------------------------------------------------------------------- Q&A draft


@dataclass
class QADraft:
    sequence: int
    question_text: str
    answer_text: str
    question_speaker_id: uuid.UUID | None
    answer_speaker_id: uuid.UUID | None
    segment_ids: list[str]
    recording_ids: list[str]
    start_seconds: float | None
    end_seconds: float | None


def _is_question_role(info: SpeakerInfo | None) -> bool:
    return info is not None and info.role is SpeakerRole.INVESTIGATOR


def build_qa_blocks(turns: list[Turn], speakers: dict[str, SpeakerInfo]) -> list[QADraft]:
    """Turns -> an initial س/ج draft. A DRAFT: the investigator rewrites it freely.

    Investigator turns open a block; the following non-investigator turns answer it.
    Deliberately not naive alternation - an unanswered question, two answers in a row, or a
    session with no role assignments at all must all survive into something editable rather
    than being forced into pairs. Speech with no question before it becomes an
    answer-only block, so no testimony is ever silently dropped.
    """
    blocks: list[QADraft] = []
    pending: QADraft | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            blocks.append(pending)
            pending = None

    for turn in turns:
        info = speakers.get(turn.speaker_label)
        speaker_id = info.speaker_id if info else None
        if _is_question_role(info):
            flush()
            pending = QADraft(
                sequence=len(blocks) + 1,
                question_text=turn.text,
                answer_text="",
                question_speaker_id=speaker_id,
                answer_speaker_id=None,
                segment_ids=[str(s) for s in turn.segment_ids],
                recording_ids=[str(turn.recording_id)],
                start_seconds=turn.start_seconds,
                end_seconds=turn.end_seconds,
            )
            continue

        if pending is None:
            # Testimony with no question in front of it (a statement, or a session where
            # nobody is marked as the investigator). Keep it as an answer-only block.
            pending = QADraft(
                sequence=len(blocks) + 1,
                question_text="",
                answer_text=turn.text,
                question_speaker_id=None,
                answer_speaker_id=speaker_id,
                segment_ids=[str(s) for s in turn.segment_ids],
                recording_ids=[str(turn.recording_id)],
                start_seconds=turn.start_seconds,
                end_seconds=turn.end_seconds,
            )
            continue

        if pending.answer_text and pending.answer_speaker_id != speaker_id:
            # A different person answers the same question: new block, question repeated so
            # the attribution of each answer stays unambiguous.
            question, qid = pending.question_text, pending.question_speaker_id
            flush()
            pending = QADraft(
                sequence=len(blocks) + 1,
                question_text=question,
                answer_text=turn.text,
                question_speaker_id=qid,
                answer_speaker_id=speaker_id,
                segment_ids=[str(s) for s in turn.segment_ids],
                recording_ids=[str(turn.recording_id)],
                start_seconds=turn.start_seconds,
                end_seconds=turn.end_seconds,
            )
            continue

        joiner = " " if pending.answer_text else ""
        pending.answer_text = f"{pending.answer_text}{joiner}{turn.text}"
        pending.answer_speaker_id = pending.answer_speaker_id or speaker_id
        pending.segment_ids.extend(str(s) for s in turn.segment_ids)
        if str(turn.recording_id) not in pending.recording_ids:
            pending.recording_ids.append(str(turn.recording_id))
        pending.end_seconds = turn.end_seconds

    flush()
    for i, block in enumerate(blocks, start=1):
        block.sequence = i
    return blocks
