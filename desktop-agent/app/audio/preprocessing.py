"""Audio validation, hashing and preprocessing (original is never modified)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.audio import ffmpeg_service
from app.config import Settings

ALLOWED_EXTENSIONS = {"wav", "mp3", "m4a", "webm"}
ALLOWED_MIME = {
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/vnd.wave",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/x-m4a",
    "audio/m4a",
    "audio/aac",
    "audio/webm",
    "video/webm",
    "audio/ogg",
    "application/octet-stream",
    "",
}


class AudioValidationError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass
class AudioMetadata:
    original_filename: str
    mime_type: str
    size_bytes: int
    duration_seconds: float
    sha256: str
    codec_name: str | None
    sample_rate: int | None
    channels: int | None


def sanitize_filename(name: str) -> str:
    name = Path(name or "recording").name
    name = re.sub(r"[^\w.\-؀-ۿ ]", "_", name, flags=re.UNICODE).strip()
    return name[:200] or "recording"


def extension_of(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def sniff_format(head: bytes) -> str | None:
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head[4:8] == b"ftyp":
        return "m4a"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    if head.startswith(b"OggS"):
        return "webm"  # opus-in-ogg from some browsers; ffmpeg handles it
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_original(path: Path, filename: str, mime_type: str, settings: Settings) -> AudioMetadata:
    """Validate extension, MIME, size, magic bytes, readability and duration."""
    ext = extension_of(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise AudioValidationError("unsupported_audio", f"extension .{ext or '?'} not allowed")
    if mime_type.split(";")[0].strip().lower() not in ALLOWED_MIME:
        raise AudioValidationError("unsupported_audio", f"mime type {mime_type} not allowed")
    size = path.stat().st_size if path.exists() else 0
    if size == 0:
        raise AudioValidationError("empty_file")
    if size > settings.max_upload_bytes:
        raise AudioValidationError("file_too_large")
    with path.open("rb") as fh:
        head = fh.read(16)
    if sniff_format(head) is None:
        raise AudioValidationError("malformed_audio", "unrecognized audio container")
    try:
        info = ffmpeg_service.probe(path)
    except ffmpeg_service.FFmpegError as exc:
        raise AudioValidationError(exc.code if exc.code != "malformed_audio" else "malformed_audio", exc.message) from exc
    if info.duration_seconds <= 0:
        # Some WebM recordings have no duration in the header; ffmpeg still decodes them.
        info.duration_seconds = 0.0
    if info.duration_seconds and info.duration_seconds < settings.min_duration_seconds:
        raise AudioValidationError("audio_too_short", f"duration {info.duration_seconds:.2f}s")
    if info.duration_seconds > settings.max_duration_seconds:
        raise AudioValidationError("audio_too_long", f"duration {info.duration_seconds:.0f}s")
    return AudioMetadata(
        original_filename=sanitize_filename(filename),
        mime_type=mime_type.split(";")[0].strip().lower() or "application/octet-stream",
        size_bytes=size,
        duration_seconds=info.duration_seconds,
        sha256=sha256_of(path),
        codec_name=info.codec_name,
        sample_rate=info.sample_rate,
        channels=info.channels,
    )


def make_processing_copy(original: Path, target: Path) -> float:
    """Create the 16 kHz mono PCM WAV copy and return its exact duration."""
    ffmpeg_service.to_processing_wav(original, target)
    return ffmpeg_service.wav_duration_seconds(target)
