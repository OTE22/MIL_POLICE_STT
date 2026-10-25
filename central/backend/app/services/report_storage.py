"""Path-confined atomic storage for immutable HTML/PDF report artifacts."""
import hashlib
from pathlib import Path
from app.config import get_settings


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _confined(relative: str) -> Path:
    settings = get_settings()
    root = settings.storage_root.resolve()
    path = (settings.storage_root / relative).resolve()
    if root not in path.parents:
        raise ValueError("invalid_path")
    return path


def atomic_write(relative: str, data: bytes) -> tuple[str, int, str]:
    """Write bytes into storage atomically. Returns (relative_path, size, sha256)."""
    target = _confined(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        tmp.write_bytes(data)
        tmp.replace(target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return relative, len(data), sha256_bytes(data)


def read_file(relative: str) -> bytes | None:
    try:
        path = _confined(relative)
    except ValueError:
        return None
    return path.read_bytes() if path.is_file() else None


def absolute_path(relative: str) -> Path | None:
    """The on-disk path, or None when it is missing or outside storage."""
    try:
        path = _confined(relative)
    except ValueError:
        return None
    return path if path.is_file() else None


