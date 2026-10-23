"""Supported model selection, strict restore, and reproducible provisioning."""

from __future__ import annotations

import hashlib
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.ai.diarization_service import DiarizationError, build_diarization_service
from app.config import (
    DIARIZATION_MODELS,
    NEMOTRON_DIARIZATION_MODEL,
    NEMOTRON_DIARIZATION_REVISION,
    NEMOTRON_DIARIZATION_SHA256,
    NVIDIA_DIARIZATION_MODEL,
    NVIDIA_DIARIZATION_REVISION,
    Settings,
)


@pytest.fixture(autouse=True)
def isolated_diarization_environment(monkeypatch):
    for name in ("MODEL", "MODEL_REVISION", "SPEAKER_CACHE_LEN"):
        monkeypatch.delenv(f"AGENT_DIARIZATION_{name}", raising=False)


@pytest.mark.parametrize("model,revision,capacity,cache", [
    (NVIDIA_DIARIZATION_MODEL, NVIDIA_DIARIZATION_REVISION, 4, 188),
    (NEMOTRON_DIARIZATION_MODEL, NEMOTRON_DIARIZATION_REVISION, 8, 264),
])
def test_model_selection_resolves_capacity_revision_and_cache(model, revision, capacity, cache, tmp_path):
    settings = Settings(diarization_model=model, model_dir=tmp_path, _env_file=None)
    assert settings.diarization_model_revision == revision
    assert settings.diarization_speaker_cache_len == cache
    assert settings.diarization_max_speakers == capacity
    service = build_diarization_service(settings)
    assert service.max_speakers == capacity
    assert service.info().extra["max_speakers"] == capacity
    assert settings.diarization_nemo_path.name == model.split("/")[-1] + ".nemo"


def test_default_model_remains_sortformer():
    settings = Settings(_env_file=None)
    assert settings.diarization_model == NVIDIA_DIARIZATION_MODEL
    assert settings.diarization_model_revision == NVIDIA_DIARIZATION_REVISION
    assert settings.diarization_speaker_cache_len == 188


def test_compose_empty_overrides_use_selected_model_defaults(monkeypatch):
    monkeypatch.setenv("AGENT_DIARIZATION_MODEL", NEMOTRON_DIARIZATION_MODEL)
    monkeypatch.setenv("AGENT_DIARIZATION_MODEL_REVISION", "")
    monkeypatch.setenv("AGENT_DIARIZATION_SPEAKER_CACHE_LEN", "")
    settings = Settings(_env_file=None)
    assert settings.diarization_model_revision == NEMOTRON_DIARIZATION_REVISION
    assert settings.diarization_speaker_cache_len == 264


def test_explicit_immutable_revision_and_cache_overrides_are_retained():
    settings = Settings(
        diarization_model=NEMOTRON_DIARIZATION_MODEL,
        diarization_model_revision="1" * 40, diarization_speaker_cache_len=300, _env_file=None,
    )
    assert settings.diarization_model_revision == "1" * 40
    assert settings.diarization_speaker_cache_len == 300


@pytest.mark.parametrize("override", [
    {"diarization_model": "unreviewed/unknown"},
    {"diarization_model_revision": "main"},
    {"diarization_speaker_cache_len": 0},
])
def test_unsupported_or_unpinned_configuration_is_rejected(override):
    with pytest.raises(ValidationError):
        Settings(**override, _env_file=None)


@pytest.mark.parametrize("model,capacity", [
    (NVIDIA_DIARIZATION_MODEL, 4), (NEMOTRON_DIARIZATION_MODEL, 8),
])
def test_runtime_reports_selected_capacity(model, capacity, tmp_path):
    from app.ai.runtime import ModelRuntime

    runtime = ModelRuntime(Settings(diarization_model=model, model_dir=tmp_path, _env_file=None))
    assert runtime.max_speakers == capacity


def fake_checkpoint(monkeypatch, capacity, *, model_validator=True):
    model = SimpleNamespace(
        cfg=SimpleNamespace(max_num_of_spks=capacity), eval=Mock(),
        sortformer_modules=SimpleNamespace(_check_streaming_parameters=Mock()),
    )
    if model_validator:
        model._check_streaming_parameters = Mock()
    restore = Mock(return_value=model)
    for name in ("nemo", "nemo.collections", "nemo.collections.asr", "nemo.collections.asr.models"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    sys.modules["nemo.collections.asr.models"].SortformerEncLabelModel = SimpleNamespace(restore_from=restore)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(device=lambda value: value))
    monkeypatch.setattr("app.ai.diarization_service.resolve_device", lambda _: "cpu")
    return model, restore


def provisioned_service(tmp_path, model=NVIDIA_DIARIZATION_MODEL):
    settings = Settings(diarization_model=model, model_dir=tmp_path, _env_file=None)
    settings.diarization_model_dir.mkdir(parents=True)
    settings.diarization_nemo_path.write_bytes(b"mock checkpoint")
    return settings, build_diarization_service(settings)


