"""JSON checkpoint for resumable ordinance fetching."""

import json
import logging
import threading

from core.atomic_io import atomic_write_text

from .config import WORKSPACE_ROOT

logger = logging.getLogger(__name__)

CHECKPOINT_FILE = WORKSPACE_ROOT / ".ordinance-checkpoint.json"
_LOCK = threading.Lock()


def load() -> dict:
    if not CHECKPOINT_FILE.exists():
        return {}
    try:
        return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load ordinance checkpoint: %s", e)
        return {}


def _write(data: dict) -> None:
    data.setdefault("schema_version", 1)
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(CHECKPOINT_FILE, json.dumps(data, ensure_ascii=False, indent=2))


def _page_key(ordinance_type: str, page: int, org: str = "", sborg: str = "") -> str:
    return f"{org or '*'}:{sborg or '*'}:{ordinance_type}:{page}"


def mark_page_processed(ordinance_type: str, page: int, org: str = "", sborg: str = "") -> None:
    with _LOCK:
        data = load()
        processed = set(data.get("processed_pages", []))
        processed.add(_page_key(str(ordinance_type), int(page), str(org), str(sborg)))
        data["processed_pages"] = sorted(processed)
        _write(data)


def is_page_processed(ordinance_type: str, page: int, org: str = "", sborg: str = "") -> bool:
    return _page_key(str(ordinance_type), int(page), str(org), str(sborg)) in set(load().get("processed_pages", []))


def mark_detail_processed(ordinance_id: str) -> None:
    with _LOCK:
        data = load()
        processed = set(data.get("processed_ids", []))
        processed.add(str(ordinance_id))
        data["processed_ids"] = sorted(processed, key=lambda value: int(value) if value.isdigit() else value)
        _write(data)


def get_processed_ids() -> set[str]:
    return set(load().get("processed_ids", []))
