"""Agent API: health, capabilities, job lifecycle, audio validation, cancellation, failures."""

from __future__ import annotations

import shutil
import uuid

import pytest

from app.audio.ffmpeg_service import ffmpeg_available
from tests.conftest import FakeDiarization, FakeTranscription, make_token, read_result, wait_for_state, write_wav

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")


def test_health_and_capabilities(agent_app):
    c = agent_app["client"]
    res = c.get("/health")
    assert res.status_code == 200 and res.json()["status"] == "ok"
    caps = c.get("/capabilities").json()
    assert caps["stt"]["state"] == "READY" and caps["diarization"]["state"] == "READY"
    assert caps["max_speakers"] == 4
    assert "wav" in caps["supported_formats"]
    assert c.get("/model-status").json()["agent_id"] == caps["agent_id"]


def test_job_requires_valid_token(agent_app, tmp_path):
    c = agent_app["client"]
    wav = write_wav(tmp_path / "a.wav", 2)
    with wav.open("rb") as fh:
        res = c.post("/jobs", data={"processing_token": "bad"}, files={"file": ("a.wav", fh, "audio/wav")})
    assert res.status_code == 401 and res.json()["detail"]["code"] == "token_invalid"


def test_job_rejects_expired_token(agent_app, tmp_path):
    c = agent_app["client"]
    token, _ = make_token(agent_app["keypair"]["private"], accept_seconds=-900)
    wav = write_wav(tmp_path / "a.wav", 2)
    with wav.open("rb") as fh:
        res = c.post("/jobs", data={"processing_token": token}, files={"file": ("a.wav", fh, "audio/wav")})
    assert res.status_code == 401 and res.json()["detail"]["code"] == "token_expired"


def test_job_rejects_unsupported_extension(agent_app, tmp_path):
    c = agent_app["client"]
    token, _ = make_token(agent_app["keypair"]["private"])
    res = c.post("/jobs", data={"processing_token": token}, files={"file": ("a.exe", b"MZ....", "audio/wav")})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "unsupported_audio"


def test_job_rejects_fake_wav(agent_app):
    c = agent_app["client"]
    token, _ = make_token(agent_app["keypair"]["private"])
    res = c.post("/jobs", data={"processing_token": token}, files={"file": ("a.wav", b"this is not audio at all", "audio/wav")})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "unsupported_audio"


def test_job_rejects_empty_file(agent_app):
    c = agent_app["client"]
    token, _ = make_token(agent_app["keypair"]["private"])
    res = c.post("/jobs", data={"processing_token": token}, files={"file": ("a.wav", b"", "audio/wav")})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "empty_file"


def test_replayed_token_rejected(agent_app, tmp_path):
    c = agent_app["client"]
    token, _ = make_token(agent_app["keypair"]["private"])
    wav = write_wav(tmp_path / "a.wav", 2)
    with wav.open("rb") as fh:
        first = c.post("/jobs", data={"processing_token": token}, files={"file": ("a.wav", fh, "audio/wav")})
    assert first.status_code == 202
    with wav.open("rb") as fh:
        second = c.post("/jobs", data={"processing_token": token}, files={"file": ("a.wav", fh, "audio/wav")})
    assert second.status_code == 401 and second.json()["detail"]["code"] == "token_replay"


@needs_ffmpeg
def test_full_job_lifecycle_with_states_and_sync(agent_app, tmp_path):
    c, store, central = agent_app["client"], agent_app["store"], agent_app["central"]
    token, claims = make_token(agent_app["keypair"]["private"])
    wav = write_wav(tmp_path / "interview.wav", 3.0)
    with wav.open("rb") as fh:
        res = c.post("/jobs", data={"processing_token": token}, files={"file": ("interview.wav", fh, "audio/wav")})
    assert res.status_code == 202
    body = res.json()
    assert body["job_id"] == claims["job_id"] and body["state"] in ("RECEIVING_AUDIO", "PREPROCESSING", "CREATED")

    job = wait_for_state(store, claims["job_id"], {"COMPLETED", "FAILED"})
    assert job.state == "COMPLETED", job.error_message
    assert job.speaker_count == 2 and job.segment_count == 3

    # Structured result: who + when + what + overlap metadata
    result = read_result(store, job.job_id)
    assert [s["speaker_label"] for s in result["segments"]] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]
    assert result["segments"][0]["text"] == "أين كنت مساء أمس؟"
    assert result["segments"][0]["start_seconds"] == 0.0 and result["segments"][0]["end_seconds"] == 1.0
    assert all("is_overlap" in s for s in result["segments"])
    assert result["stt_model"] == "fake/stt-ar" and result["diarization_model"] == "fake/diarizer"
    assert result["audio"]["sha256"] and result["audio"]["duration_seconds"] == 3.0

    # State reports reached the central server in order
    reported = [s for j, s in central.states if j == job.job_id]
    for expected in ("CREATED", "RECEIVING_AUDIO", "PREPROCESSING", "DIARIZING", "TRANSCRIBING", "FINALIZING"):
        assert expected in reported
    assert reported.index("DIARIZING") < reported.index("TRANSCRIBING")

    # Synchronization: result + original audio uploaded
    agent_app["manager"].sync.wake()
    import time

    for _ in range(100):
        if store.get(job.job_id).sync_state == "SYNCED":
            break
        time.sleep(0.05)
    job = store.get(job.job_id)
    assert job.sync_state == "SYNCED" and job.result_synced and job.audio_synced
    assert job.job_id in central.results and job.job_id in central.audio
    assert central.audio[job.job_id]["filename"] == "interview.wav"
    assert store.get_token(job.job_id) is None  # token discarded after successful sync

    # The API exposes the job without local paths
    api_job = c.get(f"/jobs/{job.job_id}").json()
    assert api_job["state"] == "COMPLETED" and api_job["sync_state"] == "SYNCED"
    assert "original_path" not in api_job
    assert c.get("/jobs").json()[0]["job_id"] == job.job_id


