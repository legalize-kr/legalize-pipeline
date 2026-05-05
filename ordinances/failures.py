"""JSONL failure ledger for quarantined ordinance records."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.atomic_io import atomic_write_text

from .config import ORDINANCE_FAILURES_FILE

_LOCK = threading.Lock()


def append_failure(row: dict, *, path: Path = ORDINANCE_FAILURES_FILE) -> None:
    payload = {
        **row,
        "timestamp": row.get("timestamp") or datetime.now(timezone.utc).isoformat(),
    }
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        atomic_write_text(path, existing + json.dumps(payload, ensure_ascii=False) + "\n")


def quarantine_type(ordinance_id: str, ordinance_type: str, *, path: Path = ORDINANCE_FAILURES_FILE) -> None:
    append_failure(
        {
            "자치법규ID": str(ordinance_id),
            "자치법규종류": ordinance_type,
            "reason": "type_quarantined",
        },
        path=path,
    )
