"""The official محضر template: one format, a version history, and a gate before activation.

Deliberately small. There is ONE approved layout, so this is not a document designer - it is
"here is the current official form, download it, edit it in Word, upload the replacement,
validate it, activate it". Everything about how the report LOOKS lives inside that .docx.

Validation gates ACTIVATION, not upload: a bad file can be stored and inspected, but it can
never become the form that official documents are printed on.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import client_ip, require_permission
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (
    AuditAction,
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

    next_version = int(db.scalar(select(func.max(ReportTemplateVersion.version))) or 0) + 1
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
