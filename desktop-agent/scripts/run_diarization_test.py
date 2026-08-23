"""Real speaker-diarization acceptance test (spec section 80).

    python scripts/run_diarization_test.py path/to/multi_speaker.wav [--expect SPEAKER_00,SPEAKER_01,SPEAKER_00]

Runs FFmpeg preprocessing + VAD + NVIDIA Sortformer on a real recording and
prints the speaker turns. With --expect, the sequence of speaker changes is
compared against the expected pattern (A, B, A ...).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.diarization_service import build_diarization_service  # noqa: E402
from app.ai.segment_service import SegmentSettings, plan_segments  # noqa: E402
from app.ai.vad_service import VadService  # noqa: E402
from app.audio.preprocessing import make_processing_copy  # noqa: E402
from app.config import get_settings  # noqa: E402


def collapse(labels: list[str]) -> list[str]:
    out: list[str] = []
    for label in labels:
        if not out or out[-1] != label:
            out.append(label)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("--expect", default=None, help="comma separated expected speaker sequence")
    args = parser.parse_args()
    settings = get_settings()
    src = Path(args.audio)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "processing.wav"
        duration = make_processing_copy(src, wav)
        print(f"audio: {src.name}  duration={duration:.2f}s")
        vad = VadService(settings)
        speech = vad.detect(wav, duration)
        print(f"VAD: {len(speech)} speech region(s): " + ", ".join(f"{r.start_seconds:.2f}-{r.end_seconds:.2f}" for r in speech))
        diar = build_diarization_service(settings)
        diar.load()
        turns = diar.diarize(wav)
        print(f"diarization ({diar.provider}, {diar.device}): {len(turns)} turn(s)")
        for t in turns:
            print(f"  {t.start_seconds:8.2f} -> {t.end_seconds:8.2f}  {t.speaker_label}{'  [overlap]' if t.is_overlap else ''}")
        plans = plan_segments(turns, speech, duration, SegmentSettings(), vad_enabled=settings.vad_enabled)
        print(f"post-processed segments: {len(plans)}")
        for p in plans:
            print(f"  {p.start_seconds:8.2f} -> {p.end_seconds:8.2f}  {p.speaker_label}  window {p.window_start:.2f}-{p.window_end:.2f}")
        sequence = collapse([p.speaker_label for p in plans])
        print("speaker sequence:", " -> ".join(sequence))
        if args.expect:
            expected = [x.strip() for x in args.expect.split(",") if x.strip()]
            if sequence == expected:
                print("RESULT: PASS (sequence matches expectation)")
                return 0
            print(f"RESULT: FAIL (expected {' -> '.join(expected)})")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
