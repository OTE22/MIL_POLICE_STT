"""Thin wrapper around ffmpeg / ffprobe (must be installed on the workstation)."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

TARGET_SAMPLE_RATE = 16000


class FFmpegError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ProbeResult:
    duration_seconds: float
    codec_name: str | None
    sample_rate: int | None
    channels: int | None
    format_name: str | None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def ffmpeg_version() -> str | None:
    if not shutil.which("ffmpeg"):
        return None
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10, check=False)
        return out.stdout.splitlines()[0] if out.stdout else None
    except Exception:  # noqa: BLE001
        return None


def probe(path: Path) -> ProbeResult:
    if not shutil.which("ffprobe"):
        raise FFmpegError("ffmpeg_missing", "ffprobe is not installed")
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-select_streams",
        "a:0",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError("probe_timeout", "ffprobe timed out") from exc
    if out.returncode != 0:
        raise FFmpegError("malformed_audio", (out.stderr or "ffprobe failed").strip()[:500])
    try:
        data = json.loads(out.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FFmpegError("malformed_audio", "unreadable ffprobe output") from exc
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    if not streams:
        raise FFmpegError("malformed_audio", "no audio stream found")
    stream = streams[0]
    duration = fmt.get("duration") or stream.get("duration")
    try:
        duration_f = float(duration) if duration is not None else 0.0
    except (TypeError, ValueError):
        duration_f = 0.0
    return ProbeResult(
        duration_seconds=duration_f,
        codec_name=stream.get("codec_name"),
        sample_rate=int(stream["sample_rate"]) if stream.get("sample_rate") else None,
        channels=int(stream["channels"]) if stream.get("channels") else None,
        format_name=fmt.get("format_name"),
    )


def to_processing_wav(source: Path, target: Path) -> None:
    """Create the normalized processing copy: WAV, 16 kHz, mono, 16-bit PCM.

    The original file is never modified.
    """
    if not shutil.which("ffmpeg"):
        raise FFmpegError("ffmpeg_missing", "ffmpeg is not installed")
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-v",
        "error",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(TARGET_SAMPLE_RATE),
        "-sample_fmt",
        "s16",
        "-f",
        "wav",
        str(target),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError("preprocess_timeout", "ffmpeg timed out") from exc
    if out.returncode != 0 or not target.exists() or target.stat().st_size < 100:
        raise FFmpegError("malformed_audio", (out.stderr or "ffmpeg failed").strip()[:500])


def wav_duration_seconds(path: Path) -> float:
    import soundfile as sf

    info = sf.info(str(path))
    return float(info.frames) / float(info.samplerate)
