"""One-time model provisioning (run on a machine with Internet access, or from an offline bundle).

Downloads the pinned revisions into MODEL_DIR and writes MANIFEST.json with
SHA-256 of every file. Afterwards the workstation never needs Internet access.

Usage:
    python scripts/provision_models.py --model-dir /models [--only stt|diarization|vad]
    HF_TOKEN=hf_xxx python scripts/provision_models.py   # Cohere model is gated -> accept the license on HF first

The HF token is used only for this download; it is never stored by the agent.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.model_files import read_manifest, write_manifest  # noqa: E402
from app.config import (  # noqa: E402
    COHERE_STT_MODEL,
    COHERE_STT_REVISION,
    NVIDIA_DIARIZATION_MODEL,
    NVIDIA_DIARIZATION_REVISION,
    SPEAKERNET_MODEL,
    SPEAKERNET_REVISION,
    SPEAKERNET_SHA256,
    SPEAKERNET_URL,
    get_settings,
)

STT_FILES = [
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "normalizer.json",
    "preprocessor_config.json",
    "processor_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer.model",
    "tokenizer_config.json",
]


def provision_hf(repo: str, revision: str, target: Path, allow_patterns: list[str] | None, token: str | None) -> None:
    from huggingface_hub import snapshot_download

    target.mkdir(parents=True, exist_ok=True)
    print(f"-> downloading {repo}@{revision} into {target}")
    snapshot_download(
        repo_id=repo,
        revision=revision,
        local_dir=str(target),
        allow_patterns=allow_patterns,
        token=token,
    )
    # Remove the HF cache bookkeeping so the directory is a plain file set.
    shutil.rmtree(target / ".cache", ignore_errors=True)
    manifest = write_manifest(target, model=repo, revision=revision, source="huggingface")
    print(f"   {len(manifest['files'])} files, manifest written")


def provision_speakernet(target: Path) -> None:
    """SpeakerNet-M is distributed through NVIDIA NGC, not Hugging Face."""
    import hashlib
    import urllib.request

    target.mkdir(parents=True, exist_ok=True)
    dest = target / f"{SPEAKERNET_MODEL.split('/')[-1]}.nemo"
    if not dest.exists():
        print(f"-> downloading {SPEAKERNET_MODEL}@{SPEAKERNET_REVISION} from NGC")
        tmp = dest.with_suffix(".nemo.part")
        with urllib.request.urlopen(SPEAKERNET_URL, timeout=120) as r, tmp.open("wb") as fh:
            shutil.copyfileobj(r, fh)
        tmp.replace(dest)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    if digest != SPEAKERNET_SHA256:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"SpeakerNet sha256 mismatch: {digest}")
    write_manifest(target, model=SPEAKERNET_MODEL, revision=SPEAKERNET_REVISION, source="ngc")
    print(f"   verified sha256={digest[:16]}...")


def provision_vad(target: Path) -> None:
    """Silero VAD ships inside the `silero-vad` wheel; record its identity for the manifest."""
    from importlib.metadata import version

    import silero_vad

    pkg_dir = Path(silero_vad.__file__).parent / "data"
    target.mkdir(parents=True, exist_ok=True)
    for f in pkg_dir.glob("*"):
        if f.is_file():
            shutil.copy2(f, target / f.name)
    write_manifest(target, model="snakers4/silero-vad", revision=f"silero-vad {version('silero-vad')}", source="pypi")
    print(f"-> VAD model files copied to {target} (bundled with silero-vad {version('silero-vad')})")


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", default=str(settings.model_dir))
    parser.add_argument("--only", choices=["stt", "diarization", "speaker_id", "vad"], default=None)
    parser.add_argument("--force", action="store_true", help="re-download even if a manifest exists")
    args = parser.parse_args()
    model_dir = Path(args.model_dir)
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

    targets = {
        "stt": (COHERE_STT_MODEL, COHERE_STT_REVISION, model_dir / COHERE_STT_MODEL.split("/")[-1], STT_FILES),
        "diarization": (
            NVIDIA_DIARIZATION_MODEL,
            NVIDIA_DIARIZATION_REVISION,
            model_dir / NVIDIA_DIARIZATION_MODEL.split("/")[-1],
            ["*.nemo", "README.md"],
        ),
    }
    ok = True
    for key, (repo, rev, target, patterns) in targets.items():
        if args.only and args.only != key:
            continue
        if not args.force and read_manifest(target):
            print(f"-> {repo} already provisioned in {target} (use --force to re-download)")
            continue
        try:
            provision_hf(repo, rev, target, patterns, token)
        except Exception as exc:  # noqa: BLE001
            ok = False
            msg = str(exc)
            if "401" in msg or "403" in msg or "gated" in msg.lower():
                print(
                    f"!! {repo} is gated. Accept the license at https://huggingface.co/{repo} "
                    "and re-run with HF_TOKEN=<your token>.",
                    file=sys.stderr,
                )
            else:
                print(f"!! failed to provision {repo}: {msg}", file=sys.stderr)
    if not args.only or args.only == "speaker_id":
        try:
            provision_speakernet(model_dir / SPEAKERNET_MODEL.split("/")[-1])
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"!! failed to provision {SPEAKERNET_MODEL}: {exc}", file=sys.stderr)
    if not args.only or args.only == "vad":
        try:
            provision_vad(model_dir / "silero-vad")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"!! failed to provision VAD: {exc}", file=sys.stderr)
    print("done" if ok else "finished with errors")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
