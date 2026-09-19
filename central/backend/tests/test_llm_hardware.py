"""Phases 9-10: what runs where, decided from detected hardware — never from hope.

Every case is mocked, so the matrix runs identically on the CPU laptop that builds the image
and on a 24 GB workstation. The rules being pinned:

  hardware supports X, X installed          -> X
  hardware supports X, X missing            -> the strongest INSTALLED profile below it
  runtime down / nothing installed          -> unavailable, with a reason
  production                                -> local or nothing. Never NVIDIA.
"""

import httpx
import pytest

from app.config import get_settings
from app.services.llm.hardware import GPU, Hardware
from app.services.llm.local import OllamaProvider, resolve_local_provider
from app.services.llm.profiles import (
    CPU_BASELINE,
    GPU_LARGE,
    GPU_MEDIUM,
    GPU_SMALL,
    resolve_profile,
)


def hw(*, ram=24.0, vram=0.0, gpus=0, cuda=None, runtime=True, models=()) -> Hardware:
    return Hardware(
        system_ram_gb=ram,
        gpus=tuple(GPU(name=f"NVIDIA Test {i}", vram_gb=vram) for i in range(gpus)),
        cuda_available=(gpus > 0) if cuda is None else cuda,
        runtime_reachable=runtime,
        installed_models=tuple(models),
    )


@pytest.fixture
def models():
    s = get_settings()
    return {
        CPU_BASELINE: s.llm_cpu_model,
        GPU_SMALL: s.llm_gpu_small_model,
        GPU_MEDIUM: s.llm_gpu_medium_model,
        GPU_LARGE: s.llm_gpu_large_model,
    }


# --------------------------------------------------------------- the §72 matrix


def test_no_gpu_with_plenty_of_ram_resolves_to_the_cpu_baseline(models):
    res = resolve_profile(hw(ram=24.0, gpus=0, models=[models[CPU_BASELINE]]))
    assert res.profile.name == CPU_BASELINE
    assert res.profile.execution == "cpu"
    assert res.fallback_reason is None


def test_a_small_gpu_resolves_to_gpu_small_when_that_model_is_installed(models):
    res = resolve_profile(hw(ram=32.0, gpus=1, vram=8.0, models=[models[GPU_SMALL]]))
    assert res.profile.name == GPU_SMALL
    assert res.profile.execution == "gpu"


def test_a_sixteen_gigabyte_gpu_resolves_to_gpu_medium(models):
    res = resolve_profile(hw(ram=64.0, gpus=1, vram=16.0, models=[models[GPU_MEDIUM]]))
    assert res.profile.name == GPU_MEDIUM


def test_a_twenty_four_gigabyte_gpu_resolves_to_gpu_large(models):
    res = resolve_profile(hw(ram=64.0, gpus=1, vram=24.0, models=[models[GPU_LARGE]]))
    assert res.profile.name == GPU_LARGE


def test_a_gpu_without_cuda_falls_back_to_the_cpu_profile(models):
    res = resolve_profile(hw(ram=32.0, gpus=1, vram=24.0, cuda=False, models=[models[CPU_BASELINE]]))
    assert res.profile.name == CPU_BASELINE
    assert res.requested_profile == CPU_BASELINE, "no GPU profile may be requested without CUDA"


def test_a_missing_gpu_model_steps_down_to_the_next_installed_local_profile(models):
    """16 GB of VRAM, but only the CPU model is provisioned - use it, and say why."""
    res = resolve_profile(hw(ram=64.0, gpus=1, vram=16.0, models=[models[CPU_BASELINE]]))
    assert res.profile.name in (GPU_SMALL, CPU_BASELINE)
    assert res.requested_profile == GPU_MEDIUM
    assert res.fallback_reason == "gpu_medium_model_not_provisioned"


def test_a_runtime_that_is_down_is_unavailable_not_a_crash(models):
    res = resolve_profile(hw(ram=64.0, gpus=1, vram=16.0, runtime=False, models=[models[GPU_MEDIUM]]))
    assert res.profile is None
    assert res.fallback_reason == "local_runtime_unavailable"


def test_a_runtime_with_no_approved_model_is_unavailable():
    res = resolve_profile(hw(ram=64.0, gpus=1, vram=16.0, models=["some-unapproved-model:latest"]))
    assert res.profile is None
    assert res.fallback_reason == "no_approved_model_provisioned"


def test_hardware_below_every_profile_is_reported_as_such():
    res = resolve_profile(hw(ram=2.0, gpus=0, models=[]))
    assert res.profile is None
    assert res.fallback_reason == "hardware_below_all_profiles"


def test_multiple_gpus_are_detected_and_bounded_by_the_largest_card():
    hardware = Hardware(
        system_ram_gb=128.0,
        gpus=(GPU("A", 8.0), GPU("B", 24.0)),
        cuda_available=True,
        runtime_reachable=True,
        installed_models=(get_settings().llm_gpu_large_model,),
    )
    assert hardware.gpu_count == 2
    assert hardware.max_vram_gb == 24.0
    # Model choice follows ONE card: no implicit sharding across GPUs.
    assert resolve_profile(hardware).profile.name == GPU_LARGE


