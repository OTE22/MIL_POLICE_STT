"""One HTML report workflow: structured editing, review, immutable HTML/PDF issuance."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.deps import get_accessible_session, require_permission, client_ip
from app.db.session import get_db
from app.models import InvestigationSession, ReportDraft, ReportStatus, GeneratedReport, User, Subject, ReportNoteTemplate, AuditAction
from app.schemas.report_html import HtmlReportUpdate, StatementSelection, NoteTemplateCreate
from app.schemas.statement_details import StatementDetailsUpdate, DETAIL_KEYS
from app.services import report_html, report_people, note_templates
from app.services.report_draft import create_draft, get_draft, refresh_draft
from app.services.audit import record_audit
from app.services.report_finalize import check_ready, finalize, verify, review_token
from app.services.workflow import guard_mutation, source_token, source_snapshot
from app.services.report_storage import absolute_path
router = APIRouter(tags=["reports"])


def _require_draft(db, session):
    draft = get_draft(db, session.id)
    if draft is None:
        raise HTTPException(404, detail="report_draft_not_found")
    return draft


def _guard_editable(draft):
    if draft.status == ReportStatus.FINAL:
        raise HTTPException(409, detail="report_is_final")


def _lock_session(db, session):
    return db.scalar(select(InvestigationSession).where(InvestigationSession.id == session.id)
                     .with_for_update().execution_options(populate_existing=True))


def _audit(db, request, user, action, session, entity_id, **metadata):
    record_audit(db, action=action, user_id=user.id, entity_type="report", entity_id=entity_id,
                 metadata={"session_id": str(session.id), **metadata}, ip_address=client_ip(request))


class TokenInput(BaseModel):
    expected_token: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReviewInput(TokenInput):
    expected_source_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_reviewed: Literal[True]
    acknowledge_source_changes: bool = False


class ReopenInput(TokenInput):
    model_config = {"str_strip_whitespace": True}
    reason: str = Field(min_length=3, max_length=2000)


def _check_token(body, draft):
    if body.expected_token != report_html.token_for(draft):
        raise HTTPException(409, detail="html_report_changed")


@router.get("/report-forms/html-statement")
def html_statement_catalogue(_: User = Depends(require_permission("reports.read", "reports.generate"))):
    return report_html.CATALOGUE


@router.get("/report-forms/note-templates")
def get_note_templates(_: User = Depends(require_permission("reports.read", "reports.generate")), db: Session = Depends(get_db)):
    return note_templates.list_templates(db)


@router.post("/report-forms/note-templates", status_code=201)
def create_note_template(body: NoteTemplateCreate, request: Request,
                         user: User = Depends(require_permission("reports.templates.manage")), db: Session = Depends(get_db)):
    template = ReportNoteTemplate(title=body.title, body=body.body, created_by=user.id)
    db.add(template)
    db.flush()
    record_audit(db, action=AuditAction.REPORT_TEMPLATE_UPLOADED, user_id=user.id,
                 entity_type="report_note_template", entity_id=template.id,
                 metadata={"kind": "note_wording"}, ip_address=client_ip(request))
    db.commit()
    return note_templates.definition(template.id, template.title, template.body)


@router.get("/investigations/{session_id}/report/html/people")
def html_report_people(session: InvestigationSession = Depends(get_accessible_session),
                       _: User = Depends(require_permission("reports.read", "reports.generate")), db: Session = Depends(get_db)):
    return {"session_id": str(session.id), "options": report_people.options_for(db, session)}


@router.post("/investigations/{session_id}/report/html/statement-preview")
def html_statement_preview(body: StatementSelection, session: InvestigationSession = Depends(get_accessible_session),
                           _: User = Depends(require_permission("reports.generate")), db: Session = Depends(get_db)):
    draft = _require_draft(db, session)
    _guard_editable(draft)
    from app.services.workflow import guard_mutation
    guard_mutation(session)
    try:
        return report_html.statement_preview(db, draft, session, body.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


def _participant_details(session, key):
    subject = next((s for s in session.subjects if s.participant_key == key), None)
    if subject is None:
        raise HTTPException(404, detail="session_participant_not_found")
    return subject


def _details_state(subject):
    return {"session_id": str(subject.session_id), "participant_key": str(subject.participant_key),
            "values": subject.statement_details or {}, "token": report_people.details_token(subject),
            "fields": [f for f in report_html.CATALOGUE["fields"] if f["key"] in DETAIL_KEYS]}


@router.get("/investigations/{session_id}/participants/{participant_key}/statement-details")
def participant_statement_details(participant_key: uuid.UUID, session: InvestigationSession = Depends(get_accessible_session),
                                  _: User = Depends(require_permission("investigations.read_assigned", "investigations.read_all"))):
    return _details_state(_participant_details(session, participant_key))


@router.put("/investigations/{session_id}/participants/{participant_key}/statement-details")
def update_participant_statement_details(participant_key: uuid.UUID, body: StatementDetailsUpdate, request: Request,
                                         session: InvestigationSession = Depends(get_accessible_session),
                                         user: User = Depends(require_permission("investigations.update")), db: Session = Depends(get_db)):
    db.scalar(select(InvestigationSession).where(InvestigationSession.id == session.id).with_for_update())
    subject = db.scalar(select(Subject).where(Subject.session_id == session.id, Subject.participant_key == participant_key, Subject.removed_at.is_(None))
                        .with_for_update().execution_options(populate_existing=True))
    if subject is None:
        raise HTTPException(404, detail="session_participant_not_found")
    if body.expected_token != report_people.details_token(subject):
        raise HTTPException(409, detail="statement_details_changed")
    from app.services.workflow import evidence_changed
    evidence_changed(session)
    subject.statement_details = body.values
    record_audit(db, action=AuditAction.INVESTIGATION_UPDATED, user_id=user.id,
                 entity_type="investigation_session", entity_id=session.id,
                 metadata={"participant_key": str(participant_key), "fields": sorted(body.values)}, ip_address=client_ip(request))
    db.commit()
    return _details_state(subject)


@router.get("/investigations/{session_id}/report/html")
def get_html_report(session: InvestigationSession = Depends(get_accessible_session),
                    _: User = Depends(require_permission("reports.read", "reports.generate")), db: Session = Depends(get_db)):
    return report_html.state_for(_require_draft(db, session), db, session)


@router.post("/investigations/{session_id}/report/html")
def create_html_report(request: Request,
                       session: InvestigationSession = Depends(get_accessible_session),
                       user: User = Depends(require_permission("reports.generate")), db: Session = Depends(get_db)):
    # A manually filled statement can be started before a recording is transcribed.
    db.scalar(select(InvestigationSession).where(InvestigationSession.id == session.id).with_for_update())
    draft = get_draft(db, session.id)
    if draft is None:
        from app.services.workflow import guard_mutation, source_token, source_snapshot
        guard_mutation(session)
        draft = create_draft(db, session.id, user.id)
        lead = next((i for i in session.investigators if i.assignment_role.value == "LEAD"), None)
        draft.official_form = {"source_token": source_token(db, session), "source_snapshot": source_snapshot(db, session), "html_report": {
            "revision": "statement-html-1", "session_id": str(session.id), "subject": session.title,
            "investigator_id": str(lead.investigator_id) if lead else None, "clerk_id": None, "blocks": []}}
        record_audit(db, action=AuditAction.REPORT_DRAFT_CREATED, user_id=user.id,
                     entity_type="report_draft", entity_id=draft.id,
                     metadata={"form": report_html.CATALOGUE["revision"], "session_id": session.id}, ip_address=client_ip(request))
        db.commit()
    return report_html.state_for(draft, db, session)


@router.post("/investigations/{session_id}/report/html/preview")
def preview_html(body: HtmlReportUpdate, session: InvestigationSession = Depends(get_accessible_session),
                 _: User = Depends(require_permission("reports.read", "reports.generate")), db: Session = Depends(get_db)):
    from app.services.report_document import render
    draft = _require_draft(db, session)
    _check_token(body, draft)
    if draft.status == ReportStatus.FINAL:
        from app.services.report_storage import read_file, sha256_bytes
        report = db.scalar(select(GeneratedReport).where(GeneratedReport.draft_id == draft.id,
            GeneratedReport.session_id == session.id, GeneratedReport.format_key == "statement-html-1")
            .order_by(GeneratedReport.report_version.desc()).limit(1))
        html = read_file(report.html_path) if report and report.html_path else None
        if html is None:
            raise HTTPException(404, detail="report_file_missing")
        if sha256_bytes(html) != report.html_sha256:
            raise HTTPException(409, detail="report_artifact_integrity_failed")
        return {"html": html.decode("utf-8")}
    try:
        document = report_html.prepare_document(body, draft, session, db, populate_untouched=False)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {"html": render(document, session, highlight=True)}


@router.post("/investigations/{session_id}/report/html/refresh-sources")
def refresh_sources(body: TokenInput, request: Request,
                    session: InvestigationSession = Depends(get_accessible_session),
                    user: User = Depends(require_permission("reports.generate")), db: Session = Depends(get_db)):
    from app.services.report_context import completed_recordings
    from app.services.report_draft import set_recordings
    session = _lock_session(db, session)
    guard_mutation(session)
    draft = _require_draft(db, session)
    _guard_editable(draft)
    _check_token(body, draft)
    set_recordings(db, draft, [r.id for r in completed_recordings(db, session.id)], user.id)
    draft.official_form = {**(draft.official_form or {}), "html_review": None}
    draft.revision += 1
    _audit(db, request, user, AuditAction.REPORT_DRAFT_UPDATED, session, draft.id, action_detail="refresh_import_sources")
    db.commit()
    return report_html.state_for(draft, db, session)


@router.post("/investigations/{session_id}/report/html/review")
def review_html(body: ReviewInput, request: Request,
                session: InvestigationSession = Depends(get_accessible_session),
                user: User = Depends(require_permission("reports.generate")), db: Session = Depends(get_db)):
    from app.services.report_finalize import content_blockers
    session = _lock_session(db, session)
    guard_mutation(session)
    draft = _require_draft(db, session)
    _guard_editable(draft)
    _check_token(body, draft)
    current = source_token(db, session)
    if body.expected_source_token != current:
        raise HTTPException(409, detail="report_sources_changed")
    if (draft.official_form or {}).get("source_token") not in (None, current) and not body.acknowledge_source_changes:
        raise HTTPException(409, detail="report_source_changes_need_review")
    reasons = content_blockers(session, report_html.document_for(draft))
    if reasons:
        raise HTTPException(422, detail={"code": "report_incomplete", "reasons": reasons})
    draft.official_form = {**(draft.official_form or {}), "source_token": current, "source_snapshot": source_snapshot(db, session),
                          "html_review": {"token": review_token(db, session, draft), "by": str(user.id),
                                          "at": datetime.now(timezone.utc).isoformat(),
                                          "source_changes_acknowledged": body.acknowledge_source_changes}}
    _audit(db, request, user, AuditAction.REPORT_DRAFT_UPDATED, session, draft.id, action_detail="content_reviewed")
    db.commit()
    return report_html.state_for(draft, db, session)


@router.get("/investigations/{session_id}/report")
def report_status(session: InvestigationSession = Depends(get_accessible_session),
                  _: User = Depends(require_permission("reports.read", "reports.generate")), db: Session = Depends(get_db)):
    draft = _require_draft(db, session)
    return {"id": str(draft.id), "status": draft.status.value, "stale": [], "case_subject": report_html.document_for(draft)["subject"],
            "token": report_html.token_for(draft)}


@router.post("/investigations/{session_id}/report/reopen")
def reopen_html(body: ReopenInput, request: Request, session: InvestigationSession = Depends(get_accessible_session),
                user: User = Depends(require_permission("reports.generate")), db: Session = Depends(get_db)):
    session = _lock_session(db, session)
    draft = _require_draft(db, session)
    _check_token(body, draft)
    if draft.status != ReportStatus.FINAL:
        raise HTTPException(409, detail="report_not_final")
    previous_state = session.workflow_state
    if previous_state != "IN_PROGRESS" and "investigations.update" not in user.permission_codes:
        raise HTTPException(403, detail="forbidden")
    draft.status = ReportStatus.DRAFT
    draft.official_form = {**(draft.official_form or {}), "html_review": None}
    draft.revision += 1
    session.workflow_state = "IN_PROGRESS"
    session.revision += 1
    if previous_state == "ARCHIVED":
        from app.models import SessionStatus
        session.status = SessionStatus.DRAFT
    record_audit(db, action=AuditAction.INVESTIGATION_UPDATED, user_id=user.id,
                 entity_type="investigation_session", entity_id=session.id,
                 metadata={"workflow_before": previous_state, "workflow_after": "IN_PROGRESS",
                           "reason": body.reason, "report_id": str(draft.id), "revision": session.revision},
                 ip_address=client_ip(request))
    _audit(db, request, user, AuditAction.REPORT_DRAFT_REOPENED, session, draft.id, reason=body.reason)
    db.commit()
    return report_html.state_for(draft, db, session)


def _archive(db, session):
    rows = db.scalars(select(GeneratedReport).where(GeneratedReport.session_id == session.id,
                     GeneratedReport.format_key == "statement-html-1").order_by(GeneratedReport.report_version.desc())).all()
    draft = get_draft(db, session.id)
    reasons = check_ready(db, session, draft) if draft else ["report_draft_not_found"]
    return {"reports": [{"id": str(r.id), "report_version": r.report_version, "report_number": r.report_number,
                          "created_at": r.created_at, "html_sha256": r.html_sha256, "pdf_sha256": r.pdf_sha256,
                          "context_sha256": r.context_sha256} for r in rows],
            "can_finalize": not reasons, "blocked_reasons": reasons}


@router.get("/investigations/{session_id}/reports")
def list_reports(session: InvestigationSession = Depends(get_accessible_session),
                 _: User = Depends(require_permission("reports.read", "reports.generate")), db: Session = Depends(get_db)):
    return _archive(db, session)


@router.post("/investigations/{session_id}/reports", status_code=201)
def issue_html(body: TokenInput, request: Request, session: InvestigationSession = Depends(get_accessible_session),
               user: User = Depends(require_permission("reports.finalize")), db: Session = Depends(get_db)):
    session = _lock_session(db, session)
    draft = _require_draft(db, session)
    _check_token(body, draft)
    report = finalize(db, session, draft, user)
    _audit(db, request, user, AuditAction.REPORT_GENERATED, session, report.id,
           version=report.report_version, html_sha256=report.html_sha256, pdf_sha256=report.pdf_sha256)
    db.commit()
    return _archive(db, session)


def _issued(db, session, report_id):
    report = db.get(GeneratedReport, report_id)
    if report is None or report.session_id != session.id or report.format_key != "statement-html-1":
        raise HTTPException(404, detail="report_not_found")
    return report


@router.get("/investigations/{session_id}/reports/{report_id}/file")
def download_report(report_id: uuid.UUID, request: Request, format: Literal["html", "pdf"] = "pdf",
                    session: InvestigationSession = Depends(get_accessible_session),
                    user: User = Depends(require_permission("reports.read", "reports.generate")), db: Session = Depends(get_db)):
    report = _issued(db, session, report_id)
    path = absolute_path(report.html_path if format == "html" else report.pdf_path)
    if path is None:
        raise HTTPException(404, detail="report_file_missing")
    _audit(db, request, user, AuditAction.REPORT_DOWNLOADED, session, report.id, format=format)
    db.commit()
    return FileResponse(path, media_type="text/html" if format == "html" else "application/pdf",
                        filename=f"report-{session.session_number}-v{report.report_version}.{format}",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/investigations/{session_id}/reports/{report_id}/verify")
def verify_report(report_id: uuid.UUID, request: Request, session: InvestigationSession = Depends(get_accessible_session),
                  user: User = Depends(require_permission("reports.read", "reports.generate")), db: Session = Depends(get_db)):
    report = _issued(db, session, report_id)
    result = verify(db, report)
    _audit(db, request, user, AuditAction.REPORT_VERIFIED, session, report.id, ok=result["ok"])
    db.commit()
    return result


@router.api_route("/investigations/{session_id}/report", methods=["POST", "PUT", "PATCH", "DELETE"])
@router.api_route("/investigations/{session_id}/report/blocks/{retired_path:path}", methods=["POST", "PATCH", "PUT", "DELETE"])
@router.post("/investigations/{session_id}/report/refresh")
@router.api_route("/report-forms/m53/{retired_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
@router.api_route("/report-forms/m53", methods=["GET", "POST", "PUT"])
@router.api_route("/report-templates/{retired_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@router.api_route("/report-templates", methods=["GET", "POST"])
@router.api_route("/investigations/{session_id}/report/m53/{retired_path:path}", methods=["GET", "POST", "PUT"])
@router.api_route("/investigations/{session_id}/report/m53", methods=["GET", "POST", "PUT"])
def retired_report_format(request: Request, _: User = Depends(require_permission("reports.read", "reports.generate", "reports.templates.manage"))):
    raise HTTPException(410, detail="legacy_report_format_retired_use_html")


@router.put("/investigations/{session_id}/report/html")
def save_html_report(body: HtmlReportUpdate, request: Request,
                     session: InvestigationSession = Depends(get_accessible_session),
                     user: User = Depends(require_permission("reports.generate")), db: Session = Depends(get_db)):
    session = db.scalar(select(InvestigationSession).where(InvestigationSession.id == session.id).with_for_update().execution_options(populate_existing=True))
    draft = db.scalar(select(ReportDraft).where(ReportDraft.session_id == session.id).with_for_update().execution_options(populate_existing=True))
    if draft is None:
        raise HTTPException(404, detail="report_draft_not_found")
    _guard_editable(draft)
    from app.services.workflow import guard_mutation
    guard_mutation(session)
    if body.expected_token != report_html.token_for(draft):
        raise HTTPException(409, detail="html_report_changed")
    try:
        document = report_html.prepare_document(body, draft, session, db)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    previous_document = report_html.document_for(draft)
    draft.official_form = {**(draft.official_form or {}), "html_report": document}
    draft.updated_by = user.id
    draft.revision += 1
    record_audit(db, action=AuditAction.REPORT_DRAFT_UPDATED, user_id=user.id,
                 entity_type="report_draft", entity_id=draft.id,
                 metadata={"form": report_html.CATALOGUE["revision"], "blocks": len(document["blocks"]), "session_id": session.id,
                           "before": previous_document, "after": document},
                 ip_address=client_ip(request))
    db.commit()
    return report_html.state_for(draft, db, session)


