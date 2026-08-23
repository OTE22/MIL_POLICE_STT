"""Workstation health check: runtime, FFmpeg, GPU, model files, model loading, central key.

    python scripts/healthcheck.py            # static checks
    python scripts/healthcheck.py --load     # also load both models (slow the first time)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.device import detect_device  # noqa: E402
from app.ai.model_files import model_files_status, read_manifest  # noqa: E402
from app.ai.runtime import ModelRuntime  # noqa: E402
from app.audio.ffmpeg_service import ffmpeg_available, ffmpeg_version  # noqa: E402
from app.config import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    s = get_settings()
    report: dict = {"checks": {}}
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        report["checks"][name] = {"ok": ok, "detail": detail}
        if not ok:
            failures += 1

    dev = detect_device()
    check("ffmpeg", ffmpeg_available(), ffmpeg_version() or "ffmpeg/ffprobe not found in PATH")
    check("torch", dev.torch_version is not None, f"torch {dev.torch_version}, cuda={dev.cuda_available} ({dev.gpu_name or 'CPU only'})")
    for name, d in (("stt_files", s.stt_model_dir), ("diarization_files", s.diarization_model_dir)):
        manifest = read_manifest(d)
        ok, problem = model_files_status(d, "size" if s.verify_model_integrity == "none" else s.verify_model_integrity)
        check(name, d.exists() and ok and manifest is not None, f"{d} - {('manifest ' + manifest['revision']) if manifest else 'no manifest'} {problem or ''}".strip())
    check("central_public_key", s.public_key_path.exists(), str(s.public_key_path))
    check("data_dir_writable", _writable(s.data_dir), str(s.data_dir))
    if args.load:
        runtime = ModelRuntime(s)
        try:
            runtime.load_all()
            st = runtime.status()
            check("stt_model_load", st["stt"]["state"] == "READY", st["stt"].get("error") or st["stt"]["extra"].get("device", ""))
            check("diarization_model_load", st["diarization"]["state"] == "READY", st["diarization"].get("error") or st["diarization"]["extra"].get("device", ""))
        except Exception as exc:  # noqa: BLE001
            check("model_load", False, str(exc)[:300])
    report["ok"] = failures == 0
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for name, c in report["checks"].items():
            print(f"[{'OK ' if c['ok'] else 'FAIL'}] {name}: {c['detail']}")
        print("RESULT:", "healthy" if failures == 0 else f"{failures} problem(s)")
    return 0 if failures == 0 else 1


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
