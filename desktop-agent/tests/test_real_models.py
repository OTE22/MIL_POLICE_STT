"""Real-model acceptance tests (spec §79-80). They run only when the models are provisioned.

    AGENT_MODEL_DIR=/models python -m pytest tests/test_real_models.py -v -s
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.segment_service import SegmentSettings, plan_segments  # noqa: E402
from app.audio.ffmpeg_service import ffmpeg_available  # noqa: E402
from app.audio.preprocessing import make_processing_copy  # noqa: E402
from app.config import get_settings  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
CONVERSATION = FIXTURES / "conversation_ar_2spk.wav"
SINGLE = FIXTURES / "single_speaker_ar.wav"

settings = get_settings()
needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")
needs_diar = pytest.mark.skipif(not settings.diarization_nemo_path.exists(), reason="Sortformer model not provisioned")
needs_stt = pytest.mark.skipif(not (settings.stt_model_dir / "config.json").exists(), reason="Cohere model not provisioned (gated; needs HF_TOKEN)")


def collapse(labels):
    out = []
    for x in labels:
        if not out or out[-1] != x:
            out.append(x)
    return out


@pytest.fixture(scope="module")
def processing_wav():
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "processing.wav"
        duration = make_processing_copy(CONVERSATION, wav)
        yield wav, duration


@needs_ffmpeg
def test_vad_finds_speech_regions(processing_wav):
    from app.ai.vad_service import VadService

    wav, duration = processing_wav
    vad = VadService(settings)
    regions = vad.detect(wav, duration)
    assert regions, "no speech detected"
    total = sum(r.end_seconds - r.start_seconds for r in regions)
    assert 20 < total < duration  # speech but not the whole file (there are pauses)
    assert regions[0].start_seconds >= 0.5  # leading silence is excluded
    print(f"\nVAD: {len(regions)} regions, {total:.1f}s speech of {duration:.1f}s")


@needs_ffmpeg
@needs_diar
def test_real_diarization_speaker_a_b_a(processing_wav):
    """Speaker A talks, B talks, A talks again -> SPEAKER_00, SPEAKER_01, SPEAKER_00 (spec §80)."""
    from app.ai.diarization_service import build_diarization_service
    from app.ai.vad_service import VadService

    wav, duration = processing_wav
    diar = build_diarization_service(settings)
    diar.load()
    assert diar.info().state == "READY"
    turns = diar.diarize(wav)
    assert turns, "no speaker turns"
    labels = sorted({t.speaker_label for t in turns})
    print("\nraw turns:")
    for t in turns:
        print(f"  {t.start_seconds:7.2f} -> {t.end_seconds:7.2f}  {t.speaker_label}{' overlap' if t.is_overlap else ''}")
    assert labels == ["SPEAKER_00", "SPEAKER_01"], f"expected exactly two speakers, got {labels}"
    speech = VadService(settings).detect(wav, duration)
    plans = plan_segments(turns, speech, duration, SegmentSettings(), vad_enabled=True)
    sequence = collapse([p.speaker_label for p in plans])
    print("sequence:", " -> ".join(sequence))
    assert sequence[:3] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"], sequence
    assert sequence == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00", "SPEAKER_01", "SPEAKER_00"], sequence
    # Turn boundaries roughly match the scripted timeline (A≈0.9-10s, B≈11-22s, ...)
    first_b = next(p for p in plans if p.speaker_label == "SPEAKER_01")
    assert 9.0 < first_b.start_seconds < 14.0, first_b


@needs_ffmpeg
@needs_stt
def test_real_arabic_transcription():
    import soundfile as sf

    from app.ai.transcription_service import build_transcription_service

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "p.wav"
        make_processing_copy(SINGLE, wav)
        audio, sr = sf.read(str(wav), dtype="float32")
    stt = build_transcription_service(settings)
    stt.load()
    assert stt.info().state == "READY"
    result = stt.transcribe(audio, sr)
    print("\nTEXT:", result.text)
    assert result.text.strip()
    assert any("؀" <= ch <= "ۿ" for ch in result.text), "expected Arabic script"
    for word in ("المنزل", "العشاء"):
        assert word in result.text, f"expected '{word}' in transcription"


@needs_ffmpeg
@needs_diar
@needs_stt
def test_speaker_turn_transcription_combined(processing_wav):
    """Diarization + STT per segment -> who + when + what."""
    import soundfile as sf

    from app.ai.diarization_service import build_diarization_service
    from app.ai.transcription_service import build_transcription_service
    from app.ai.vad_service import VadService

    wav, duration = processing_wav
    turns = build_diarization_service(settings).diarize(wav)
    speech = VadService(settings).detect(wav, duration)
    plans = plan_segments(turns, speech, duration, SegmentSettings(), vad_enabled=True)
    stt = build_transcription_service(settings)
    audio, sr = sf.read(str(wav), dtype="float32")
    texts = []
    for p in plans:
        clip = audio[int(p.window_start * sr) : int(p.window_end * sr)]
        texts.append((p.speaker_label, stt.transcribe(clip, sr).text))
        print(f"\n{p.speaker_label} {p.start_seconds:.1f}-{p.end_seconds:.1f}: {texts[-1][1]}")
    joined = " ".join(t for _, t in texts)
    assert "المنزل" in joined
    assert any(label == "SPEAKER_01" and "المنزل" in text for label, text in texts), "interviewee answer attributed to SPEAKER_01"