# --------------------------------------------------------------- installed-tag matching


def test_the_installed_manifest_decides_the_tag_not_an_assumed_string():
    """`qwen3:8b` approved, `qwen3:8b-q4_K_M` installed - that is a match, not a miss."""
    hardware = hw(ram=32.0, models=["qwen3:8b-q4_K_M"])
    assert hardware.has_model("qwen3:8b") == "qwen3:8b-q4_K_M"
    res = resolve_profile(hardware)
    assert res.profile.name == CPU_BASELINE
    assert res.resolved_tag == "qwen3:8b-q4_K_M", "the runtime's own tag is what gets called"


def test_an_unrelated_model_is_not_mistaken_for_the_approved_one():
    hardware = hw(ram=32.0, models=["llama3:8b", "mistral:7b"])
    assert hardware.has_model("qwen3:8b") is None


# --------------------------------------------------------------- the provider


def test_the_local_provider_calls_the_runtime_with_the_resolved_tag(models):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "لا أعرف من أخذ السيارة."}})

    hardware = hw(ram=32.0, models=["qwen3:8b-q4_K_M"])
    resolution = resolve_profile(hardware)
    provider = OllamaProvider(resolution, hardware, client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert provider.available()
    out = provider.complete(system="s", user="u", temperature=0.1, max_tokens=256, timeout=5)
    assert out == "لا أعرف من أخذ السيارة."
    assert captured["url"].endswith("/api/chat")
    assert captured["body"]["model"] == "qwen3:8b-q4_K_M"
    assert captured["body"]["stream"] is False
    assert captured["body"]["think"] is False, "no reasoning trace in an official record"
    assert captured["body"]["options"]["temperature"] == 0.1

    info = provider.info()
    assert info.provider == "local" and info.runtime == "ollama"
    assert info.execution == "cpu" and info.resolved_profile == CPU_BASELINE
    assert info.system_ram_gb == 32.0


def test_the_provider_reports_gpu_details_when_running_on_one(models):
    hardware = hw(ram=64.0, gpus=1, vram=16.0, models=[models[GPU_MEDIUM]])
    provider = OllamaProvider(resolve_profile(hardware), hardware)
    info = provider.info()
    assert info.execution == "gpu"
    assert info.gpu_count == 1 and info.vram_gb == 16.0


def test_no_local_provider_when_nothing_is_installed(monkeypatch):
    from app.services.llm import local as local_module

    monkeypatch.setattr(local_module, "get_hardware", lambda: hw(ram=32.0, models=[]))
    provider, reason = resolve_local_provider()
    assert provider is None
    assert reason == "no_approved_model_provisioned"


def test_a_resolved_local_provider_is_returned_with_its_fallback_reason(monkeypatch):
    from app.services.llm import local as local_module

    monkeypatch.setattr(
        local_module, "get_hardware", lambda: hw(ram=64.0, gpus=1, vram=16.0, models=[get_settings().llm_cpu_model])
    )
    provider, reason = resolve_local_provider()
    assert provider is not None and provider.available()
    assert reason == "gpu_medium_model_not_provisioned", "an expected downgrade, reported"


# --------------------------------------------------------------- production invariant


def test_production_with_a_local_model_uses_it_and_still_never_touches_the_cloud(monkeypatch):
    from app.services.llm import local as local_module
    from app.services.llm.service import resolve_provider

    monkeypatch.setattr(get_settings(), "environment", "production")
    monkeypatch.setattr(
        local_module, "get_hardware", lambda: hw(ram=32.0, models=[get_settings().llm_cpu_model])
    )
    provider, _ = resolve_provider()
    assert provider is not None
    assert provider.info().provider == "local"
    assert provider.info().execution in ("cpu", "gpu")


def test_settings_retune_the_profiles_without_code_changes(monkeypatch):
    """Benchmarking changes which model a profile means - through Settings, not a deploy."""
    monkeypatch.setattr(get_settings(), "llm_cpu_model", "custom-arabic:8b")
    hardware = hw(ram=32.0, models=["custom-arabic:8b"])
    res = resolve_profile(hardware)
    assert res.profile.name == CPU_BASELINE
    assert res.resolved_tag == "custom-arabic:8b"


def test_raising_the_vram_bar_makes_a_card_ineligible(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_gpu_small_min_vram_gb", 40.0)
    monkeypatch.setattr(get_settings(), "llm_gpu_medium_min_vram_gb", 48.0)
    monkeypatch.setattr(get_settings(), "llm_gpu_large_min_vram_gb", 64.0)
    res = resolve_profile(hw(ram=32.0, gpus=1, vram=16.0, models=[get_settings().llm_cpu_model]))
    assert res.profile.name == CPU_BASELINE, "a 16 GB card cannot meet a 40 GB bar"
