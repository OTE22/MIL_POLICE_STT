"""Approved local profiles, and choosing the strongest one this machine can actually serve.

Two rules the resolver never breaks:

* **Approved, not merely fitting.** A profile is a vetted pairing of hardware class and
  model. Free VRAM is not permission to load an untested model into an official workflow.
* **Installed, not installable.** The chosen model must already be provisioned. Production
  never pulls anything - no `ollama pull`, no Hugging Face, no network fetch at startup.

When the preferred profile is not available the resolver steps DOWN through the local
profiles and records why. Every fallback is local; there is no cloud rung on this ladder.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import get_settings
from app.services.llm.hardware import Hardware

log = logging.getLogger(__name__)

CPU_BASELINE = "CPU_BASELINE"
GPU_SMALL = "GPU_SMALL"
GPU_MEDIUM = "GPU_MEDIUM"
GPU_LARGE = "GPU_LARGE"


@dataclass(frozen=True)
class Profile:
    """One approved hardware/model pairing.

    `configured_model` is what the administrator approved; `resolved_tag` (filled by the
    resolver) is what the runtime manifest actually calls it. Keeping them apart is what
    stops a working machine reporting "model missing" because the tag reads
    `qwen3:8b-q4_K_M` rather than the assumed `qwen3:8b`.
    """

    name: str
    configured_model: str
    required_quantization: str
    min_vram_gb: float
    min_ram_gb: float
    execution: str  # "gpu" | "cpu"
    priority: int  # higher = stronger


@dataclass(frozen=True)
class Resolution:
    profile: Profile | None
    resolved_tag: str | None
    requested_profile: str | None
    fallback_reason: str | None


def approved_profiles() -> list[Profile]:
    """Built from Settings, so the organisation can retune after benchmarking."""
    s = get_settings()
    return [
        Profile(GPU_LARGE, s.llm_gpu_large_model, "Q4-class", s.llm_gpu_large_min_vram_gb, 0.0, "gpu", 40),
        Profile(GPU_MEDIUM, s.llm_gpu_medium_model, "Q4-class", s.llm_gpu_medium_min_vram_gb, 0.0, "gpu", 30),
        Profile(GPU_SMALL, s.llm_gpu_small_model, "Q4-class", s.llm_gpu_small_min_vram_gb, 0.0, "gpu", 20),
        Profile(CPU_BASELINE, s.llm_cpu_model, "Q4-class", 0.0, s.llm_cpu_min_ram_gb, "cpu", 10),
    ]


def _hardware_supports(profile: Profile, hardware: Hardware) -> bool:
    if profile.execution == "gpu":
        if not hardware.cuda_available or hardware.gpu_count == 0:
            return False
        return hardware.max_vram_gb >= profile.min_vram_gb
    return hardware.system_ram_gb >= profile.min_ram_gb


def resolve_profile(hardware: Hardware) -> Resolution:
    """The strongest APPROVED profile that this hardware supports and that is INSTALLED."""
    ordered = sorted(approved_profiles(), key=lambda p: p.priority, reverse=True)
    supported = [p for p in ordered if _hardware_supports(p, hardware)]

    if not supported:
        return Resolution(None, None, None, "hardware_below_all_profiles")

    requested = supported[0].name  # what the hardware alone would justify

    if not hardware.runtime_reachable:
        return Resolution(None, None, requested, "local_runtime_unavailable")

    for profile in supported:
        tag = hardware.has_model(profile.configured_model)
        if tag:
            reason = None if profile.name == requested else f"{requested.lower()}_model_not_provisioned"
            return Resolution(profile, tag, requested, reason)

    return Resolution(None, None, requested, "no_approved_model_provisioned")
