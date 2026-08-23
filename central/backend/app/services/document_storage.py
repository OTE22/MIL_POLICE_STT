"""Storage for subject identity documents (ID / passport scans).

Treated exactly like the audio originals: the uploaded file is never modified,
its SHA-256 is recorded, the format is verified by magic bytes (never by the
file name) and the path is resolved inside the storage root.

Only images and PDF are accepted. PDFs are always served as attachments and
never rendered inline, so a malicious PDF cannot execute in the app origin.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import get_settings
from app.services.storage import InvalidAudioError, sanitize_filename

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024  # 20 MiB per scan

ALLOWED_DOCUMENT_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}
ALLOWED_DOCUMENT_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}


class InvalidDocumentError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sniff_document(head: bytes) -> str | None:
    """Identify the container from its magic bytes."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"%PDF-"):
        return "pdf"
    return None


def document_relative_path(session_id: uuid.UUID, document_id: uuid.UUID, ext: str) -> str:
    return f"subject-documents/{session_id}/{document_id}.{ext}"


async def store_document(
    upload: UploadFile, session_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[str, int, str, str, str]:
    """Stream a scan to disk.

    Returns (relative_path, size_bytes, sha256, detected_extension, mime_type).
    """
    settings = get_settings()
    declared_mime = (upload.content_type or "").split(";")[0].strip().lower()
    if declared_mime and declared_mime not in ALLOWED_DOCUMENT_MIME:
        raise InvalidDocumentError("unsupported_document_type")
    ext_declared = Path(upload.filename or "").suffix.lower().lstrip(".")
    if ext_declared and ext_declared not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise InvalidDocumentError("unsupported_document_type")

    tmp_dir = settings.storage_root / "subject-documents" / str(session_id)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"{document_id}.part"
    digest = hashlib.sha256()
    size = 0
    head = b""
    try:
        with tmp.open("wb") as fh:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                if not head:
                    head = chunk[:16]
                size += len(chunk)
                if size > MAX_DOCUMENT_BYTES:
                    raise InvalidDocumentError("document_too_large")
                digest.update(chunk)
                fh.write(chunk)
        if size == 0:
            raise InvalidDocumentError("empty_file")
        detected = sniff_document(head)
        if detected is None:
            raise InvalidDocumentError("unsupported_document_type")
        rel = document_relative_path(session_id, document_id, detected)
        target = (settings.storage_root / rel).resolve()
        if settings.storage_root.resolve() not in target.parents:
            raise InvalidDocumentError("invalid_path")
        tmp.replace(target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    mime = {
        "jpg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "pdf": "application/pdf",
    }[detected]
    return rel, size, digest.hexdigest(), detected, mime


def delete_document_file(relative: str) -> None:
    settings = get_settings()
    path = (settings.storage_root / relative).resolve()
    if settings.storage_root.resolve() in path.parents:
        path.unlink(missing_ok=True)


__all__ = [
    "MAX_DOCUMENT_BYTES",
    "ALLOWED_DOCUMENT_EXTENSIONS",
    "ALLOWED_DOCUMENT_MIME",
    "InvalidDocumentError",
    "InvalidAudioError",
    "sanitize_filename",
    "sniff_document",
    "store_document",
    "delete_document_file",
    "document_relative_path",
]
