"""JSON checkpoint for resumable administrative rule fetching."""

import json
import logging
import threading

from core.atomic_io import atomic_write_text

from .config import WORKSPACE_ROOT

logger = logging.getLogger(__name__)

CHECKPOINT_FILE = WORKSPACE_ROOT / ".admrule-checkpoint.json"
_LOCK = threading.Lock()


def load() -> dict:
    if not CHECKPOINT_FILE.exists():
        return {}
    try:
        return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load admrule checkpoint: %s", e)
        return {}


def _write(data: dict) -> None:
    data.setdefault("schema_version", 1)
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(CHECKPOINT_FILE, json.dumps(data, ensure_ascii=False, indent=2))


def save(data: dict) -> None:
    with _LOCK:
        _write(data)


def _page_key(knd: str, page: int, org: str = "") -> str:
    return f"{org or '*'}:{knd}:{page}"


def mark_page_processed(knd: str, page: int, org: str = "") -> None:
    with _LOCK:
        data = load()
        processed = set(data.get("processed_pages", []))
        processed.add(_page_key(str(knd), int(page), str(org)))
        data["processed_pages"] = sorted(processed)
        _write(data)


def is_page_processed(knd: str, page: int, org: str = "") -> bool:
    return _page_key(str(knd), int(page), str(org)) in set(load().get("processed_pages", []))


def mark_detail_processed(serial_no: str) -> None:
    with _LOCK:
        data = load()
        processed = set(data.get("processed_serials", []))
        processed.add(str(serial_no))
        data["processed_serials"] = sorted(processed, key=lambda value: int(value) if value.isdigit() else value)
        _write(data)


def get_processed_serials() -> set[str]:
    return set(load().get("processed_serials", []))
