"""The production path: local runtimes only, on whatever hardware is actually here.

`resolve_local_provider` is the whole production decision - detect, choose an approved and
installed profile, and hand back a provider bound to it. Every failure mode returns
(None, reason) so the capabilities endpoint can explain itself and the محضر stays editable
by hand. There is no rung on this ladder that leaves the machine.

Ollama is the first runtime because it serves both CPU and GPU from one API; the report code
never learns which, and swapping in vLLM later means writing another provider here and
nothing else.
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.services.llm.base import LLMProvider, ProviderInfo, clean_model_text
from app.services.llm.hardware import Hardware, get_hardware
from app.services.llm.profiles import Resolution, resolve_profile

log = logging.getLogger(__name__)


class OllamaProvider:
    """Chat completion against a locally provisioned model. CPU or GPU is Ollama's business."""

    def __init__(self, resolution: Resolution, hardware: Hardware, *, client: httpx.Client | None = None):
        self._resolution = resolution
        self._hardware = hardware
        self._client = client
        self.model = resolution.resolved_tag or ""
        self.base_url = get_settings().ollama_base_url.rstrip("/")

    def info(self) -> ProviderInfo:
        profile = self._resolution.profile
        return ProviderInfo(
            provider="local",
            runtime="ollama",
            execution=(profile.execution if profile else "none"),
            model=self.model or None,
            resolved_profile=(profile.name if profile else None),
            fallback_reason=self._resolution.fallback_reason,
            gpu_count=self._hardware.gpu_count,
            vram_gb=self._hardware.max_vram_gb or None,
            system_ram_gb=self._hardware.system_ram_gb or None,
        )

    def available(self) -> bool:
        return bool(self.model and self._resolution.profile)

    def complete(
        self, *, system: str, user: str, temperature: float, max_tokens: int, timeout: float
    ) -> str:
        if not self.available():
            raise RuntimeError("local_model_unavailable")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            # `think: false` keeps reasoning models from emitting a trace we would only
            # have to discard - an official record keeps the answer, not the deliberation.
            "think": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        client = self._client or httpx.Client(timeout=timeout)
        close = self._client is None
        try:
            res = client.post(f"{self.base_url}/api/chat", json=payload)
            res.raise_for_status()
            body = res.json()
        finally:
            if close:
                client.close()

        content = (body.get("message") or {}).get("content")
        if not isinstance(content, str):
            raise RuntimeError("llm_unexpected_response")
        return clean_model_text(content)


def resolve_local_provider() -> tuple[LLMProvider | None, str | None]:
    """(provider, fallback_reason) for the strongest APPROVED and INSTALLED local profile."""
    hardware = get_hardware()
    resolution = resolve_profile(hardware)
    if resolution.profile is None or not resolution.resolved_tag:
        log.info(
            "no local llm: reason=%s requested=%s ram=%.1fGB gpus=%d",
            resolution.fallback_reason, resolution.requested_profile,
            hardware.system_ram_gb, hardware.gpu_count,
        )
        return None, resolution.fallback_reason or "local_runtime_not_configured"

    provider = OllamaProvider(resolution, hardware)
    log.info(
        "local llm resolved profile=%s model=%s execution=%s%s",
        resolution.profile.name, resolution.resolved_tag, resolution.profile.execution,
        f" (fallback: {resolution.fallback_reason})" if resolution.fallback_reason else "",
    )
    return provider, resolution.fallback_reason
