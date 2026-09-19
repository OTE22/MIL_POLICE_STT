"""What this machine can actually run — detected once at startup, then cached.

Production must not assume CPU-only: the same image may land on a workstation with no GPU,
one with 8 GB of VRAM, or one with 24. This module answers "what is here", and
`profiles.py` decides "what may run on it". Neither downloads anything: detection only ever
observes what an operator has already provisioned.

Detection is cached deliberately. Shelling out to nvidia-smi and polling a runtime on every
suggestion would add latency to each Q&A block for information that changes when the machine
is rebooted, not when a report is written.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

NVIDIA_SMI_TIMEOUT = 5.0
RUNTIME_PROBE_TIMEOUT = 3.0


@dataclass(frozen=True)
class GPU:
    name: str
    vram_gb: float


@dataclass(frozen=True)
class Hardware:
    system_ram_gb: float
    gpus: tuple[GPU, ...] = ()
    cuda_available: bool = False
    runtime_reachable: bool = False
    installed_models: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def gpu_count(self) -> int:
        return len(self.gpus)

    @property
    def max_vram_gb(self) -> float:
        """The largest single GPU. Model choice is bounded by ONE card unless a runtime is
        explicitly configured to shard, which we do not do implicitly."""
        return max((g.vram_gb for g in self.gpus), default=0.0)

    def has_model(self, configured: str) -> str | None:
        """The installed tag matching `configured`, or None.

        Matches the ACTUAL manifest rather than assuming a tag exists: "qwen3:8b" may be
        installed as "qwen3:8b", "qwen3:8b-q4_K_M" or "qwen3:8b-instruct-q4_0" depending on
        how it was pulled, and guessing the literal string is how a working machine reports
        "model missing".

        Exact match first, then the approved tag as a PREFIX of an installed one - never a
        bare family match. "qwen3:8b" must not satisfy an approved "qwen3:14b": they are
        different models, and quietly serving the smaller one would mean an official
        document was written with a model nobody approved for that hardware.
        """
        wanted = (configured or "").strip().lower()
        if not wanted:
            return None
        for tag in self.installed_models:
            if tag.lower() == wanted:
                return tag
        for tag in self.installed_models:
            low = tag.lower()
            # Only a quantization/variant suffix may follow, e.g. qwen3:8b -> qwen3:8b-q4_K_M
            if low.startswith(wanted) and (len(low) == len(wanted) or low[len(wanted)] in "-_."):
                return tag
        return None


def _system_ram_gb() -> float:
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / (1024 * 1024), 1)
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def _detect_gpus() -> tuple[tuple[GPU, ...], bool]:
    """(gpus, cuda_available) via nvidia-smi. Absent driver is a normal, quiet outcome."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return (), False
    try:
        out = subprocess.run(
            [smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=NVIDIA_SMI_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("gpu detection failed: %s", exc.__class__.__name__)
        return (), False
    if out.returncode != 0:
        return (), False

    gpus = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            gpus.append(GPU(name=parts[0], vram_gb=round(float(parts[1]) / 1024, 1)))
        except ValueError:
            continue
    # A driver that answers the query is what "CUDA usable" means operationally here; the
    # runtime still reports its own execution mode.
    return tuple(gpus), bool(gpus)


def _probe_runtime() -> tuple[bool, tuple[str, ...]]:
    """Is a local runtime up, and which models are ALREADY provisioned on it?"""
    settings = get_settings()
    url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
    try:
        res = httpx.get(url, timeout=RUNTIME_PROBE_TIMEOUT)
        res.raise_for_status()
        body = res.json()
    except Exception as exc:
        log.info("local llm runtime not reachable: %s", exc.__class__.__name__)
        return False, ()
    models = tuple(
        str(m.get("name") or m.get("model") or "").strip()
        for m in (body.get("models") or [])
        if (m.get("name") or m.get("model"))
    )
    return True, models


def detect_hardware() -> Hardware:
    """One full pass. Call `get_hardware()` unless you deliberately want a fresh look."""
    gpus, cuda = _detect_gpus()
    reachable, models = _probe_runtime()
    hardware = Hardware(
        system_ram_gb=_system_ram_gb(),
        gpus=gpus,
        cuda_available=cuda,
        runtime_reachable=reachable,
        installed_models=models,
    )
    log.info(
        "hardware: ram=%.1fGB gpus=%d max_vram=%.1fGB cuda=%s runtime=%s models=%d",
        hardware.system_ram_gb, hardware.gpu_count, hardware.max_vram_gb,
        hardware.cuda_available, hardware.runtime_reachable, len(hardware.installed_models),
    )
    return hardware


@lru_cache(maxsize=1)
def get_hardware() -> Hardware:
    """The cached view. Detected on first use (startup warms it) and reused thereafter."""
    return detect_hardware()


def refresh_hardware() -> Hardware:
    """Re-detect - after an operator installs a model or starts the runtime."""
    get_hardware.cache_clear()
    return get_hardware()
