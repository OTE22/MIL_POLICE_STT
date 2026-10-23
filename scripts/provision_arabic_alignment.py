"""Download the public, pinned Arabic alignment model without credentials or audio."""
import hashlib
import json
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

REPOSITORY = "jonatasgrosman/wav2vec2-large-xlsr-53-arabic"
REVISION = "af46c2d8531b8dcbb5e23b952f739b372c2e5d2d"
WEIGHTS_SHA256 = "a0b26f6d9d3edfde1784aef863c192a8cc1e438a23b45910ab648531ebe1857b"


def main():
    target = Path(sys.argv[1])
    snapshot_download(REPOSITORY, revision=REVISION, token=False, local_dir=target,
                      allow_patterns=["*.json", "pytorch_model.bin", "README.md"], max_workers=2)
    with (target / "pytorch_model.bin").open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != WEIGHTS_SHA256:
        raise RuntimeError("Alignment checkpoint checksum mismatch")
    (target / "EVALUATION_SOURCE.json").write_text(json.dumps({
        "repository": REPOSITORY, "revision": REVISION, "weights_sha256": actual,
    }, indent=2), encoding="utf-8")
    print("Arabic alignment model downloaded and checksum verified", flush=True)


if __name__ == "__main__":
    main()
