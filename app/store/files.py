"""The ML model beside the database (ADR-0010; ADR-0020 moved every upload into `blobs`).

The model lives at `DATA_DIR/models/<name>-<sha256 prefix>.joblib`; its `model_versions` row
keeps the relative path and the full sha256, and a read verifies the digest before the bytes
are unpickled. Paths are built only from the model name and the digest — never from a
caller-supplied name — so nothing can escape the data directory."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .database import database

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def _safe(part: str, what: str) -> str:
    if not isinstance(part, str) or not _SAFE.match(part) or ".." in part:
        raise ValueError(f"unsafe {what}: {part!r}")
    return part


# --- models -----------------------------------------------------------------------

def model_relpath(name: str, sha256: str) -> str:
    return f"models/{_safe(name, 'model name')}-{_safe(sha256[:8], 'sha')}.joblib"


def write_model(name: str, data: bytes) -> tuple[str, str]:
    """Store model bytes; returns (relative path, sha256). Same bytes -> same path."""
    sha = hashlib.sha256(data).hexdigest()
    rel = model_relpath(name, sha)
    path = database.data_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel, sha


def read_model(row: dict) -> bytes:
    """Bytes for a `model_versions` row; raises if the sha256 no longer matches."""
    rel = row.get("path") or ""
    if not rel.startswith("models/"):
        raise ValueError(f"model path outside models/: {rel!r}")
    _safe(Path(rel).name, "model file")
    data = (database.data_dir / rel).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if row.get("sha256") and sha != row["sha256"]:
        raise RuntimeError("model file failed SHA256 integrity check")
    return data


def delete_model_file(rel: str) -> bool:
    path = database.data_dir / rel
    if rel.startswith("models/") and path.exists():
        path.unlink()
        return True
    return False
