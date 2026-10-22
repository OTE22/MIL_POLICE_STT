"""Read-only real-model check; run in the agent image with source/models mounted read-only.

Prints durations and embedding dimensions only. Never uploads results or changes records.
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from app.ai.diarization_service import build_diarization_service
from app.ai.speaker_id_service import (
    build_speaker_id_service, clean_diarized_speaker_spans,
    clean_speaker_spans, collect_speaker_audio,
)
from app.ai.vad_service import VadService
from app.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--previous-result", type=Path)
    parser.add_argument("--expect-recovered", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        settings = Settings(data_dir=Path(folder), model_dir=Path("/models"),
                            speaker_id_device="cpu", diarization_device="cpu", _env_file=None)
        wav = Path(folder) / "check.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(args.audio), "-ac", "1",
                        "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)
        audio, rate = sf.read(wav, dtype="float32")
        speech = VadService(settings).detect(wav, len(audio) / rate)
        turns = build_diarization_service(settings).diarize(wav)
        spans = clean_diarized_speaker_spans(turns, speech)
        model = build_speaker_id_service(settings)
        report = {"turns": len(turns), "samples": [], "old_usable_seconds": None}
        if args.previous_result:
            previous = json.loads(args.previous_result.read_text(encoding="utf-8"))
            old = clean_speaker_spans([SimpleNamespace(**s) for s in previous["segments"]])
            report["old_usable_seconds"] = round(sum(b-a for windows in old.values() for a,b in windows), 3)
        for label in sorted({t.speaker_label for t in turns}):
            clip = collect_speaker_audio(audio, rate, spans.get(label, []), settings.speaker_id_max_seconds)
            seconds = len(clip) / rate
            sample = {"label": label, "clean_seconds": round(seconds, 3), "embedding_dim": 0}
            if seconds >= settings.speaker_id_min_seconds:
                vector = model.embed(clip, rate)
                assert len(vector) == model.embedding_dim
                assert np.isfinite(vector).all() and abs(float(np.linalg.norm(vector))-1) < 1e-5
                sample["embedding_dim"] = len(vector)
            report["samples"].append(sample)
        if args.expect_recovered:
            assert report["old_usable_seconds"] == 0, report
            assert any(s["embedding_dim"] for s in report["samples"]), report
        print("VOICE_OVERLAP_CHECK=" + json.dumps(report))


if __name__ == "__main__":
    main()
