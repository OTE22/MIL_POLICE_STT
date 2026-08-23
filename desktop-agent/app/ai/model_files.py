"""Model integrity: MANIFEST.json written at provisioning time, verified at load time."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST_NAME = "MANIFEST.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(model_dir: Path, *, model: str, revision: str, source: str) -> dict:
    files = {}
    for p in sorted(model_dir.rglob("*")):
        if p.is_file() and p.name != MANIFEST_NAME:
            rel = p.relative_to(model_dir).as_posix()
            files[rel] = {"size": p.stat().st_size, "sha256": sha256_file(p)}
    manifest = {"model": model, "revision": revision, "source": source, "files": files}
    (model_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def read_manifest(model_dir: Path) -> dict | None:
    p = model_dir / MANIFEST_NAME
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def model_files_status(model_dir: Path, mode: str = "size") -> tuple[bool, str | None]:
    """Verify the provisioned files against MANIFEST.json.

    mode: none | size | full (sha256 of every file; slow for multi-GB models)
    """
    if mode == "none":
        return True, None
    manifest = read_manifest(model_dir)
    if manifest is None:
        # Not fatal: models copied manually without a manifest are allowed but unverified.
        return True, "no manifest"
    for rel, meta in manifest.get("files", {}).items():
        p = model_dir / rel
        if not p.exists():
            return False, f"missing {rel}"
        if p.stat().st_size != meta.get("size"):
            return False, f"size mismatch {rel}"
        if mode == "full" and sha256_file(p) != meta.get("sha256"):
            return False, f"sha256 mismatch {rel}"
    return True, None
