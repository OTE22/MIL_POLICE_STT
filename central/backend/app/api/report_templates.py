"""The official محضر template: one format, a version history, and a gate before activation.

Layouts can be authored by annotating sample pages or uploading a Word template.
Both paths produce a versioned DOCX and share validation, review and activation.

Validation gates ACTIVATION, not upload: a bad file can be stored and inspected, but it can
never become the form that official documents are printed on.
"""

from __future__ import annotations

import logging
import uuid
import io

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.core.deps import client_ip, require_permission
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (
    AuditAction,
    AuditLog,
    GeneratedReport,
    ReportTemplateVersion,
    TemplateValidationStatus,
    User,
)
from app.schemas.report_templates import (
    TemplatePlaceholdersOut,
    TemplateVersionOut,
    TemplatesOut,
)
from app.services.audit import record_audit
from app.services.report_layout import ReportLayout, sample_pages, build_layout, read_layout, MAX_BYTES
from app.services.report_renderer import (
    ALLOWED_PLACEHOLDERS,
    LIST_PLACEHOLDERS,
    REQUIRED_PLACEHOLDERS,
    validate_template,
)
from app.services.report_storage import (
    absolute_path,
    atomic_write,
    remove_file,
    template_relative_path,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["report-templates"])

MANAGE = "reports.templates.manage"


def _lock_registry(db: Session) -> None:
    db.execute(select(func.pg_advisory_xact_lock(8432701)))


@router.post('/report-templates/sample')
async def import_sample(file: UploadFile = File(...), _: User = Depends(require_permission(MANAGE))):
    data = await file.read(MAX_BYTES + 1)
    try:
        return {'pages': sample_pages(data)}
    except Exception as exc:
        log.info('Report sample could not be decoded: %s', type(exc).__name__)
        raise HTTPException(422, detail='report_sample_invalid') from exc


