"""Dictation processing never invokes diarization or speaker identification."""
import json
import uuid
from datetime import datetime, timezone
import pytest
from app.jobs.store import JobRecord, JobStore
from app.jobs.pipeline import JobPipeline
from tests.conftest import build_runtime, FakeCentral, FakeVad, FakeTranscription, write_wav


@pytest.mark.parametrize("silent", [False, True])
def test_dictation_pipeline_keeps_audio_and_skips_speaker_models(settings, tmp_path, monkeypatch, silent):
    settings.data_dir.mkdir(parents=True)
    store = JobStore(settings.db_path)
    runtime = build_runtime(settings, vad=FakeVad(regions=[] if silent else [(0, 2)]))
    central = FakeCentral()
    pipeline = JobPipeline(settings, store, runtime, central, lambda: {"agent_id": "test"})
    def prohibited(*args, **kwargs):
        pytest.fail("dictation invoked a speaker model")
    monkeypatch.setattr(pipeline, "_stage_diarize", prohibited)
    monkeypatch.setattr(pipeline, "_stage_identify_speakers", prohibited)
    original = write_wav(tmp_path / "dictation.wav", 2, silence=silent)
    job = JobRecord(job_id=str(uuid.uuid4()), session_id=str(uuid.uuid4()), recording_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()), purpose="REPORT_DICTATION", original_filename="dictation.wav", original_path=str(original),
        audio_metadata={"mime_type": "audio/wav"})
    store.save(job)
    store.save_token(job.job_id, "test-token", datetime(2999, 1, 1, tzinfo=timezone.utc))
    pipeline.run(job)
    assert original.exists()
    persisted = store.get(job.job_id)
    assert persisted.purpose == "REPORT_DICTATION"
    if silent:
        assert persisted.state == "FAILED" and persisted.error_code == "no_speech_detected"
    else:
        assert persisted.state == "COMPLETED", persisted.error_message
        result = json.loads(open(persisted.result_path).read())
        assert result["processing_metadata"]["purpose"] == "REPORT_DICTATION"
        assert result["diarization_provider"] == "not_applicable"
        assert result["processing_metadata"]["speaker_identification"]["enabled"] is False
        assert result["segments"] and not result.get("voice_identification")
    store.close()
