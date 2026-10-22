"""Voice extraction uses complete diarization, and optional failures remain visible."""

import json
import time
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from app.ai.speaker_id_service import SpeakerIdentificationError
from app.ai.types import ModelInfo, SpeakerTurn, SpeechRegion, TranscriptSegment
from app.jobs.pipeline import JobPipeline
from app.jobs.store import JobRecord
from tests.conftest import build_runtime


class FakeSpeakerId:
    embedding_dim = 256
    device = 'cpu'

    def __init__(self, fail=None):
        self.fail = fail
        self.clips = []

    def load(self):
        if self.fail == 'load':
            raise SpeakerIdentificationError('speaker_id_model_missing', 'missing model')

    def embed(self, audio, sample_rate):
        self.clips.append(audio.copy())
        if self.fail == 'embed':
            raise SpeakerIdentificationError('speaker_id_failed', 'inference failed')
        return np.ones(self.embedding_dim, dtype=np.float32) / 16

    def info(self):
        return ModelInfo('speaker_id', 'nemo_speakernet', 'fake/speaker', '1', 'READY')


def fixture_pipeline(settings, tmp_path, *, fail=None):
    runtime = build_runtime(settings)
    runtime.speaker_id = FakeSpeakerId(fail)
    store = SimpleNamespace(is_cancel_requested=lambda _: False,
                            get_token=lambda _: None, save=lambda _: None)
    pipeline = JobPipeline(settings, store, runtime, None, lambda: {})
    wav = tmp_path / 'original.wav'
    audio = np.full(9 * 16000, .1, dtype=np.float32)
    # A distinct signal marks exactly the audio that must never enter the print.
    audio[int(1.28 * 16000):int(2.88 * 16000)] = .8
    sf.write(wav, audio, 16000, subtype='FLOAT')
    job = JobRecord('job', 'session', 'recording', 'user', original_path=str(wav))
    return pipeline, job, wav, runtime.speaker_id


def finalize(pipeline, job, segments, voice, diagnostics):
    audio_meta = SimpleNamespace(original_filename='original.wav', mime_type='audio/wav',
                                 size_bytes=1, sha256='a' * 64)
    pipeline._stage_finalize(job, audio_meta, 9, [], segments, {}, time.time(), voice, diagnostics)
    with open(job.result_path, encoding='utf-8') as result:
        return json.load(result)


@pytest.mark.parametrize('include_competitor_transcript', [True, False])
def test_pipeline_recovers_clean_voice_even_when_competitor_has_no_text(settings, tmp_path, include_competitor_transcript):
    pipeline, job, wav, model = fixture_pipeline(settings, tmp_path)
    turns = [SpeakerTurn('SPEAKER_00', 1.1, 8.56, True), SpeakerTurn('SPEAKER_01', 1.28, 2.88, True)]
    segments = [TranscriptSegment('SPEAKER_00', 1.1, 8.56, 'speech', True)]
    if include_competitor_transcript:
        segments.append(TranscriptSegment('SPEAKER_01', 1.28, 2.88, 'speech', True))
    voice, diagnostics = pipeline._stage_identify_speakers(job, wav, segments, turns, [SpeechRegion(0, 9)])
    assert set(voice['speakers']) == {'SPEAKER_00'}
    assert voice['speakers']['SPEAKER_00']['seconds'] == pytest.approx(5.86)
    assert len(model.clips) == 1
    assert np.max(model.clips[0]) < .2  # no competing voice in the recovered audio
    result = finalize(pipeline, job, segments, voice, diagnostics)
    assert result['voice_identification']['model_revision'] == '1'
    assert set(result['voice_identification']) == {'provider', 'model', 'model_revision', 'embedding_dim', 'device', 'speakers'}
    if include_competitor_transcript:
        skipped = result['processing_metadata']['speaker_identification']['speakers']['SPEAKER_01']
        assert skipped == {'status': 'skipped', 'clean_seconds': 0, 'reason': 'speaker_id_no_clean_speech'}
        assert any('SPEAKER_01' in warning and 'Record speakers separately' in warning for warning in result['warnings'])
    assert all('speaker_id_' not in warning for warning in result['warnings'])


@pytest.mark.parametrize(('failure', 'reason'), [('load', 'speaker_id_model_missing'), ('embed', 'speaker_id_failed')])
def test_optional_voice_failure_preserves_transcript_and_records_reason(settings, tmp_path, failure, reason):
    pipeline, job, wav, _ = fixture_pipeline(settings, tmp_path, fail=failure)
    segments = [TranscriptSegment('SPEAKER_00', 3, 8, 'preserved text')]
    voice, diagnostics = pipeline._stage_identify_speakers(
        job, wav, segments, [SpeakerTurn('SPEAKER_00', 3, 8)], [SpeechRegion(0, 9)])
    result = finalize(pipeline, job, segments, voice, diagnostics)
    assert result['voice_identification'] is None
    assert result['segments'][0]['text'] == 'preserved text'
    assert any('voice model' in warning for warning in result['warnings'])
    details = result['processing_metadata']['speaker_identification']
    assert details['embeddings'] == 0
    assert (details['reason'] if failure == 'load' else details['speakers']['SPEAKER_00']['reason']) == reason
    assert all('speaker_id_' not in warning for warning in result['warnings'])


def test_short_speech_is_reported_without_calling_encoder(settings, tmp_path):
    pipeline, job, wav, model = fixture_pipeline(settings, tmp_path)
    segments = [TranscriptSegment('SPEAKER_00', 3, 4.5, 'short speech')]
    voice, diagnostics = pipeline._stage_identify_speakers(
        job, wav, segments, [SpeakerTurn('SPEAKER_00', 3, 4.5)], [SpeechRegion(0, 9)])
    result = finalize(pipeline, job, segments, voice, diagnostics)
    assert not model.clips
    assert diagnostics['speakers']['SPEAKER_00']['clean_seconds'] == 1.5
    assert diagnostics['speakers']['SPEAKER_00']['reason'] == 'speaker_id_audio_too_short'
    assert any('1.50s' in warning and '2.00s' in warning and 'longer sample' in warning for warning in result['warnings'])
    assert all('speaker_id_' not in warning for warning in result['warnings'])


def test_disabled_voice_identification_is_explicit(settings, tmp_path):
    settings.speaker_id_enabled = False
    pipeline, job, wav, model = fixture_pipeline(settings, tmp_path)
    segments = [TranscriptSegment('SPEAKER_00', 3, 8, 'speech')]
    voice, diagnostics = pipeline._stage_identify_speakers(
        job, wav, segments, [SpeakerTurn('SPEAKER_00', 3, 8)], [SpeechRegion(0, 9)])
    result = finalize(pipeline, job, segments, voice, diagnostics)
    assert not model.clips
    assert result['processing_metadata']['speaker_identification']['status'] == 'disabled'
    assert diagnostics['reason'] == 'speaker_id_disabled'
    assert any('Voice identification is disabled' in warning for warning in result['warnings'])
    assert all('speaker_id_' not in warning for warning in result['warnings'])
