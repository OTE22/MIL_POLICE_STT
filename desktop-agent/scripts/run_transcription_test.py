"""Real Arabic transcription test with the local Cohere model.

    python scripts/run_transcription_test.py path/to/arabic.wav
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.transcription_service import build_transcription_service  # noqa: E402
from app.audio.preprocessing import make_processing_copy  # noqa: E402
from app.config import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    args = parser.parse_args()
    settings = get_settings()
    import soundfile as sf

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "processing.wav"
        duration = make_processing_copy(Path(args.audio), wav)
        audio, sr = sf.read(str(wav), dtype="float32")
        stt = build_transcription_service(settings)
        t0 = time.time()
        stt.load()
        print(f"model loaded in {time.time() - t0:.1f}s on {stt.device}: {stt.info().model}@{stt.info().revision}")
        t0 = time.time()
        result = stt.transcribe(audio, sr)
        elapsed = time.time() - t0
        print(f"transcribed {duration:.1f}s of audio in {elapsed:.1f}s (RTFx {duration / max(elapsed, 1e-6):.1f})")
        print("TEXT:", result.text)
        return 0 if result.text.strip() else 1


if __name__ == "__main__":
    raise SystemExit(main())
