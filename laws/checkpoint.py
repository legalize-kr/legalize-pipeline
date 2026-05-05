"""Simple JSON checkpoint for resumable imports."""

import json
import logging
import threading

from .config import CACHE_ROOT

logger = logging.getLogger(__name__)

CHECKPOINT_FILE = CACHE_ROOT / ".checkpoint.json"
_LOCK = threading.Lock()


def load() -> dict:
    """Load checkpoint data. Returns empty dict if no checkpoint exists."""
    if not CHECKPOINT_FILE.exists():
        return {}
    try:
        return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load checkpoint: {e}")
        return {}


def _write(data: dict) -> None:
    data.setdefault("schema_version", 2)
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save(data: dict) -> None:
    """Save checkpoint data."""
    with _LOCK:
        _write(data)


def get_processed_msts() -> set[str]:
    """Get set of already-processed 법령MST values."""
    data = load()
    return set(data.get("processed_msts", []))


def mark_processed(mst: str) -> None:
    """Mark a 법령MST as processed."""
    with _LOCK:
        data = load()
        processed = set(data.get("processed_msts", []))
        processed.add(str(mst))
        data["processed_msts"] = sorted(processed)
        _write(data)


def set_last_update(date: str) -> None:
    """Set the last update date for incremental updates."""
    with _LOCK:
        data = load()
        data["last_update"] = date
        _write(data)


def get_last_update() -> str:
    """Get the last update date. Returns empty string if not set."""
    return load().get("last_update", "")
