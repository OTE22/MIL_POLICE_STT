"""Hardware detection: CUDA availability, GPU name, selected inference device."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

log = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    cuda_available: bool
    gpu_name: str | None
    torch_version: str | None
    cuda_version: str | None


@lru_cache
def detect_device() -> DeviceInfo:
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        log.warning("torch not importable: %s", exc)
        return DeviceInfo(False, None, None, None)
    cuda = bool(torch.cuda.is_available())
    name = None
    if cuda:
        try:
            name = torch.cuda.get_device_name(0)
        except Exception:  # noqa: BLE001
            name = "CUDA"
    return DeviceInfo(cuda, name, getattr(torch, "__version__", None), getattr(torch.version, "cuda", None) if cuda else None)


def resolve_device(requested: str) -> str:
    requested = (requested or "auto").lower()
    info = detect_device()
    if requested == "cuda":
        if not info.cuda_available:
            log.warning("CUDA requested but not available; falling back to CPU")
            return "cpu"
        return "cuda"
    if requested == "cpu":
        return "cpu"
    return "cuda" if info.cuda_available else "cpu"


def resolve_dtype(requested: str, device: str):  # noqa: ANN201
    import torch

    requested = (requested or "auto").lower()
    if device == "cpu":
        return torch.float32
    if requested == "float16":
        return torch.float16
    if requested == "bfloat16":
        return torch.bfloat16
    if requested == "float32":
        return torch.float32
    return torch.float16
