"""Phase 8: the Fusha service, the NVIDIA development provider, and the invariants.

No network here - the provider is driven through a stubbed httpx client, so these tests run
identically on a machine with no key, no internet and no GPU. What they pin down:

* production can NEVER reach a cloud provider (checked at construction, not at the caller);
* a missing key degrades to "unavailable with a reason", never an error the operator has to
  work around - the محضر is still fully editable by hand;
* the request we send matches the spec: the strict system prompt, low temperature, no
  reasoning trace, bounded output;
* the key never appears in a log line or in what we store;
* provenance ties a suggestion to the exact text it was made for.

The Arabic faithfulness examples (§74) are asserted against MODEL-SHAPED responses: they
prove the pipeline preserves what the model returned - character for character - which is
the part this codebase controls. Whether a given model is faithful is a benchmarking
question, and Phase 15 measures it against the real one.
"""

import logging

import httpx
import pytest

from app.config import get_settings
from app.services.llm.base import (
    FUSHA_SYSTEM_PROMPT,
    FormalizationUnavailable,
    clean_model_text,
    source_hash,
)
from app.services.llm.nvidia import NvidiaNimProvider, ProductionCloudRefused
from app.services.llm.service import ArabicFormalizationService, resolve_provider


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _reply(text: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    return handler


def _provider(text: str, *, key: str = "nvapi-test-key-value") -> NvidiaNimProvider:
    return NvidiaNimProvider(api_key=key, client=_client(_reply(text)))


def _service(text: str) -> ArabicFormalizationService:
    return ArabicFormalizationService(provider=_provider(text))


@pytest.fixture
def production(monkeypatch):
    """Flip the running settings object to production for one test."""
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "production")
    return settings


# --------------------------------------------------------------- the hard invariant


def test_the_cloud_provider_refuses_to_exist_in_production(production):
    with pytest.raises(ProductionCloudRefused):
        NvidiaNimProvider(api_key="nvapi-anything")


def test_production_resolves_to_local_only_never_to_nvidia(production):
    """On this build machine no local model is provisioned, so production resolves to
    nothing - and the REASON always comes from the local ladder, never from the cloud one."""
    provider, reason = resolve_provider()
    assert provider is None
    assert reason in {
        "local_runtime_not_configured",
        "local_runtime_unavailable",
        "no_approved_model_provisioned",
        "hardware_below_all_profiles",
    }, f"production must land on the LOCAL path, got {reason!r}"
    assert "nvidia" not in (reason or "")


def test_production_never_serves_a_suggestion_from_the_cloud(production):
    service = ArabicFormalizationService()
    assert service.available() is False
    with pytest.raises(FormalizationUnavailable):
        service.formalize("ما بعرف مين أخد السيارة")
    assert service.info().provider in ("none", "local")


# --------------------------------------------------------------- unavailability is normal


def test_a_missing_key_is_unavailable_not_an_error(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "nvidia_api_key_file", tmp_path / "does-not-exist")
    provider, reason = resolve_provider()
    assert provider is None and reason == "nvidia_api_key_missing"

    service = ArabicFormalizationService()
    assert service.available() is False
    info = service.info()
    assert info.provider == "none" and info.fallback_reason == "nvidia_api_key_missing"
    assert info.model is None


def test_the_key_is_read_from_the_operator_provisioned_file(monkeypatch, tmp_path):
    key_file = tmp_path / "nvidia_api_key"
    key_file.write_text("nvapi-from-secret-file\n", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "nvidia_api_key_file", key_file)
    provider, reason = resolve_provider()
    assert reason is None and provider is not None and provider.available()


def test_disabling_fusha_in_settings_turns_it_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "report_fusha_enabled", False)
    service = _service("أي نص")
    assert service.available() is False
    assert service.info().fallback_reason == "disabled_by_settings"
    with pytest.raises(FormalizationUnavailable) as exc:
        service.formalize("نص")
    assert exc.value.reason == "disabled_by_settings"


def test_a_model_failure_degrades_gracefully():
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "overloaded"})

    provider = NvidiaNimProvider(api_key="nvapi-x", client=_client(boom))
    service = ArabicFormalizationService(provider=provider)
    with pytest.raises(FormalizationUnavailable) as exc:
        service.formalize("ما بعرف")
    assert exc.value.reason == "llm_request_failed"


def test_an_empty_model_answer_is_refused_not_stored():
    with pytest.raises(FormalizationUnavailable) as exc:
        _service("   ").formalize("ما بعرف")
    assert exc.value.reason == "llm_empty_response"


def test_input_limits_are_enforced(monkeypatch):
    monkeypatch.setattr(get_settings(), "report_fusha_max_input_chars", 20)
    with pytest.raises(FormalizationUnavailable) as exc:
        _service("x").formalize("ن" * 50)
    assert exc.value.reason == "text_too_long"
    with pytest.raises(FormalizationUnavailable) as exc:
        _service("x").formalize("   ")
    assert exc.value.reason == "empty_text"


# --------------------------------------------------------------- the request we send


