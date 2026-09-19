"""NVIDIA NIM — the DEVELOPMENT provider, and only ever development.

The hosted catalogue at integrate.api.nvidia.com is OpenAI-compatible, which makes it a
convenient benchmark while local models are chosen. It sends text off this machine, so:

* the class REFUSES TO CONSTRUCT unless the environment is development - the guard is in
  __init__, not in a caller, so no future code path can reach it in production;
* only synthetic or anonymised Arabic may be sent to it (an operational rule, stated here
  because the code cannot enforce what the operator types);
* the API key is read from a file the operator provisions and never appears in a log line,
  an API response, the settings table, or an audit entry.
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.services.llm.base import ProviderInfo, clean_model_text

log = logging.getLogger(__name__)


class ProductionCloudRefused(Exception):
    """Production is local-only. This is an invariant, not a configuration mistake."""


def read_api_key() -> str | None:
    """The key, from the operator-provisioned secret file. Missing is a normal state."""
    settings = get_settings()
    path = settings.nvidia_api_key_file
    try:
        if path and path.is_file():
            key = path.read_text(encoding="utf-8").strip()
            return key or None
    except OSError as exc:  # unreadable secret: report the failure, never the contents
        log.warning("nvidia api key file unreadable: %s", exc.__class__.__name__)
    return None


class NvidiaNimProvider:
    """OpenAI-compatible chat completion against the NVIDIA build catalogue."""

    def __init__(self, *, api_key: str | None = None, client: httpx.Client | None = None):
        settings = get_settings()
        if settings.environment.strip().lower() != "development":
            # The one line that makes "no cloud in production" structural.
            raise ProductionCloudRefused("nvidia_nim_is_development_only")
        self._settings = settings
        self._api_key = api_key if api_key is not None else read_api_key()
        self._client = client
        self.model = settings.development_llm_model
        self.base_url = settings.nvidia_base_url.rstrip("/")

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            provider="nvidia_nim",
            runtime="nim",
            execution="cloud",
            model=self.model,
            resolved_profile="DEVELOPMENT_CLOUD",
            fallback_reason=None if self.available() else "nvidia_api_key_missing",
        )

    def available(self) -> bool:
        return bool(self._api_key)

    def complete(
        self, *, system: str, user: str, temperature: float, max_tokens: int, timeout: float
    ) -> str:
        if not self._api_key:
            raise RuntimeError("nvidia_api_key_missing")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "top_p": 0.95,
            "max_tokens": max_tokens,
            "stream": False,
            # No reasoning trace: an official record keeps the answer, not the deliberation.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}

        client = self._client or httpx.Client(timeout=timeout)
        close = self._client is None
        try:
            res = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            res.raise_for_status()
            body = res.json()
        finally:
            if close:
                client.close()

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("llm_unexpected_response") from exc
        if isinstance(content, list):  # some deployments return content parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return clean_model_text(content)
