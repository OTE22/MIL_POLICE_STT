"""Storage for report templates and issued documents: sniffed, hashed, path-confined.

`document_storage` cannot be reused here - its MIME whitelist is built for identity scans
and rejects .docx - but the guarantees are the same ones, and deliberately so: nothing is
trusted from a filename, every write lands atomically, and no path may escape /storage.

The write order for an issued report matters and is enforced by `atomic_write`:
render to a temporary file -> validate -> hash -> os.replace into place. A crash therefore
leaves either the previous state or the finished file, never a half-written official
document.
"""

from __future__ import annotations

import hashlib
import io
import uuid
import zipfile
from pathlib import Path

from app.config import get_settings

TEMPLATES_DIR = "report-templates"
REPORTS_DIR = "reports"

# A .docx is a ZIP whose first bytes are the local-file-header magic. Real Word files also
# always contain word/document.xml - checking both rejects a renamed .zip of anything else.
ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
DOCX_REQUIRED_ENTRY = "word/document.xml"

# Zip-bomb and abuse limits for an ADMIN-uploaded template. Generous for a Word document
# with a letterhead image, tight enough that nothing pathological reaches the parser.
MAX_ENTRIES = 2000
MAX_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


class InvalidDocxError(Exception):
    """The bytes are not a Word document we are willing to open."""

    def __init__(self, code: str, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sniff_docx(data: bytes) -> None:
    """Raise unless `data` really is a Word document. Structure only - no Jinja yet."""
    if not data:
        raise InvalidDocxError("empty_file")
    if not any(data.startswith(magic) for magic in ZIP_MAGIC):
        raise InvalidDocxError("not_a_docx")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if len(names) > MAX_ENTRIES:
                raise InvalidDocxError("too_many_entries")
            if DOCX_REQUIRED_ENTRY not in names:
                raise InvalidDocxError("not_a_docx")

            expanded = 0
            for info in zf.infolist():
                # A member path that escapes its own archive is never legitimate here.
                if info.filename.startswith("/") or ".." in Path(info.filename).parts:
                    raise InvalidDocxError("path_traversal_in_archive", info.filename)
                expanded += info.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise InvalidDocxError("expanded_too_large")
                if info.compress_size > 0 and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                    raise InvalidDocxError("suspicious_compression_ratio", info.filename)

            # Macros are executable content; an official form has no business carrying any.
            if any(name.lower().endswith("vbaproject.bin") for name in names):
                raise InvalidDocxError("macros_not_allowed")

            # Relationships that reach out to the network turn a document into a beacon.
            for name in names:
                if name.endswith(".rels"):
                    rels = zf.read(name).decode("utf-8", "ignore").lower()
                    if 'targetmode="external"' in rels and ("http://" in rels or "https://" in rels):
                        raise InvalidDocxError("external_relationship_not_allowed", name)
    except zipfile.BadZipFile as exc:
        raise InvalidDocxError("corrupt_docx") from exc


def _confined(relative: str) -> Path:
    settings = get_settings()
    root = settings.storage_root.resolve()
    path = (settings.storage_root / relative).resolve()
    if root not in path.parents:
        raise InvalidDocxError("invalid_path")
    return path


def template_relative_path(template_id: uuid.UUID) -> str:
    return f"{TEMPLATES_DIR}/{template_id}.docx"


def report_relative_path(session_id: uuid.UUID, report_id: uuid.UUID, version: int) -> str:
    return f"{REPORTS_DIR}/{session_id}/v{version}-{report_id}.docx"


def context_relative_path(session_id: uuid.UUID, report_id: uuid.UUID, version: int) -> str:
    return f"{REPORTS_DIR}/{session_id}/v{version}-{report_id}.context.json"


def atomic_write(relative: str, data: bytes) -> tuple[str, int, str]:
    """Write bytes into storage atomically. Returns (relative_path, size, sha256)."""
    target = _confined(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        tmp.write_bytes(data)
        tmp.replace(target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return relative, len(data), sha256_bytes(data)


def read_file(relative: str) -> bytes | None:
    try:
        path = _confined(relative)
    except InvalidDocxError:
        return None
    return path.read_bytes() if path.is_file() else None


def absolute_path(relative: str) -> Path | None:
    """The on-disk path, or None when it is missing or outside storage."""
    try:
        path = _confined(relative)
    except InvalidDocxError:
        return None
    return path if path.is_file() else None


def remove_file(relative: str) -> None:
    """Undo a write whose database row never committed - no orphan official documents."""
    try:
        path = _confined(relative)
    except InvalidDocxError:
        return
    path.unlink(missing_ok=True)


def file_matches(relative: str, expected_sha256: str) -> bool:
    """Integrity check, not a signature: do the bytes still hash to what we recorded?"""
    path = absolute_path(relative)
    return path is not None and sha256_file(path) == expected_sha256
