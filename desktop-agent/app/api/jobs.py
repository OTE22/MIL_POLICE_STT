"""Job endpoints: create (token + audio), query, cancel."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from app.audio.preprocessing import ALLOWED_EXTENSIONS, ALLOWED_MIME, extension_of, sniff_format
from app.security.token_validation import TokenValidationError

router = APIRouter(prefix="/jobs", tags=["jobs"])
log = logging.getLogger(__name__)


def _error(status_code: int, code: str, message: str | None = None) -> HTTPException:
    return HTTPException(status_code, detail={"code": code, "message": message or code})


async def _stream_to_disk(upload: UploadFile, target: Path, limit: int) -> int:
    size = 0
    head = b""
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        with tmp.open("wb") as fh:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                if not head:
                    head = chunk[:16]
                size += len(chunk)
                if size > limit:
                    raise _error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file_too_large")
                fh.write(chunk)
        if size == 0:
            raise _error(status.HTTP_400_BAD_REQUEST, "empty_file")
        if sniff_format(head) is None:
            raise _error(status.HTTP_400_BAD_REQUEST, "unsupported_audio", "unrecognized audio container")
        tmp.replace(target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return size


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: Request,
    processing_token: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    settings = request.app.state.settings
    manager = request.app.state.manager
    validator = request.app.state.token_validator

    filename = file.filename or "recording.bin"
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if extension_of(filename) not in ALLOWED_EXTENSIONS:
        raise _error(status.HTTP_400_BAD_REQUEST, "unsupported_audio", f"extension not allowed: {filename}")
    if mime not in ALLOWED_MIME:
        raise _error(status.HTTP_400_BAD_REQUEST, "unsupported_audio", f"mime type not allowed: {mime}")
    try:
        claims = validator.validate(processing_token)
    except TokenValidationError as exc:
        code = {"token_expired": "token_expired", "token_replay": "token_replay"}.get(exc.code, exc.code)
        raise _error(status.HTTP_401_UNAUTHORIZED, code, exc.message) from exc

    runtime_status = request.app.state.runtime.status()
    if not runtime_status["loadable"] and not runtime_status["ready"]:
        stt = runtime_status["stt"]
        dia = runtime_status["diarization"]
        code = "stt_model_missing" if stt["state"] in ("NOT_PROVISIONED", "ERROR") else "diarization_model_missing"
        raise _error(status.HTTP_503_SERVICE_UNAVAILABLE, code, stt.get("error") or dia.get("error"))

    if manager.get(claims.job_id) is not None:
        raise _error(status.HTTP_409_CONFLICT, "job_exists")
    job = manager.create_job(claims, filename, mime or "application/octet-stream")
    manager.mark_receiving(job)
    try:
        size = await _stream_to_disk(file, Path(job.original_path), settings.max_upload_bytes)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "upload_failed", "message": str(exc.detail)}
        manager.discard(job, detail["code"], detail.get("message") or detail["code"])
        raise
    job.audio_metadata["size_bytes"] = size
    manager.enqueue(job)
    request.app.state.runtime.load_in_background()
    return job.public()


@router.get("")
def list_jobs(request: Request) -> list[dict]:
    return [j.public() for j in request.app.state.manager.list()]


@router.get("/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    try:
        uuid.UUID(job_id)
    except ValueError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, "job_not_found") from exc
    job = request.app.state.manager.get(job_id)
    if job is None:
        raise _error(status.HTTP_404_NOT_FOUND, "job_not_found")
    return job.public()


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict:
    try:
        uuid.UUID(job_id)
    except ValueError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, "job_not_found") from exc
    job = request.app.state.manager.cancel(job_id)
    if job is None:
        raise _error(status.HTTP_404_NOT_FOUND, "job_not_found")
    return job.public()


@router.post("/sync/run")
def run_sync_now(request: Request) -> dict:
    """Force an immediate retry of pending synchronizations."""
    manager = request.app.state.manager
    manager.sync.wake()
    return {"pending": [j.public() for j in request.app.state.store.pending_sync()]}