@pytest.mark.parametrize("model_name,capacity,cache", [
    (NVIDIA_DIARIZATION_MODEL, 4, 188), (NEMOTRON_DIARIZATION_MODEL, 8, 264),
])
def test_strict_restore_uses_model_level_validation_and_correct_cache(monkeypatch, tmp_path, model_name, capacity, cache):
    settings, service = provisioned_service(tmp_path, model_name)
    model, restore = fake_checkpoint(monkeypatch, capacity)
    service.load()
    service.load()
    restore.assert_called_once_with(restore_path=str(settings.diarization_nemo_path), map_location="cpu", strict=True)
    assert model.sortformer_modules.spkcache_len == cache
    assert model.sortformer_modules.chunk_len == 340
    model._check_streaming_parameters.assert_called_once_with()
    model.sortformer_modules._check_streaming_parameters.assert_not_called()
    assert service.info().state == "READY"


def test_module_validation_fallback_for_older_supported_runtime(monkeypatch, tmp_path):
    _, service = provisioned_service(tmp_path)
    model, _ = fake_checkpoint(monkeypatch, 4, model_validator=False)
    service.load()
    model.sortformer_modules._check_streaming_parameters.assert_called_once_with()


def test_strict_weight_incompatibility_fails_without_publishing_model(monkeypatch, tmp_path):
    _, service = provisioned_service(tmp_path, NEMOTRON_DIARIZATION_MODEL)
    _, restore = fake_checkpoint(monkeypatch, 8)
    restore.side_effect = RuntimeError("Unexpected checkpoint keys")
    with pytest.raises(DiarizationError, match="Unexpected checkpoint keys"):
        service.load()
    assert service._model is None
    assert service.info().state == "ERROR"
    assert restore.call_args.kwargs["strict"] is True


def test_checkpoint_capacity_mismatch_is_rejected(monkeypatch, tmp_path):
    _, service = provisioned_service(tmp_path, NEMOTRON_DIARIZATION_MODEL)
    fake_checkpoint(monkeypatch, 4)
    with pytest.raises(DiarizationError, match="selected model requires 8"):
        service.load()
    assert service._model is None


def test_manifest_revision_mismatch_is_rejected_before_restore(monkeypatch, tmp_path):
    settings, service = provisioned_service(tmp_path)
    _, restore = fake_checkpoint(monkeypatch, 4)
    (settings.diarization_model_dir / "MANIFEST.json").write_text(json.dumps({
        "model": NVIDIA_DIARIZATION_MODEL, "revision": "0" * 40, "files": {},
    }))
    with pytest.raises(DiarizationError, match="does not match configuration"):
        service.load()
    restore.assert_not_called()


def test_provision_cli_selects_candidate_pin_and_digest(monkeypatch, tmp_path):
    from scripts import provision_models

    monkeypatch.setattr(provision_models, "get_settings", lambda: Settings(_env_file=None))
    download = Mock()
    monkeypatch.setattr(provision_models, "provision_hf", download)
    monkeypatch.setattr(sys, "argv", [
        "provision_models.py", "--only", "diarization", "--model-dir", str(tmp_path),
        "--diarization-model", NEMOTRON_DIARIZATION_MODEL,
    ])
    assert provision_models.main() == 0
    assert download.call_args.args[:3] == (
        NEMOTRON_DIARIZATION_MODEL, NEMOTRON_DIARIZATION_REVISION,
        tmp_path / "Nemotron-3-Diarization",
    )
    assert download.call_args.kwargs["checkpoint_sha256"] == NEMOTRON_DIARIZATION_SHA256


@pytest.mark.parametrize("matching_digest", [True, False])
def test_provision_writes_manifest_only_after_checkpoint_digest_matches(monkeypatch, tmp_path, matching_digest):
    from scripts import provision_models

    payload = b"downloaded checkpoint"
    downloader = ModuleType("huggingface_hub")

    def snapshot_download(**kwargs):
        (tmp_path / "Nemotron-3-Diarization.nemo").write_bytes(payload)
        assert kwargs["revision"] == NEMOTRON_DIARIZATION_REVISION

    downloader.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", downloader)
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text('{"revision":"obsolete"}')
    arguments = dict(
        repo=NEMOTRON_DIARIZATION_MODEL, revision=NEMOTRON_DIARIZATION_REVISION,
        target=tmp_path, allow_patterns=["*.nemo"], token=None,
        checkpoint_sha256=hashlib.sha256(payload).hexdigest() if matching_digest else "0" * 64,
    )
    if matching_digest:
        provision_models.provision_hf(**arguments)
        assert json.loads(manifest.read_text())["revision"] == NEMOTRON_DIARIZATION_REVISION
    else:
        with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
            provision_models.provision_hf(**arguments)
        assert not manifest.exists()
