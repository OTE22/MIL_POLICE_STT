"""Central audio storage: validated, hashed, path-traversal safe."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import get_settings

_SAFE_EXT = re.compile(r"^[a-z0-9]{1,5}$")

# Magic-byte sniffing: never trust the filename or the declared MIME type.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "wav": (b"RIFF",),
    "mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xe3"),
    "m4a": (b"ftyp",),
    "webm": (b"\x1a\x45\xdf\xa3",),
}


class InvalidAudioError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sanitize_filename(name: str) -> str:
    name = Path(name).name  # strip any directory part
    name = re.sub(r"[^\w.\-؀-ۿ ]", "_", name, flags=re.UNICODE).strip()
    return name[:255] or "recording"


def extension_of(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext if _SAFE_EXT.match(ext) else ""


def sniff_format(head: bytes) -> str | None:
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head[4:8] == b"ftyp":
        return "m4a"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


def validate_declared(filename: str, mime_type: str, size_bytes: int) -> str:
    """Validate metadata declared at token-request time. Returns the extension."""
    settings = get_settings()
    ext = extension_of(filename)
    if ext not in settings.allowed_audio_extensions:
        raise InvalidAudioError("unsupported_extension")
    if mime_type.split(";")[0].strip().lower() not in settings.allowed_audio_mime_types:
        raise InvalidAudioError("unsupported_mime_type")
    if size_bytes <= 0:
        raise InvalidAudioError("empty_file")
    if size_bytes > settings.max_upload_bytes:
        raise InvalidAudioError("file_too_large")
    return ext


def recording_relative_path(session_id: uuid.UUID, recording_id: uuid.UUID, ext: str) -> str:
    return f"recordings/{session_id}/{recording_id}.{ext}"


async def store_upload(upload: UploadFile, session_id: uuid.UUID, recording_id: uuid.UUID, ext: str) -> tuple[str, int, str]:
    """Stream the upload to disk, enforcing the size limit and sniffing the format.

    Returns (relative_path, size_bytes, sha256).
    """
    settings = get_settings()
    rel = recording_relative_path(session_id, recording_id, ext)
    target = (settings.storage_root / rel).resolve()
    if settings.storage_root.resolve() not in target.parents:
        raise InvalidAudioError("invalid_path")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
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
                if size > settings.max_upload_bytes:
                    raise InvalidAudioError("file_too_large")
                digest.update(chunk)
                fh.write(chunk)
        if size == 0:
            raise InvalidAudioError("empty_file")
        sniffed = sniff_format(head)
        if sniffed is None:
            raise InvalidAudioError("malformed_audio")
        tmp.replace(target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return rel, size, digest.hexdigest()


def absolute_path(relative: str) -> Path | None:
    settings = get_settings()
    path = (settings.storage_root / relative).resolve()
    if settings.storage_root.resolve() not in path.parents or not path.is_file():
        return None
    return path
