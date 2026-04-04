"""File-based cache for raw law detail API responses and amendment history.

Caches detail (lawService.do) responses in .cache/detail/{MST}.xml and
amendment history (lsHistory) in .cache/history/{law_name}.json.
"""

import hashlib
import json
import logging
from pathlib import Path

from .config import WORKSPACE_ROOT
from core.atomic_io import atomic_write_bytes, atomic_write_text

logger = logging.getLogger(__name__)

CACHE_DIR = WORKSPACE_ROOT / ".cache"

# OS filename limit is typically 255 bytes; leave margin for extension
_MAX_FILENAME_BYTES = 200


def _safe_filename(name: str, ext: str) -> str:
    """Return a safe filename, using hash suffix if name exceeds OS limit."""
    candidate = f"{name}{ext}"
    if len(candidate.encode("utf-8")) <= _MAX_FILENAME_BYTES:
        return candidate
    h = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    suffix = f"_{h}{ext}"
    prefix = name
    while len(f"{prefix}{suffix}".encode("utf-8")) > _MAX_FILENAME_BYTES:
        prefix = prefix[:-1]
    return f"{prefix}{suffix}"


def _detail_path(mst_id: str) -> Path:
    return CACHE_DIR / "detail" / f"{mst_id}.xml"


def get_detail(mst_id: str) -> bytes | None:
    path = _detail_path(str(mst_id))
    if path.exists():
        return path.read_bytes()
    return None


def put_detail(mst_id: str, content: bytes) -> None:
    path = _detail_path(str(mst_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, content)


def list_cached_msts() -> list[str]:
    """List all MST IDs that have cached detail XML."""
    detail_dir = CACHE_DIR / "detail"
    if not detail_dir.exists():
        return []
    return [p.stem for p in detail_dir.glob("*.xml")]


def _history_path(law_name: str) -> Path:
    return CACHE_DIR / "history" / _safe_filename(law_name, ".json")


def get_history(law_name: str) -> list[dict] | None:
    """Read cached amendment history for a law. Returns parsed list or None."""
    path = _history_path(law_name)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def put_history(law_name: str, entries: list[dict]) -> None:
    """Write amendment history for a law to cache."""
    path = _history_path(law_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(entries, ensure_ascii=False, indent=2))


def list_cached_history_names() -> list[str]:
    """List all law names that have cached history JSON."""
    history_dir = CACHE_DIR / "history"
    if not history_dir.exists():
        return []
    return [p.stem for p in history_dir.glob("*.json")]
