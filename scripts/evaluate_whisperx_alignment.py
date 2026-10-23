"""Offline Arabic alignment trial using existing text and saved diarization turns.

Mount all inputs read-only and run with --network none. No production API is used.
Output text is private: keep the result under storage/model-evaluation (ignored).
This measures automatic alignment coverage and runtime, not ground-truth accuracy.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import time
from unittest.mock import patch


class InputSpanSplitter:
    """Preserve each existing input utterance; speaker splitting happens later."""
    def span_tokenize(self, text):
        return [(0, len(text))] if text else []


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def valid_interval(start, end) -> bool:
    return bool(isinstance(start, (int, float)) and isinstance(end, (int, float))
                and math.isfinite(start) and math.isfinite(end) and 0 <= start < end)


def report_json(report: dict) -> str:
    """Export NumPy numeric scalars without stringifying numbers or allowing NaN."""
    import numpy as np

    def numeric_scalar(value):
        if isinstance(value, (np.integer, np.floating, np.bool_)):
            return value.item()
        raise TypeError(f"Unsupported report value: {type(value).__name__}")

    return json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False,
                      default=numeric_scalar)


def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return merged


def attribute_words(words: list[dict], turns: list[dict]) -> list[dict]:
    """Assign by actual intersection. Never invent a speaker in silence or ties."""
    by_speaker = defaultdict(list)
    for turn in turns:
        start, end = turn["start_seconds"], turn["end_seconds"]
        if not valid_interval(start, end) or not turn.get("speaker_label"):
            raise ValueError("Invalid diarization interval")
        by_speaker[turn["speaker_label"]].append((start, end))
    by_speaker = {label: merge_intervals(spans) for label, spans in by_speaker.items()}
    result = []
    for original in words:
        word = dict(original)
        start, end = word.get("start"), word.get("end")
        word.update(speaker=None, attribution_status="unaligned", is_overlap=False)
        if valid_interval(start, end):
            intersections = {
                label: [(max(start, a), min(end, b)) for a, b in spans
                        if min(end, b) > max(start, a)]
                for label, spans in by_speaker.items()
            }
            scores = {label: sum(b-a for a, b in spans)
                      for label, spans in intersections.items() if spans}
            ranked = sorted(scores, key=lambda label: (-scores[label], label))
            word["attribution_status"] = "outside_speaker_turns"
            if ranked:
                # A word crossing a sequential boundary differs from simultaneous voices.
                word["is_overlap"] = any(
                    min(b, d) > max(a, c)
                    for i, label in enumerate(ranked) for other in ranked[i+1:]
                    for a, b in intersections[label] for c, d in intersections[other]
                )
                word["speaker_coverage"] = round(min(1, scores[ranked[0]] / (end-start)), 4)
                if len(ranked) > 1 and math.isclose(scores[ranked[0]], scores[ranked[1]], abs_tol=0.001):
                    word["attribution_status"] = "ambiguous"
                else:
                    word["speaker"] = ranked[0]
                    word["attribution_status"] = "overlap" if word["is_overlap"] else "assigned"
        else:
            # JSON output must not carry NaN or fabricated precise times.
            word["start"] = word["end"] = None
        result.append(word)
    return result


def split_runs(words: list[dict], max_gap: float = 1.0) -> list[dict]:
    """Keep every word, breaking at speaker changes and unresolved attribution."""
    runs = []
    for word in words:
        start, end = word.get("start"), word.get("end")
        previous = runs[-1] if runs else None
        same = (previous and previous["speaker_label"] == word["speaker"]
                and previous["attribution_status"] == word["attribution_status"]
                and start is not None and previous["end_seconds"] is not None
                and 0 <= start - previous["end_seconds"] <= max_gap)
        if same:
            previous["words"].append(word)
            previous["text"] += " " + word["word"]
            previous["end_seconds"] = end
        else:
            runs.append({"speaker_label": word["speaker"], "start_seconds": start,
                         "end_seconds": end, "text": word["word"],
                         "attribution_status": word["attribution_status"], "words": [word]})
    return runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--diarization", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu-threads", type=int, default=2)
    args = parser.parse_args()
    hashes = {name: digest(getattr(args, name)) for name in ("audio", "transcript", "diarization")}
    diarization = json.loads(args.diarization.read_text(encoding="utf-8"))
    if diarization["audio_sha256"] != hashes["audio"]:
        raise ValueError("Diarization belongs to a different recording")
    source = json.loads(args.transcript.read_text(encoding="utf-8"))
    models = diarization["models"]
    if len(models) != 1:
        raise ValueError("Provide a diarization report containing one selected model")
    turns = models[0]["turns"]
    import torch
    from whisperx.alignment import align, load_align_model
    from whisperx.audio import load_audio
    torch.set_num_threads(args.cpu_threads)
    torch.set_num_interop_threads(args.cpu_threads)
    audio = load_audio(str(args.audio))
    duration = len(audio) / 16000
    segments = [{"start": max(0, item["start_seconds"]),
                 "end": min(duration, item["end_seconds"]), "text": item["text"]}
                for item in source["segments"]]
    if any(not valid_interval(s["start"], s["end"]) for s in segments):
        raise ValueError("Transcript interval is outside the audio")
    started = time.perf_counter()
    model, metadata = load_align_model("ar", "cpu", model_name=str(args.model), model_cache_only=True)
    loaded = time.perf_counter()
    with patch("whisperx.alignment.nltk_load", return_value=InputSpanSplitter()):
        aligned = align(segments, model, metadata, audio, "cpu", interpolate_method="ignore")
    completed = time.perf_counter()
    words = attribute_words(aligned["word_segments"], turns)
    runs = split_runs(words)
    expected = [word for segment in segments for word in segment["text"].split()]
    actual = [word["word"] for word in words]
    unchanged = all(digest(getattr(args, key)) == value for key, value in hashes.items())
    report = {
        "source_hashes": hashes, "source_unchanged": unchanged,
        "whisperx_source": json.loads(Path('/opt/whisperx-source/SOURCE.json').read_text()),
        "torch_version": torch.__version__, "cpu_threads": args.cpu_threads,
        "alignment_model": json.loads((args.model / "EVALUATION_SOURCE.json").read_text()),
        "diarization_model": models[0]["model_file"], "audio_seconds": round(duration, 3),
        "sentence_segmentation": "existing input utterances; no downloaded sentence tokenizer",
        "model_load_seconds": round(loaded-started, 3),
        "alignment_seconds": round(completed-loaded, 3),
        "input_words": len(expected), "output_words": len(actual), "all_words_preserved": expected == actual,
        "timed_words": sum(valid_interval(w.get("start"), w.get("end")) for w in words),
        "assigned_words": sum(w["speaker"] is not None for w in words),
        "speaker_count": len({w["speaker"] for w in words if w["speaker"] is not None}),
        "status_counts": {status: sum(w["attribution_status"] == status for w in words)
                          for status in sorted({w["attribution_status"] for w in words})},
        "segments": runs, "central_sync_enabled": False,
        "limitation": "No manually labelled reference: timing and speaker accuracy are unmeasured. Existing text is not re-transcribed.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report_json(report), encoding="utf-8")
    print(report_json({key: value for key, value in report.items()
                       if key not in ("segments", "source_hashes", "alignment_model")}), flush=True)
    if not unchanged or expected != actual:
        raise SystemExit("Input integrity or word preservation check failed")


if __name__ == "__main__":
    main()
