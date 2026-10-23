"""Fetch only the official release's alignment modules, retaining its license."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

REVISION = "3ccc17b8de34f305300f8a3fd3c9f76ba820c0d0"
FILES = ["LICENSE", *["whisperx/" + name + ".py" for name in
                       ("__init__", "alignment", "audio", "utils", "schema", "log_utils")]]


def main():
    destination = Path(sys.argv[1])
    def fetch(relative):
        url = f"https://raw.githubusercontent.com/m-bain/whisperX/{REVISION}/{relative}"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return relative, hashlib.sha256(data).hexdigest()
    with ThreadPoolExecutor(max_workers=4) as pool:
        hashes = dict(pool.map(fetch, FILES))
    (destination / "SOURCE.json").write_text(json.dumps({
        "repository": "https://github.com/m-bain/whisperX", "release": "3.8.6",
        "revision": REVISION, "files": hashes, "scope": "alignment modules only",
    }, indent=2), encoding="utf-8")
    print(f"Downloaded {len(hashes)} official alignment source files at {REVISION}", flush=True)


if __name__ == "__main__":
    main()
