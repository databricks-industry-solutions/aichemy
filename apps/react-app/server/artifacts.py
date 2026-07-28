"""Shared on-disk artifact store for downloadable agent outputs (e.g. DOCX).

Agent process writes files here; web server serves them at /api/artifacts/{id}.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from uuid import uuid4

_APP_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = _APP_ROOT / "artifacts"
_META_SUFFIX = ".meta.json"
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def ensure_artifacts_dir() -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR


def is_valid_artifact_id(artifact_id: str) -> bool:
    return bool(artifact_id and _UUID_RE.match(artifact_id))


def save_artifact(
    data: bytes,
    *,
    filename: str,
    media_type: str = DOCX_MEDIA_TYPE,
) -> dict:
    """Persist bytes and return metadata including download path."""
    ensure_artifacts_dir()
    artifact_id = str(uuid4())
    safe_name = _safe_filename(filename)
    file_path = ARTIFACTS_DIR / f"{artifact_id}.bin"
    meta_path = ARTIFACTS_DIR / f"{artifact_id}{_META_SUFFIX}"

    file_path.write_bytes(data)
    meta = {
        "id": artifact_id,
        "filename": safe_name,
        "media_type": media_type,
        "created_at": time.time(),
        "size": len(data),
    }
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return {
        **meta,
        "download_path": f"/api/artifacts/{artifact_id}",
    }


def get_artifact(artifact_id: str) -> tuple[Path, dict] | None:
    """Return (file_path, meta) or None if missing/invalid."""
    if not is_valid_artifact_id(artifact_id):
        return None
    file_path = ARTIFACTS_DIR / f"{artifact_id}.bin"
    meta_path = ARTIFACTS_DIR / f"{artifact_id}{_META_SUFFIX}"
    if not file_path.is_file() or not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return file_path, meta


def _safe_filename(name: str) -> str:
    base = Path(name or "document.docx").name.strip() or "document.docx"
    base = re.sub(r"[^\w.\- ]+", "_", base).strip(" ._") or "document.docx"
    if not base.lower().endswith(".docx"):
        base = f"{base}.docx"
    return base