@router.post('/report-templates/layout', response_model=TemplatesOut, status_code=201)
async def save_layout(body: ReportLayout, request: Request,
                      user: User = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    try:
        data = build_layout(body)
    except Exception as exc:
        raise HTTPException(422, detail='report_layout_invalid') from exc
    result = validate_template(data)
    if not result.ok:
        log.error('Generated layout failed validation: %s', result.message)
        raise HTTPException(422, detail='report_layout_invalid')
    # The existing upload path handles versioning, audit, hashing and atomic storage.
    return await upload_template(request, UploadFile(file=io.BytesIO(data), filename=body.name + '.docx'), user, db)


@router.get('/report-templates/{template_id}/layout')
def get_layout(template_id: uuid.UUID, _: User = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    template = _require(db, template_id)
    path = absolute_path(template.storage_path)
    if path is None or template.validation_status != TemplateValidationStatus.VALID:
        raise HTTPException(404, detail='report_template_file_missing')
    layout = read_layout(path.read_bytes())
    if layout is None:
        raise HTTPException(404, detail='report_layout_not_available')
    return layout


@router.get('/report-templates/{template_id}/preview')
def preview_layout(template_id: uuid.UUID, _: User = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    from app.services.report_renderer import render, sample_context, RenderError
    template = _require(db, template_id)
    path = absolute_path(template.storage_path)
    if path is None or template.validation_status != TemplateValidationStatus.VALID:
        raise HTTPException(404, detail='report_template_file_missing')
    try:
        data = render(path.read_bytes(), sample_context())
    except RenderError as exc:
        raise HTTPException(409, detail=exc.code) from exc
    return Response(data,
        media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': 'attachment; filename="template-preview.docx"', 'Cache-Control': 'no-store'})


def _out(db: Session, template: ReportTemplateVersion) -> TemplateVersionOut:
    in_use = int(
        db.scalar(
            select(func.count(GeneratedReport.id)).where(
                GeneratedReport.template_version_id == template.id
            )
        )
        or 0
    )
    return TemplateVersionOut(
        id=template.id,
        version=template.version,
        original_filename=template.original_filename,
        size_bytes=template.size_bytes,
        sha256=template.sha256,
        validation_status=template.validation_status,
        validation_message=template.validation_message,
        is_development=template.is_development,
        is_active=template.is_active,
        activated_at=template.activated_at,
        notes=template.notes,
        uploaded_by=template.uploaded_by,
        created_at=template.created_at,
        reports_issued=in_use,
    )


def _all(db: Session) -> list[ReportTemplateVersion]:
    return list(
        db.scalars(select(ReportTemplateVersion).order_by(ReportTemplateVersion.version.desc())).all()
    )


def active_template(db: Session) -> ReportTemplateVersion | None:
    return db.scalar(select(ReportTemplateVersion).where(ReportTemplateVersion.is_active.is_(True)))


def _require(db: Session, template_id: uuid.UUID) -> ReportTemplateVersion:
    template = db.get(ReportTemplateVersion, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="report_template_not_found")
    return template


@router.get("/report-templates", response_model=TemplatesOut)
def list_templates(
    _: User = Depends(require_permission(MANAGE)),
    db: Session = Depends(get_db),
) -> TemplatesOut:
    rows = _all(db)
    current = next((t for t in rows if t.is_active), None)
    return TemplatesOut(
        active=_out(db, current) if current else None,
        # Production must not issue an official document on the development stand-in.
        production_ready=bool(
            current
            and not current.is_development
            and current.validation_status is TemplateValidationStatus.VALID
        ),
        environment=get_settings().environment,
        versions=[_out(db, t) for t in rows],
    )


@router.get("/report-templates/placeholders", response_model=TemplatePlaceholdersOut)
def list_placeholders(
    _: User = Depends(require_permission(MANAGE)),
) -> TemplatePlaceholdersOut:
    """The catalogue a template author may use. Anything else fails validation."""
    return TemplatePlaceholdersOut(
        scalars=sorted(ALLOWED_PLACEHOLDERS - LIST_PLACEHOLDERS),
        lists=sorted(LIST_PLACEHOLDERS),
        required=sorted(REQUIRED_PLACEHOLDERS),
    )


@router.get("/report-templates/{template_id}/file")
def download_template(
    template_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission(MANAGE)),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Download to edit in Word - the intended way to produce the next version."""
    template = _require(db, template_id)
    path = absolute_path(template.storage_path)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="report_template_file_missing")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=template.original_filename or f"report-template-v{template.version}.docx",
        content_disposition_type="attachment",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/report-templates", response_model=TemplatesOut, status_code=201)
async def upload_template(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_permission(MANAGE)),
    db: Session = Depends(get_db),
) -> TemplatesOut:
    """Store a new version and validate it. It does NOT become active by itself."""
    settings = get_settings()
    data = await file.read()
    limit = settings.report_template_upload_max_mb * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "report_template_too_large", "max_mb": settings.report_template_upload_max_mb},
        )

    result = validate_template(data)

    _lock_registry(db)
    previous_deleted = db.scalar(select(func.max(AuditLog.safe_metadata['version'].as_integer())).where(
        AuditLog.action == AuditAction.REPORT_TEMPLATE_DELETED.value)) or 0
    next_version = max(int(db.scalar(select(func.max(ReportTemplateVersion.version))) or 0), int(previous_deleted)) + 1
    template = ReportTemplateVersion(
        version=next_version,
        storage_path="",
        sha256="",
        original_filename=file.filename,
        validation_status=(
            TemplateValidationStatus.VALID if result.ok else TemplateValidationStatus.INVALID
        ),
        validation_message=result.message,
        is_development=False,
        is_active=False,
    )
    template.uploaded_by = user.id
    db.add(template)
    db.flush()

    rel, size, digest = atomic_write(template_relative_path(template.id), data)
    template.storage_path, template.size_bytes, template.sha256 = rel, size, digest

    record_audit(
        db,
        action=AuditAction.REPORT_TEMPLATE_UPLOADED,
        user_id=user.id,
        entity_type="report_template",
        entity_id=template.id,
        metadata={
            "version": next_version,
            "filename": file.filename,
            "sha256": digest,
            "valid": result.ok,
            "message": result.message,
            "warnings": result.warnings,
        },
        ip_address=client_ip(request),
    )
    try:
        db.commit()
    except Exception:
        # No orphan file may outlive a failed insert.
        remove_file(rel)
        raise
    log.info("report template v%d uploaded valid=%s (%s)", next_version, result.ok, result.message)
    return list_templates(user, db)


@router.post("/report-templates/{template_id}/activate", response_model=TemplatesOut)
def activate_template(
    template_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission(MANAGE)),
    db: Session = Depends(get_db),
) -> TemplatesOut:
    """Make this version the official form. Only a VALID version may be activated."""
    _lock_registry(db)
    template = _require(db, template_id)
    if template.validation_status is not TemplateValidationStatus.VALID:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "report_template_invalid", "message": template.validation_message},
        )

    previous = active_template(db)
    if previous is not None and previous.id != template.id:
        previous.is_active = False
        record_audit(
            db,
            action=AuditAction.REPORT_TEMPLATE_DEACTIVATED,
            user_id=user.id,
            entity_type="report_template",
            entity_id=previous.id,
            metadata={"version": previous.version, "replaced_by": template.version},
            ip_address=client_ip(request),
        )

    template.is_active = True
    template.activated_at = utcnow()
    record_audit(
        db,
        action=AuditAction.REPORT_TEMPLATE_ACTIVATED,
        user_id=user.id,
        entity_type="report_template",
        entity_id=template.id,
        metadata={"version": template.version, "sha256": template.sha256},
        ip_address=client_ip(request),
    )
    db.commit()
    log.info("report template v%d activated by %s", template.version, user.username)
    return list_templates(user, db)


@router.delete("/report-templates/{template_id}", response_model=TemplatesOut)
def delete_template(
    template_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission(MANAGE)),
    db: Session = Depends(get_db),
) -> TemplatesOut:
    _lock_registry(db)
    template = db.scalar(select(ReportTemplateVersion).where(
        ReportTemplateVersion.id == template_id).with_for_update())
    if template is None:
        raise HTTPException(404, detail="report_template_not_found")
    if template.is_active:
        raise HTTPException(409, detail="report_template_delete_active")
    if db.scalar(select(GeneratedReport.id).where(
        GeneratedReport.template_version_id == template_id).limit(1)):
        raise HTTPException(409, detail="report_template_delete_used")
    relative_path = template.storage_path
    record_audit(db, action=AuditAction.REPORT_TEMPLATE_DELETED, user_id=user.id,
                 entity_type="report_template", entity_id=template.id,
                 metadata={"version": template.version, "filename": template.original_filename,
                           "sha256": template.sha256}, ip_address=client_ip(request))
    db.delete(template)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail="report_template_delete_used") from exc
    # Commit first so a rolled-back deletion never loses the template file.
    try:
        remove_file(relative_path)
    except OSError:
        log.exception("Deleted template file cleanup failed for %s", template_id)
    return list_templates(user, db)


@router.post("/report-templates/{template_id}/revalidate", response_model=TemplatesOut)
def revalidate_template(
    template_id: uuid.UUID,
    user: User = Depends(require_permission(MANAGE)),
    db: Session = Depends(get_db),
) -> TemplatesOut:
    """Re-run the checks - useful after the placeholder catalogue changes."""
    template = _require(db, template_id)
    path = absolute_path(template.storage_path)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="report_template_file_missing")
    result = validate_template(path.read_bytes())
    template.validation_status = (
        TemplateValidationStatus.VALID if result.ok else TemplateValidationStatus.INVALID
    )
    template.validation_message = result.message
    if not result.ok and template.is_active:
        # An active template that no longer validates must not keep printing documents.
        template.is_active = False
    db.commit()
    return list_templates(user, db)
