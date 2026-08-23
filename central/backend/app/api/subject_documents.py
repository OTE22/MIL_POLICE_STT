"""Identity-document scans of interviewed subjects.

Access is gated by the dedicated `subjects.documents.view` permission *in
addition to* resource access to the session, because an ID or passport scan is
more sensitive than the transcript itself. Every upload, view and deletion is
written to the audit log.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.deps import client_ip, get_accessible_session, require_permission
from app.db.session import get_db
from app.models import AuditAction, InvestigationSession, Subject, SubjectDocument, User
from app.schemas.investigations import SubjectDocumentOut
from app.services.audit import record_audit
from app.services.document_storage import (
    InvalidDocumentError,
    delete_document_file,
    store_document,
)
from app.services.storage import absolute_path, sanitize_filename

router = APIRouter(tags=["subject-documents"])


def _load(db: Session, session: InvestigationSession, document_id: uuid.UUID) -> SubjectDocument:
    doc = db.get(SubjectDocument, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document_not_found")
    subject = db.get(Subject, doc.subject_id)
    if subject is None or subject.session_id != session.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document_not_found")
    return doc


@router.post(
    "/investigations/{session_id}/subject-documents/{document_id}/file",
    response_model=SubjectDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_file(
    document_id: uuid.UUID,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("subjects.documents.view")),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> SubjectDocumentOut:
    if "investigations.update" not in user.permission_codes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
    doc = _load(db, session, document_id)
    if doc.storage_path:
        # The original is evidence: replacing it requires an explicit delete first.
        raise HTTPException(status.HTTP_409_CONFLICT, detail="document_file_exists")
    try:
        rel, size, sha256, ext, mime = await store_document(file, session.id, doc.id)
    except InvalidDocumentError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from exc
    doc.storage_path = rel
    doc.original_filename = sanitize_filename(file.filename or f"document.{ext}")
    doc.mime_type = mime
    doc.size_bytes = size
    doc.sha256 = sha256
    doc.uploaded_by = user.id
    record_audit(
        db,
        action=AuditAction.SUBJECT_DOCUMENT_UPLOADED,
        user_id=user.id,
        entity_type="subject_document",
        entity_id=doc.id,
        metadata={
            "session_id": session.id,
            "document_type": doc.document_type,
            "mime_type": mime,
            "size_bytes": size,
            "sha256": sha256,
        },
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(doc)
    from app.api.investigations import _document_out

    return _document_out(db, doc)


@router.get("/investigations/{session_id}/subject-documents/{document_id}/file")
def download_document_file(
    document_id: uuid.UUID,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("subjects.documents.view")),
    db: Session = Depends(get_db),
) -> FileResponse:
    doc = _load(db, session, document_id)
    if not doc.storage_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document_file_not_found")
    path = absolute_path(doc.storage_path)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document_file_not_found")
    record_audit(
        db,
        action=AuditAction.SUBJECT_DOCUMENT_VIEWED,
        user_id=user.id,
        entity_type="subject_document",
        entity_id=doc.id,
        metadata={"session_id": session.id, "document_type": doc.document_type},
        ip_address=client_ip(request),
    )
    db.commit()
    # PDFs are never rendered inline: always delivered as an attachment.
    disposition = "attachment" if doc.mime_type == "application/pdf" else "inline"
    return FileResponse(
        path,
        media_type=doc.mime_type or "application/octet-stream",
        filename=doc.original_filename or "document",
        content_disposition_type=disposition,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.delete(
    "/investigations/{session_id}/subject-documents/{document_id}/file",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document_scan(
    document_id: uuid.UUID,
    request: Request,
    session: InvestigationSession = Depends(get_accessible_session),
    user: User = Depends(require_permission("subjects.documents.view")),
    db: Session = Depends(get_db),
):
    from fastapi import Response

    if "investigations.update" not in user.permission_codes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
    doc = _load(db, session, document_id)
    if doc.storage_path:
        delete_document_file(doc.storage_path)
    record_audit(
        db,
        action=AuditAction.SUBJECT_DOCUMENT_DELETED,
        user_id=user.id,
        entity_type="subject_document",
        entity_id=doc.id,
        metadata={"session_id": session.id, "sha256": doc.sha256, "document_type": doc.document_type},
        ip_address=client_ip(request),
    )
    doc.storage_path = None
    doc.original_filename = None
    doc.mime_type = None
    doc.size_bytes = None
    doc.sha256 = None
    doc.uploaded_by = None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
