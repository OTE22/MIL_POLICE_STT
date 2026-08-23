"""Finalize a manually downloaded Cohere weights file.

Verifies size and SHA-256 of model.safetensors(.part) against the pinned revision's
LFS object, renames it into place and (re)writes MANIFEST.json. Used after
resume_cohere_weights.ps1 or after copying a bundle by hand.

    python scripts/finalize_cohere_weights.py [--model-dir ../models]
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.model_files import write_manifest  # noqa: E402
from app.config import COHERE_STT_MODEL, COHERE_STT_REVISION, get_settings  # noqa: E402

EXPECTED_SIZE = 4131862976
EXPECTED_SHA256 = "404ff5dccd66b1985a06059b9d5ed970a676761c0821f9c10756db6e4a1910a5"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", default=str(get_settings().model_dir))
    args = parser.parse_args()
    model_dir = Path(args.model_dir) / COHERE_STT_MODEL.split("/")[-1]
    part = model_dir / "model.safetensors.part"
    final = model_dir / "model.safetensors"
    src = final if final.exists() else part
    if not src.exists():
        print(f"!! no weights file found in {model_dir}", file=sys.stderr)
        return 1
    size = src.stat().st_size
    if size != EXPECTED_SIZE:
        print(f"!! size {size} != expected {EXPECTED_SIZE} (download incomplete?)", file=sys.stderr)
        return 1
    print("verifying SHA-256 (4 GB, this takes a minute)...")
    h = hashlib.sha256()
    with src.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    digest = h.hexdigest()
    if digest != EXPECTED_SHA256:
        print(f"!! sha256 mismatch: {digest}", file=sys.stderr)
        return 1
    if src != final:
        src.replace(final)
    shutil.rmtree(model_dir / ".cache", ignore_errors=True)
    manifest = write_manifest(model_dir, model=COHERE_STT_MODEL, revision=COHERE_STT_REVISION, source="huggingface (manual resume)")
    print(f"OK: {final} sha256={digest[:16]}... manifest with {len(manifest['files'])} files written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
