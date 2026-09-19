"""ArabicFormalizationService — the only door the report code uses to reach a model.

Provider resolution lives here, and it is the single place where the environment decides
what may run:

    development  ->  NVIDIA NIM (hosted), when the operator has provisioned a key
    production   ->  LOCAL ONLY (Ollama / approved profile). Never a cloud fallback.

"Unavailable" is a first-class, tested state: no key, no local model, no runtime, model
error - all of them return a reason and leave the محضر workflow fully usable by hand.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.services.llm.base import (
    FUSHA_SYSTEM_PROMPT,
    FormalizationResult,
    FormalizationUnavailable,
    LLMProvider,
    ProviderInfo,
    source_hash,
    utcnow,
)
from app.services.llm.nvidia import NvidiaNimProvider, ProductionCloudRefused

log = logging.getLogger(__name__)

NO_PROVIDER = ProviderInfo(
    provider="none", runtime="none", execution="none", model=None, fallback_reason="not_configured"
)


def _is_production() -> bool:
    return get_settings().environment.strip().lower() == "production"


def resolve_provider() -> tuple[LLMProvider | None, str | None]:
    """Pick the runtime for this machine. Returns (provider, fallback_reason).

    Order is deliberately short: production never even constructs the cloud provider, and
    development never silently reaches for local hardware it was not asked to use.
    """
    settings = get_settings()
    mode = (settings.llm_runtime_mode or "auto").strip().lower()

    if mode == "off":
        return None, "disabled_by_settings"

    if _is_production() or mode == "local":
        # Phase 9/10 fill this in with hardware detection + Ollama. Until an approved local
        # model is provisioned, the honest answer is "unavailable" - NOT a cloud call.
        from app.services.llm.local import resolve_local_provider

        return resolve_local_provider()

    try:
        provider = NvidiaNimProvider()
    except ProductionCloudRefused:
        # Belt and braces: even if the mode said otherwise, the environment wins.
        return None, "cloud_refused_in_production"
    if not provider.available():
        return None, "nvidia_api_key_missing"
    return provider, None


class ArabicFormalizationService:
    """Formalize ONE Q&A block at a time. Suggestions only - a human always decides."""

    def __init__(self, provider: LLMProvider | None = None, fallback_reason: str | None = None):
        if provider is None and fallback_reason is None:
            provider, fallback_reason = resolve_provider()
        self._provider = provider
        self._fallback_reason = fallback_reason

    # ---- capability reporting (safe to expose; never includes a key) --------

    def available(self) -> bool:
        settings = get_settings()
        return bool(settings.report_fusha_enabled and self._provider and self._provider.available())

    def info(self) -> ProviderInfo:
        if self._provider is None:
            return ProviderInfo(
                provider="none",
                runtime="none",
                execution="none",
                model=None,
                fallback_reason=self._fallback_reason or "not_configured",
            )
        info = self._provider.info()
        if not get_settings().report_fusha_enabled:
            return ProviderInfo(**{**info.__dict__, "fallback_reason": "disabled_by_settings"})
        return info

    # ---- the one operation -------------------------------------------------

    def formalize(self, text: str, *, context: str | None = None) -> FormalizationResult:
        """Suggest a Fusha rewording of one question or answer.

        Per block on purpose: small inputs keep latency, memory and context small, make the
        human comparison honest, and mean one failure never costs the whole محضر.
        """
        settings = get_settings()
        if not settings.report_fusha_enabled:
            raise FormalizationUnavailable("disabled_by_settings")
        if self._provider is None or not self._provider.available():
            raise FormalizationUnavailable(self._fallback_reason or "llm_unavailable")

        source = (text or "").strip()
        if not source:
            raise FormalizationUnavailable("empty_text")
        if len(source) > settings.report_fusha_max_input_chars:
            raise FormalizationUnavailable("text_too_long")

        user_prompt = source if not context else f"{context}\n\n{source}"
        info = self._provider.info()
        try:
            suggestion = self._provider.complete(
                system=FUSHA_SYSTEM_PROMPT,
                user=user_prompt,
                temperature=settings.report_fusha_temperature,
                # Formalizing cannot legitimately grow the text much; the cap also bounds a
                # runaway model. Generous enough for a long answer.
                max_tokens=min(2048, max(256, len(source) * 3)),
                timeout=float(settings.report_fusha_timeout_seconds),
            )
        except FormalizationUnavailable:
            raise
        except Exception as exc:
            # The reason is logged by class, never the text and never the key.
            log.warning("fusha suggestion failed provider=%s error=%s", info.provider, exc.__class__.__name__)
            raise FormalizationUnavailable("llm_request_failed") from exc

        suggestion = (suggestion or "").strip()
        if not suggestion:
            raise FormalizationUnavailable("llm_empty_response")

        log.info(
            "fusha suggestion provider=%s runtime=%s model=%s chars=%d -> %d",
            info.provider, info.runtime, info.model, len(source), len(suggestion),
        )
        return FormalizationResult(
            suggested_text=suggestion,
            provider=info.provider,
            runtime=info.runtime,
            model=info.model or "",
            temperature=settings.report_fusha_temperature,
            source_text_hash=source_hash(source),
            generated_at=utcnow(),
        )