@needs_ffmpeg
def test_overlap_metadata_preserved(agent_app, tmp_path):
    runtime, store, c = agent_app["runtime"], agent_app["store"], agent_app["client"]
    runtime.diarization = FakeDiarization(turns=[("SPEAKER_00", 0.0, 2.0, True), ("SPEAKER_01", 1.5, 3.0, True)])
    token, claims = make_token(agent_app["keypair"]["private"])
    wav = write_wav(tmp_path / "o.wav", 3.0)
    with wav.open("rb") as fh:
        assert c.post("/jobs", data={"processing_token": token}, files={"file": ("o.wav", fh, "audio/wav")}).status_code == 202
    job = wait_for_state(store, claims["job_id"], {"COMPLETED", "FAILED"})
    assert job.state == "COMPLETED"
    result = read_result(store, job.job_id)
    assert len(result["segments"]) == 2 and all(s["is_overlap"] for s in result["segments"])
    assert result["processing_metadata"]["overlap_turns"] == 2


@needs_ffmpeg
def test_diarization_failure_is_reported_not_hidden(agent_app, tmp_path):
    runtime, store, central, c = agent_app["runtime"], agent_app["store"], agent_app["central"], agent_app["client"]
    runtime.diarization = FakeDiarization(fail="load")
    token, claims = make_token(agent_app["keypair"]["private"])
    wav = write_wav(tmp_path / "d.wav", 2.0)
    with wav.open("rb") as fh:
        c.post("/jobs", data={"processing_token": token}, files={"file": ("d.wav", fh, "audio/wav")})
    job = wait_for_state(store, claims["job_id"], {"COMPLETED", "FAILED"})
    assert job.state == "FAILED" and job.error_code == "diarization_model_missing" and job.failure_stage == "DIARIZING"
    assert (job.job_id, "FAILED") in central.states
    assert job.job_id not in central.results  # no fallback, nothing synced


@needs_ffmpeg
def test_stt_failure_is_reported(agent_app, tmp_path):
    runtime, store, c = agent_app["runtime"], agent_app["store"], agent_app["client"]
    runtime.transcription = FakeTranscription(fail="infer")
    token, claims = make_token(agent_app["keypair"]["private"])
    wav = write_wav(tmp_path / "s.wav", 2.0)
    with wav.open("rb") as fh:
        c.post("/jobs", data={"processing_token": token}, files={"file": ("s.wav", fh, "audio/wav")})
    job = wait_for_state(store, claims["job_id"], {"COMPLETED", "FAILED"})
    assert job.state == "FAILED" and job.error_code == "transcription_failed" and job.failure_stage == "TRANSCRIBING"


@needs_ffmpeg
def test_cancel_job(agent_app, tmp_path):
    runtime, store, c = agent_app["runtime"], agent_app["store"], agent_app["client"]

    class SlowDiarization(FakeDiarization):
        def diarize(self, path):
            import time

            time.sleep(1.5)
            return super().diarize(path)

    runtime.diarization = SlowDiarization()
    token, claims = make_token(agent_app["keypair"]["private"])
    wav = write_wav(tmp_path / "c.wav", 2.0)
    with wav.open("rb") as fh:
        c.post("/jobs", data={"processing_token": token}, files={"file": ("c.wav", fh, "audio/wav")})
    wait_for_state(store, claims["job_id"], {"DIARIZING", "PREPROCESSING"})
    res = c.post(f"/jobs/{claims['job_id']}/cancel")
    assert res.status_code == 200
    job = wait_for_state(store, claims["job_id"], {"CANCELLED", "COMPLETED", "FAILED"})
    assert job.state == "CANCELLED"


def test_unknown_job_404(agent_app):
    c = agent_app["client"]
    assert c.get(f"/jobs/{uuid.uuid4()}").status_code == 404
    assert c.get("/jobs/not-a-uuid").status_code == 404
    assert c.post(f"/jobs/{uuid.uuid4()}/cancel").status_code == 404


@needs_ffmpeg
def test_cleanup_removes_old_synced_job_dirs(agent_app, tmp_path):
    store, manager, c = agent_app["store"], agent_app["manager"], agent_app["client"]
    token, claims = make_token(agent_app["keypair"]["private"])
    wav = write_wav(tmp_path / "k.wav", 2.0)
    with wav.open("rb") as fh:
        c.post("/jobs", data={"processing_token": token}, files={"file": ("k.wav", fh, "audio/wav")})
    job = wait_for_state(store, claims["job_id"], {"COMPLETED", "FAILED"})
    manager.sync.run_once()
    job = store.get(job.job_id)
    job.sync_state = "SYNCED"
    job.completed_at = "2000-01-01T00:00:00+00:00"
    store.save(job)
    assert manager.cleanup_once() == 1
    assert not manager.job_dir(job.job_id).exists()
    shutil.rmtree(tmp_path / "x", ignore_errors=True)