def test_the_request_matches_the_specified_contract():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "نص"}}]})

    provider = NvidiaNimProvider(api_key="nvapi-secret", client=_client(handler))
    ArabicFormalizationService(provider=provider).formalize("ما بعرف")

    assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert captured["auth"] == "Bearer nvapi-secret"
    body = captured["body"]
    assert body["model"] == get_settings().development_llm_model
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][0]["content"] == FUSHA_SYSTEM_PROMPT
    assert body["messages"][1]["content"] == "ما بعرف"
    assert body["temperature"] == 0.1, "low variance for an official document"
    assert body["stream"] is False
    # No reasoning trace requested, so none can be stored.
    assert body["chat_template_kwargs"]["enable_thinking"] is False
    assert body["max_tokens"] <= 2048


def test_the_system_prompt_forbids_what_it_must():
    for rule in ("النفي", "التواريخ", "الأرقام", "تلخّص", "تختلق", "تغيّر قائل الكلام"):
        assert rule in FUSHA_SYSTEM_PROMPT


# --------------------------------------------------------------- the key never leaks


def test_the_key_never_reaches_logs_or_provenance(caplog):
    secret = "nvapi-super-secret-value"
    with caplog.at_level(logging.DEBUG):
        result = ArabicFormalizationService(
            provider=_provider("لا أعرف", key=secret)
        ).formalize("ما بعرف")
    assert secret not in caplog.text
    assert secret not in str(result.provenance())
    assert secret not in result.suggested_text


def test_provenance_records_what_is_needed_and_nothing_else():
    result = _service("لا أعرف من أخذ السيارة").formalize("ما بعرف مين أخد السيارة")
    prov = result.provenance()
    assert set(prov) == {
        "provider",
        "runtime",
        "model",
        "temperature",
        "source_text_hash",
        "generated_at",
    }
    assert prov["provider"] == "nvidia_nim" and prov["runtime"] == "nim"
    assert prov["model"] == get_settings().development_llm_model
    # The hash binds the suggestion to the exact text it was made for: edit the source and
    # the stored suggestion is visibly stale.
    assert prov["source_text_hash"] == source_hash("ما بعرف مين أخد السيارة")
    assert prov["source_text_hash"] != source_hash("ما بعرف مين أخد الدراجة")
    assert "prompt" not in prov and "reasoning" not in prov


# --------------------------------------------------------------- response handling


def test_a_reasoning_block_is_never_kept():
    raw = "<think>the speaker denies it, so keep the negation</think>\nلا أعرف من أخذ السيارة."
    assert clean_model_text(raw) == "لا أعرف من أخذ السيارة."
    result = _service(raw).formalize("ما بعرف مين أخد السيارة")
    assert "<think>" not in result.suggested_text
    assert result.suggested_text == "لا أعرف من أخذ السيارة."


def test_wrapping_quotes_and_fences_are_removed():
    assert clean_model_text('"لا أعرف"') == "لا أعرف"
    assert clean_model_text("```\nلا أعرف\n```") == "لا أعرف"


def test_content_returned_as_parts_is_joined():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": [{"text": "لا "}, {"text": "أعرف"}]}}]},
        )

    provider = NvidiaNimProvider(api_key="nvapi-x", client=_client(handler))
    assert ArabicFormalizationService(provider=provider).formalize("ما بعرف").suggested_text == "لا أعرف"


def test_a_malformed_response_is_a_clean_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    provider = NvidiaNimProvider(api_key="nvapi-x", client=_client(handler))
    with pytest.raises(FormalizationUnavailable) as exc:
        ArabicFormalizationService(provider=provider).formalize("ما بعرف")
    assert exc.value.reason == "llm_request_failed"


# --------------------------------------------------------------- §74 faithfulness


@pytest.mark.parametrize(
    "colloquial,formal",
    [
        # Negation survives.
        ("ما رحت لعندو", "لم أذهب إليه"),
        # Uncertainty survives.
        ("يمكن كان الساعة سبعة", "ربما كانت الساعة السابعة"),
        # حسن is not حسين.
        ("شفت حسن، مش حسين", "شاهدت حسن، وليس حسين"),
        # The amount is exact.
        ("معي ٣٥٠ دولار", "بحوزتي ٣٥٠ دولاراً"),
        # Attribution is not strengthened into an accusation.
        ("ما قلت إنو هو أخدها", "لم أقل إنه أخذها"),
        # The spec's worked example.
        (
            "ما بعرف مين أخد السيارة، بس شفت أحمد حدها.",
            "لا أعرف من أخذ السيارة، لكنني شاهدت أحمد بالقرب منها.",
        ),
    ],
)
def test_the_pipeline_returns_the_model_text_verbatim(colloquial, formal):
    """Whatever the model says is what the investigator compares against - unaltered."""
    result = _service(formal).formalize(colloquial)
    assert result.suggested_text == formal
    assert result.source_text_hash == source_hash(colloquial)


def test_the_source_text_is_never_modified_by_asking():
    original = "ما بعرف مين أخد السيارة"
    text = original
    _service("لا أعرف من أخذ السيارة").formalize(text)
    assert text == original, "formalize must not mutate its input"
