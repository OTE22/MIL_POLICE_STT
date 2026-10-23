"""Run real local models on a private copy; never sync or alter source evidence.

Run in the candidate image with --network none, read-only models/audio mounts,
and a separate writable output directory. The report omits transcript text and
voiceprint vectors. Speaker-count checks do not establish DER or word accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import logging
import math
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class OfflineClient:
    enabled = False

    def report_state(self, *args, **kwargs):
        raise AssertionError("An offline evaluation must not report to a server")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-speakers", type=int, required=True)
    parser.add_argument("--cpu-threads", type=int, default=2)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    import torch
    from app.ai.runtime import ModelRuntime
    from app.config import Settings, NEMOTRON_DIARIZATION_MODEL
    from app.jobs.pipeline import JobPipeline
    from app.jobs.store import JobRecord, JobStore

    torch.set_num_threads(args.cpu_threads)
    torch.set_num_interop_threads(args.cpu_threads)
    original_sha = digest(args.audio)
    started = time.perf_counter()
    report = {"source_sha256": original_sha, "expected_speakers": args.expected_speakers,
              "nemo_source_revision": os.getenv("NEMO_SOURCE_REVISION"),
              "nemo_version": importlib.metadata.version("nemo-toolkit"),
              "lhotse_version": importlib.metadata.version("lhotse"),
              "torch_version": torch.__version__, "cpu_threads": args.cpu_threads,
              "central_sync_enabled": False,
              "limitations": "Counts and pipeline compatibility only; no annotated DER or transcript-accuracy reference."}
    try:
        with tempfile.TemporaryDirectory(prefix="agent-pipeline-evaluation-") as private:
            workdir = Path(private)
            copied_audio = workdir / args.audio.name
            shutil.copyfile(args.audio, copied_audio)
            settings = Settings(_env_file=None, data_dir=workdir / "data", model_dir=args.models,
                                diarization_model=NEMOTRON_DIARIZATION_MODEL,
                                stt_device="cpu", diarization_device="cpu", speaker_id_device="cpu",
                                verify_model_integrity="full", central_sync_enabled=False,
                                central_upload_audio=False, central_public_key_auto_fetch=False,
                                preload_models=False, speaker_id_enabled=True)
            runtime = ModelRuntime(settings)
            store = JobStore(settings.db_path)
            try:
                job = JobRecord(job_id=str(uuid.uuid4()), session_id=str(uuid.uuid4()),
                                recording_id=str(uuid.uuid4()), user_id="offline-evaluation",
                                original_filename=copied_audio.name, original_path=str(copied_audio),
                                audio_metadata={"mime_type": "audio/webm", "audio_channel_mode": "mixed"})
                store.save(job)
                JobPipeline(settings, store, runtime, OfflineClient(),
                            lambda: {"agent_id": "offline-evaluation"}).run(job)
                report.update(state=job.state, error_code=job.error_code, error_message=job.error_message,
                              failure_stage=job.failure_stage, sync_state=job.sync_state,
                              copy_unchanged=digest(copied_audio) == original_sha,
                              runtime=runtime.status())
                if job.result_path:
                    result = json.loads(Path(job.result_path).read_text(encoding="utf-8"))
                    embeddings = (result.get("voice_identification") or {}).get("speakers", {})
                    report.update(speaker_count=result["speaker_count"],
                                  model=result["diarization_model"], revision=result["diarization_model_revision"],
                                  processing_metadata=result["processing_metadata"], warnings=result["warnings"],
                                  transcript_segments=[{k: v for k, v in segment.items() if k != "text"}
                                                       | {"text_characters": len(segment["text"])} for segment in result["segments"]],
                                  embeddings={label: {"dimension": len(item["embedding"]),
                                                      "norm": math.sqrt(sum(v * v for v in item["embedding"])),
                                                      "seconds": item["seconds"]} for label, item in embeddings.items()})
                    labels = {segment["speaker_label"] for segment in result["segments"]}
                    report["passed"] = (job.state == "COMPLETED" and job.sync_state == "NOT_STARTED"
                                        and len(labels) == args.expected_speakers and set(embeddings) == labels
                                        and all(item["dimension"] == 256 and abs(item["norm"] - 1) < 0.001
                                                for item in report["embeddings"].values())
                                        and report["copy_unchanged"])
                else:
                    report["passed"] = False
            finally:
                store.close()
    except Exception as exc:
        report.update(passed=False, error_type=type(exc).__name__, error_message=str(exc))
        logging.exception("Offline pipeline evaluation failed")
    finally:
        report["source_unchanged"] = digest(args.audio) == original_sha
        report["passed"] = report.get("passed", False) and report["source_unchanged"]
        report["elapsed_seconds"] = round(time.perf_counter() - started, 2)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: report.get(key) for key in ("passed", "state", "speaker_count", "embeddings", "source_unchanged", "elapsed_seconds")}), flush=True)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
