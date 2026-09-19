"""GET /api/llm/capabilities — what Fusha assistance this machine can offer, if any.

Safe fields only: which runtime resolved, on what execution target, with which model, and
WHY it fell back when it did. No key, no paths, no prompt, no secrets. "Unavailable" is a
normal answer that the composer renders as a note, not an error.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.models import User
from app.services.llm.hardware import get_hardware
from app.services.llm.service import ArabicFormalizationService

router = APIRouter(tags=["llm"])


class LLMCapabilitiesOut(BaseModel):
    available: bool
    provider: str
    runtime: str
    execution: str
    resolved_profile: str | None
    model: str | None
    gpu_count: int | None
    vram_gb: float | None
    system_ram_gb: float | None
    # An expected downgrade ("the medium model is not installed"), not a fault.
    fallback_reason: str | None


@router.get("/llm/capabilities", response_model=LLMCapabilitiesOut)
def llm_capabilities(_: User = Depends(get_current_user)) -> LLMCapabilitiesOut:
    service = ArabicFormalizationService()
    info = service.info()
    hardware = get_hardware()
    return LLMCapabilitiesOut(
        available=service.available(),
        provider=info.provider,
        runtime=info.runtime,
        execution=info.execution,
        resolved_profile=info.resolved_profile,
        model=info.model,
        gpu_count=info.gpu_count if info.gpu_count is not None else hardware.gpu_count,
        vram_gb=info.vram_gb if info.vram_gb is not None else (hardware.max_vram_gb or None),
        system_ram_gb=info.system_ram_gb if info.system_ram_gb is not None else (hardware.system_ram_gb or None),
        fallback_reason=info.fallback_reason,
    )
