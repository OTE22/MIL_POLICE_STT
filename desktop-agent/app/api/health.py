"""Health, capabilities and model status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__
from app.audio.ffmpeg_service import ffmpeg_available, ffmpeg_version
from app.audio.preprocessing import ALLOWED_EXTENSIONS

router = APIRouter(tags=["status"])


def _capabilities(request: Request) -> dict:
    settings = request.app.state.settings
    manager = request.app.state.manager
    runtime = request.app.state.runtime
    status = runtime.status()
    return {
        "agent_id": manager.agent_id,
        "agent_version": __version__,
        "device_name": settings.device_name,
        "processing_device": status["processing_device"],
        "cuda_available": status["cuda_available"],
        "gpu_name": status["gpu_name"],
        "torch_version": status["torch_version"],
        "cuda_version": status["cuda_version"],
        "ffmpeg_available": ffmpeg_available(),
        "ffmpeg_version": ffmpeg_version(),
        "stt": status["stt"],
        "diarization": status["diarization"],
        "vad": status["vad"],
        "speaker_id": status["speaker_id"],
        "max_speakers": status["max_speakers"],
        "supported_formats": sorted(ALLOWED_EXTENSIONS),
        "max_upload_bytes": settings.max_upload_bytes,
        "ready": status["ready"] and ffmpeg_available(),
        "loadable": status["loadable"],
        "loading": status["loading"],
        "busy": manager.busy,
        "current_job_id": manager.current_job_id,
        "central_sync_enabled": settings.central_sync_enabled,
        "central_url": settings.central_url,
        "public_key_installed": settings.public_key_path.exists(),
    }


@router.get("/health")
def health(request: Request) -> dict:
    manager = request.app.state.manager
    settings = request.app.state.settings
    return {
        "status": "ok",
        "agent_id": manager.agent_id,
        "agent_version": __version__,
        "device_name": settings.device_name,
        "uptime_seconds": round(manager.uptime_seconds, 1),
    }


@router.get("/capabilities")
def capabilities(request: Request) -> dict:
    return _capabilities(request)


@router.get("/model-status")
def model_status(request: Request) -> dict:
    return _capabilities(request)


@router.post("/models/load")
def load_models(request: Request) -> dict:
    """Start loading the models in the background (lazy initialization trigger)."""
    runtime = request.app.state.runtime
    accepted = runtime.load_in_background()
    return {"accepted": accepted, "status": runtime.status()}
