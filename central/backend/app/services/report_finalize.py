"""Issuing the محضر: validate, freeze, render, hash, archive.

The order in `finalize` is the whole point. A finalized report is rendered from an immutable
SNAPSHOT of the draft, not from the live tables, and the file lands on disk before the
database row exists - so the two can never disagree in the dangerous direction:

    validate -> build context -> render -> hash -> write file
             -> insert row -> audit -> commit           (on failure: delete the file)

That leaves two possible outcomes: a complete report with a row, or no report at all. Never
a database row pointing at a missing document, and never an official document on disk that
the system has no record of issuing.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AudioRecording,
    GeneratedReport,
    InvestigationSession,
    InvestigatorProfile,
    PersonIdentity,
    ReportDraft,
    ReportStatus,
    SessionInvestigator,
    Subject,
    TemplateValidationStatus,
    Transcript,
    TranscriptSourceMode,
    User,
)
from app.services.report_context import compose_name, speaker_map
from app.services.report_draft import included_blocks
from app.services.report_renderer import ALLOWED_PLACEHOLDERS, render
from app.services.report_storage import (
    atomic_write,
    context_relative_path,
    read_file,
    remove_file,
    report_relative_path,
    sha256_bytes,
)

log = logging.getLogger(__name__)

# Arabic labels for the enums a report prints. Kept beside the report because the wording on
# an official document is a decision of this feature, not of the models.
PERSON_TYPE_AR = {"MILITARY": "عسكري", "CIVILIAN": "مدني", "UNKNOWN": "غير محدد الهوية"}
SESSION_STATUS_AR = {
    "DRAFT": "مسودة",
    "RECORDING": "قيد التسجيل",
    "PROCESSING": "قيد المعالجة",
    "COMPLETED": "مكتملة",
    "FAILED": "فشلت",
    "ARCHIVED": "مؤرشفة",
}
SOURCE_MODE_AR = {
    TranscriptSourceMode.CORRECTED: "النص المنقّح (المصحّح بشرياً)",
    TranscriptSourceMode.ORIGINAL: "النص الأصلي من الذكاء الاصطناعي",
}
DEV_TEMPLATE_NOTICE = "نموذج تطويري غير معتمد — DEVELOPMENT TEMPLATE"


class FinalizationRefused(Exception):
    """The report may not be issued yet. `code` is an Arabic-mapped error for the UI."""

    def __init__(self, code: str, detail: dict | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail or {}


@dataclass
class Preflight:
    missing_fields: list[str]
    unresolved_labels: list[str]
    blocked: list[str]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seconds_to_clock(value: float | None) -> str:
    if value is None:
        return ""
    total = int(value)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def check_ready(db: Session, session: InvestigationSession, draft: ReportDraft, template) -> Preflight:
    """Everything that must be true before an official document may be issued.

    Explicit field checks rather than relying on the renderer's StrictUndefined: a blank
    رقم المحضر is a policy failure the operator must see named, not a template error.
    """
    from app.api.reports import REQUIRED_FIELD_LABELS  # labels live with the API contract

    missing = [
        label
        for field, label in REQUIRED_FIELD_LABELS.items()
        if not (getattr(draft, field) or "").strip()
    ]

    speakers = speaker_map(db, session.id)
    by_id = {info.speaker_id: info for info in speakers.values()}
    speaking = {
        sid
        for block in included_blocks(draft)
        for sid in (block.question_speaker_id, block.answer_speaker_id)
        if sid
    }
    unresolved = sorted(
        by_id[sid].speaker_label for sid in speaking if sid in by_id and not by_id[sid].resolved
    )

    blocked: list[str] = []
    if draft.status is ReportStatus.FINAL:
        blocked.append("report_is_final")
    if not included_blocks(draft):
        blocked.append("report_no_content")
    if template is None:
        blocked.append("report_no_active_template")
    elif template.validation_status is not TemplateValidationStatus.VALID:
        blocked.append("report_template_invalid")
    elif template.is_development and get_settings().environment.strip().lower() == "production":
        # A development stand-in must never leave the building as an official document.
        blocked.append("report_template_not_official")
    if unresolved and not draft.unresolved_ack:
        blocked.append("report_unresolved_speakers")
    if len(included_blocks(draft)) > get_settings().report_max_qa_blocks:
        blocked.append("report_too_large")

    return Preflight(missing_fields=missing, unresolved_labels=unresolved, blocked=blocked)


def build_context(
    db: Session,
    session: InvestigationSession,
    draft: ReportDraft,
    template,
    *,
    version: int,
    generated_by: User | None,
) -> dict:
    """The immutable rendering input: everything the template may reference, all of it.

    Emits EVERY catalogued key - empty string or empty list when absent - which is the
    contract that makes StrictUndefined safe at render time.
    """
    speakers = speaker_map(db, session.id)
    by_id = {info.speaker_id: info for info in speakers.values()}
    blocks = sorted(draft.qa_blocks, key=lambda b: b.sequence)
    printed = [b for b in blocks if b.included_in_report]

    selected = [uuid.UUID(r) for r in (draft.selected_recording_ids or [])]
    all_recordings = db.scalars(
        select(AudioRecording)
        .where(AudioRecording.session_id == session.id)
        .order_by(AudioRecording.created_at)
    ).all()

    investigators = []
    for link in db.scalars(
        select(SessionInvestigator).where(SessionInvestigator.session_id == session.id)
    ).all():
        profile = db.get(InvestigatorProfile, link.investigator_id)
        if profile:
            investigators.append(
                {
                    "name": profile.full_name,
                    "rank": profile.rank or "",
                    "unit": profile.unit or "",
                    "role": link.assignment_role.value,
                }
            )

    subjects = []
    for subject in db.scalars(select(Subject).where(Subject.session_id == session.id)).all():
        subjects.append(
            {
                "name": subject.subject_name,
                "rank": subject.rank or "",
                "person_type": PERSON_TYPE_AR.get(subject.person_type.value, ""),
                "nationality": subject.nationality_name or "",
            }
        )

    lead = next((i for i in investigators if i["role"] == "LEAD"), None) or (
        investigators[0] if investigators else None
    )
    main_subject = subjects[0] if subjects else None

    qa_blocks = []
    for index, block in enumerate(printed, start=1):
        answer_info = by_id.get(block.answer_speaker_id)
        question_info = by_id.get(block.question_speaker_id)
        qa_blocks.append(
            {
                "index": index,
                "number": str(index),
                "question": block.report_question_text or "",
                "answer": block.report_answer_text or "",
                "question_speaker": question_info.report_name() if question_info else "",
                "answer_speaker": answer_info.report_name() if answer_info else "",
                "recording": ", ".join(str(r)[:8] for r in (block.source_recording_ids or [])),
                "time_range": f"{_seconds_to_clock(block.start_seconds)} - {_seconds_to_clock(block.end_seconds)}",
                # Disclosure: the document itself can show which lines a human reworded.
                "edited": (block.report_answer_text or "") != (block.answer_source_text or "")
                or (block.report_question_text or "") != (block.question_source_text or ""),
            }
        )

    excluded = [
        {
            "index": b.sequence,
            "reason": b.exclusion_reason or "",
            "excerpt": (b.answer_source_text or b.question_source_text or "")[:120],
        }
        for b in blocks
        if not b.included_in_report
    ]

    edits = [
        {
            "index": i,
            "editor": "",
            "edited_at": qa["time_range"],
            "excerpt": qa["answer"][:120],
        }
        for i, qa in enumerate(qa_blocks, start=1)
        if qa["edited"]
    ]

    now = _now()
    context = {
        "report_number": draft.report_number or "",
        "case_subject": draft.case_subject or "",
        "report_date": draft.report_date.isoformat() if draft.report_date else "",
        "report_time": draft.report_time.strftime("%H:%M") if draft.report_time else "",
        "report_datetime": (
            f"{draft.report_date.isoformat()} {draft.report_time.strftime('%H:%M')}"
            if draft.report_date and draft.report_time
            else (draft.report_date.isoformat() if draft.report_date else "")
        ),
        "investigation_location": draft.location or "",
        "session_number": session.session_number,
        "session_title": session.title,
        "session_date": session.session_date.isoformat() if session.session_date else "",
        "session_status": SESSION_STATUS_AR.get(session.status.value, session.status.value),
        "investigator_name": compose_name(lead["name"], None) if lead else "",
        "investigator_rank": lead["rank"] if lead else "",
        "investigator_unit": lead["unit"] if lead else "",
        "subject_name": main_subject["name"] if main_subject else "",
        "subject_rank": main_subject["rank"] if main_subject else "",
        "subject_person_type": main_subject["person_type"] if main_subject else "",
        "subject_nationality": main_subject["nationality"] if main_subject else "",
        "intro_text": draft.intro_text or "",
        "closing_text": draft.closing_text or "",
        "transcript_source_label": SOURCE_MODE_AR.get(draft.transcript_source_mode, ""),
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "generated_by_name": (
            (generated_by.profile.full_name if generated_by and generated_by.profile else None)
            or (generated_by.username if generated_by else "")
        ),
        "report_version": version,
        "template_version": template.version if template else 0,
        # Stamped by the template itself; empty for an approved form.
        "template_notice": DEV_TEMPLATE_NOTICE if (template and template.is_development) else "",
        "qa_count": len(qa_blocks),
        "recording_count": len(selected),
        "qa_blocks": qa_blocks,
        "investigators": investigators,
        "subjects": subjects,
        # EVERY recording of the session, with whether it was included: selective inclusion
        # is visible on the document, never silent.
        "recordings": [
            {
                "index": i,
                "filename": r.original_filename,
                "included": r.id in selected,
                "duration": _seconds_to_clock(float(r.duration_seconds) if r.duration_seconds else None),
                "transcript_id": "",
            }
            for i, r in enumerate(all_recordings, start=1)
        ],
        "speakers": [
            {
                "label": info.speaker_label,
                "name": info.report_name(),
                "role": info.role.value,
                "resolved": info.resolved,
            }
            for info in sorted(speakers.values(), key=lambda i: i.speaker_label)
        ],
        "excluded_blocks": excluded,
        "edits": edits,
    }

    missing = ALLOWED_PLACEHOLDERS - set(context)
    if missing:  # the contract StrictUndefined depends on
        raise FinalizationRefused("report_context_incomplete", {"missing": sorted(missing)})
    return context


def finalize(
    db: Session,
    session: InvestigationSession,
    draft: ReportDraft,
    template,
    user: User,
) -> GeneratedReport:
    """Issue the report. Raises FinalizationRefused rather than producing a doubtful document."""
    preflight = check_ready(db, session, draft, template)
    if preflight.blocked or preflight.missing_fields:
        raise FinalizationRefused(
            preflight.blocked[0] if preflight.blocked else "report_missing_fields",
            {"missing_fields": preflight.missing_fields, "unresolved": preflight.unresolved_labels},
        )

    version = int(
        db.scalar(
            select(func.max(GeneratedReport.report_version)).where(
                GeneratedReport.session_id == session.id
            )
        )
        or 0
    ) + 1

    report_id = uuid.uuid4()
    context = build_context(db, session, draft, template, version=version, generated_by=user)

    template_bytes = read_file(template.storage_path)
    if template_bytes is None:
        raise FinalizationRefused("report_template_file_missing")

    docx_bytes = render(template_bytes, context)

    # Sidecar: the exact rendering input, so a document can be re-derived and explained.
    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")

    docx_rel = report_relative_path(session.id, report_id, version)
    context_rel = context_relative_path(session.id, report_id, version)

    # File first, row second - a crash leaves at worst an unreferenced file, never a row
    # pointing at a document that does not exist.
    _, size, docx_sha = atomic_write(docx_rel, docx_bytes)
    atomic_write(context_rel, context_json)

    try:
        report = GeneratedReport(
            id=report_id,
            session_id=session.id,
            draft_id=draft.id,
            report_version=version,
            template_version_id=template.id,
            storage_path=docx_rel,
            context_path=context_rel,
            docx_sha256=docx_sha,
            context_sha256=sha256_bytes(context_json),
            template_sha256=template.sha256,
            size_bytes=size,
            report_number=draft.report_number,
            transcript_source_mode=draft.transcript_source_mode,
            selected_recording_ids=list(draft.selected_recording_ids or []),
            pinned_transcripts=list(draft.pinned_transcripts or []),
            qa_block_count=len(context["qa_blocks"]),
            generated_by=user.id,
        )
        db.add(report)
        draft.status = ReportStatus.FINAL
        db.flush()
    except Exception:
        # No orphan official document may survive a failed insert.
        remove_file(docx_rel)
        remove_file(context_rel)
        raise

    log.info(
        "report issued session=%s version=%d template=v%d blocks=%d sha256=%s",
        session.session_number, version, template.version, len(context["qa_blocks"]), docx_sha[:12],
    )
    return report


@dataclass
class Verification:
    ok: bool
    docx_ok: bool
    context_ok: bool
    template_ok: bool
    detail: str


def verify(db: Session, report: GeneratedReport) -> Verification:
    """Recompute the three hashes. Integrity verification - NOT a digital signature."""
    from app.models import ReportTemplateVersion

    docx = read_file(report.storage_path)
    docx_ok = docx is not None and sha256_bytes(docx) == report.docx_sha256

    context_ok = True
    if report.context_path and report.context_sha256:
        blob = read_file(report.context_path)
        context_ok = blob is not None and sha256_bytes(blob) == report.context_sha256

    template_ok = True
    if report.template_version_id and report.template_sha256:
        template = db.get(ReportTemplateVersion, report.template_version_id)
        template_ok = template is not None and template.sha256 == report.template_sha256

    ok = bool(docx_ok and context_ok and template_ok)
    if ok:
        detail = "سليم"
    elif docx is None:
        detail = "الملف مفقود"
    else:
        detail = "غير مطابق"
    return Verification(ok=ok, docx_ok=bool(docx_ok), context_ok=context_ok, template_ok=template_ok, detail=detail)
