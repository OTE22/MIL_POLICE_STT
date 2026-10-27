"""Review-bound, immutable HTML/PDF issuance. No legacy generators."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select, func
from fastapi import HTTPException
from app.models import GeneratedReport, ReportStatus
from app.services import report_html, report_document
from app.services.workflow import source_token, source_snapshot, evidence_blockers, guard_mutation, lock_source_people
from app.services.report_storage import atomic_write, read_file, sha256_bytes


def format_digest():
    from app.services import report_opening
    paths = sorted(report_document.ASSETS.iterdir())
    return sha256_bytes(Path(report_document.__file__).read_bytes() + Path(report_opening.__file__).read_bytes() +
                        json.dumps(report_html.CATALOGUE, sort_keys=True, ensure_ascii=False).encode() +
                        b"".join(p.read_bytes() for p in paths if p.is_file()))


def review_token(db, session, draft):
    return sha256_bytes((report_html.token_for(draft) + source_token(db, session) + format_digest()).encode())


def content_blockers(session, document):
    reasons = []
    from app.services.report_opening import blockers
    reasons.extend(blockers(session, document))
    closing = document.get("closing")
    if closing and (not closing.get("text", "").strip() or not closing.get("location", "").strip() or not closing.get("date")):
        reasons.append("report_closing_details_required")
    if not document["subject"].strip():
        reasons.append("report_subject_required")
    if not document.get("investigator_id"):
        reasons.append("report_investigator_required")
    if not document["blocks"]:
        reasons.append("report_no_content")
    if not any(b["type"] == "conclusion" for b in document["blocks"]):
        reasons.append("report_conclusion_required")
    for block in document["blocks"]:
        values = block["values"]
        if not values.get("closing_date", "").strip() or not values.get("closing_location", "").strip():
            reasons.append("report_closing_details_required")
        if block["type"] == "conclusion":
            if not values.get("facts", "").strip() or not values.get("inference", "").strip():
                reasons.append("report_conclusion_incomplete")
            if block["responsibility_mode"] == "UNREVIEWED" or (block["responsibility_mode"] == "FINDINGS" and not block["findings"]):
                reasons.append("report_responsibilities_required")
            if block["responsibility_mode"] == "NONE" and block["findings"]:
                reasons.append("report_responsibility_conflict")
            for finding in block["findings"]:
                if not finding["text"].strip() or not (finding["participant_key"] or finding["unidentified_subject"].strip()):
                    reasons.append("report_finding_incomplete")
                if not any(finding["references"].get(k) for k in ("recordings", "documents", "blocks")):
                    reasons.append("report_finding_evidence_required")
            if block["proposal_mode"] == "UNREVIEWED" or (block["proposal_mode"] == "TEXT" and not values.get("proposals", "").strip()):
                reasons.append("report_proposals_required")
            if block["proposal_mode"] == "NONE" and values.get("proposals", "").strip():
                reasons.append("report_proposals_conflict")
        elif block["type"] == "note":
            if not values.get("note_text", "").strip():
                reasons.append("report_note_empty")
        else:
            if not values.get("statement_name", "").strip():
                reasons.append("report_statement_name_required")
            if not block["entries"] or any(not entry["answer"].strip() for entry in block["entries"]):
                reasons.append("report_answer_required")
            if block["identity_checked"] and not values.get("identity_documents", "").strip():
                reasons.append("report_identity_documents_required")
            if block["attestation_confirmed"] and not document.get("clerk_id"):
                reasons.append("report_clerk_required")
    return list(dict.fromkeys(reasons))


def check_ready(db, session, draft, *, verify_evidence=False):
    if draft.status == ReportStatus.FINAL:
        return ["report_is_final"]
    reasons = content_blockers(session, report_html.document_for(draft)) + evidence_blockers(db, session, verify_hashes=verify_evidence)
    from app.services.report_dictation import blockers
    reasons.extend(blockers(db, session, draft, verify_hashes=verify_evidence))
    from app.services.participant_requirements import readiness
    if not readiness(session)["ready"]:
        reasons.append("participant_details_incomplete")
    if session.workflow_state in {"CLOSED", "ARCHIVED"}:
        reasons.append("reopen_investigation_before_editing")
    if ((draft.official_form or {}).get("html_review") or {}).get("token") != review_token(db, session, draft):
        reasons.append("report_review_required")
    return list(dict.fromkeys(reasons))


def finalize(db, session, draft, user):
    require_lead(session, user)
    guard_mutation(session)
    lock_source_people(db, session)
    reasons = check_ready(db, session, draft, verify_evidence=True)
    if reasons:
        raise HTTPException(409, detail={"code": "report_not_ready", "reasons": reasons})
    version = int(db.scalar(select(func.max(GeneratedReport.report_version)).where(
        GeneratedReport.session_id == session.id)) or 0) + 1
    report_id = uuid.uuid4()
    document = report_html.document_for(draft)
    number = f"{session.session_number}/{version}"
    html = report_document.render(document, session, issued=True, version=version, number=number)
    try:
        pdf = report_document.pdf_from_html(html)
    except Exception as exc:
        raise HTTPException(503, detail="report_pdf_render_failed") from exc
    snapshot = {"document": document, "session_id": str(session.id), "session_number": session.session_number,
                "version": version, "report_number": number, "source_token": source_token(db, session),
                "review": (draft.official_form or {}).get("html_review"), "format_digest": format_digest(),
                "issued_by": str(user.id), "issued_at": datetime.now(timezone.utc).isoformat(),
                "sources": source_snapshot(db, session),
                "dictation_provenance": dictation_snapshot(db, session),
                "transcript_reviews": transcript_review_snapshot(db, draft),
                "transcript_source_mode": draft.transcript_source_mode.value,
                "transcript_pins": draft.pinned_transcripts, "selected_recording_ids": draft.selected_recording_ids}
    context = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str).encode()
    prefix = f"reports/{session.id}/v{version}-{report_id}"
    # Failed commits can leave an orphan, never a row pointing to a deleted official artifact.
    atomic_write(prefix + ".html", html.encode())
    atomic_write(prefix + ".pdf", pdf)
    atomic_write(prefix + ".context.json", context)
    report = GeneratedReport(id=report_id, session_id=session.id, draft_id=draft.id,
                             report_version=version, report_number=number, format_key=document["revision"],
                             html_path=prefix + ".html", html_sha256=sha256_bytes(html.encode()),
                             pdf_path=prefix + ".pdf", pdf_sha256=sha256_bytes(pdf),
                             context_path=prefix + ".context.json", context_sha256=sha256_bytes(context),
                             renderer_sha256=format_digest(), size_bytes=len(pdf), generated_by=user.id,
                             transcript_source_mode=draft.transcript_source_mode, qa_block_count=len(draft.qa_blocks),
                             pinned_transcripts=draft.pinned_transcripts,
                             selected_recording_ids=draft.selected_recording_ids)
    db.add(report)
    draft.status = ReportStatus.FINAL
    draft.official_form = {**draft.official_form, "issued_source_token": snapshot["source_token"]}
    session.revision += 1
    db.flush()
    return report


def require_lead(session, user):
    if "reports.finalize" not in user.permission_codes or not any(
        i.assignment_role.value == "LEAD" and i.investigator.user_id == user.id for i in session.investigators
    ):
        raise HTTPException(403, detail="report_lead_approval_required")


def dictation_snapshot(db, session):
    from app.services.report_dictation import rows
    return [{"recording_id": str(r.id), "sha256": r.sha256, "context": r.report_context}
            for r in rows(db, session.id) if (r.report_context or {}).get("status") == "ACCEPTED"]


def transcript_review_snapshot(db, draft):
    from app.services.report_context import latest_transcript_for_recording
    return [{"transcript_id": str(t.id), "recording_id": str(t.recording_id), "review_sha256": t.review_token,
             "reviewed_by": str(t.reviewed_by) if t.reviewed_by else None, "reviewed_at": t.reviewed_at}
            for identifier in draft.selected_recording_ids or []
            if (t := latest_transcript_for_recording(db, uuid.UUID(str(identifier)))) is not None]


def verify(db, report):
    def matches(path, digest):
        data = read_file(path) if path else None
        return data is not None and digest is not None and sha256_bytes(data) == digest
    result = {"report_id": str(report.id), "html_ok": matches(report.html_path, report.html_sha256),
              "pdf_ok": matches(report.pdf_path, report.pdf_sha256),
              "context_ok": matches(report.context_path, report.context_sha256)}
    result["ok"] = all(result[key] for key in ("html_ok", "pdf_ok", "context_ok"))
    result["detail"] = "verified" if result["ok"] else "missing_or_modified_artifact"
    return result
