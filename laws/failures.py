"""Failure tracking for resumable imports.

Two-section ledger:
  failed_msts      – keyed by 법령MST (parse/convert errors)
  search_misses    – keyed by law name (search API returned no results)
"""

import json
import logging
import threading
import time
from pathlib import Path

from .config import CACHE_ROOT

logger = logging.getLogger(__name__)

FAILED_FILE = CACHE_ROOT / ".failed_msts.json"

_LOCK = threading.Lock()

EXCEPTION_REASON_MAP: dict[type[BaseException], str] = {
    ValueError: "empty_body",
    RuntimeError: "api_error",
    OSError: "io_error",
    KeyError: "metadata_missing",
}


def _load() -> dict:
    if not FAILED_FILE.exists():
        return {"schema_version": 1, "failed_msts": {}, "search_misses": {}}
    try:
        data = json.loads(FAILED_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load failures file: {e}")
        return {"schema_version": 1, "failed_msts": {}, "search_misses": {}}
    data.setdefault("schema_version", 1)
    data.setdefault("failed_msts", {})
    data.setdefault("search_misses", {})
    return data


def _write(data: dict) -> None:
    FAILED_FILE.parent.mkdir(parents=True, exist_ok=True)
    FAILED_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def classify(exc: BaseException) -> str:
    """Map an exception to a reason string using isinstance checks."""
    for exc_type, reason in EXCEPTION_REASON_MAP.items():
        if isinstance(exc, exc_type):
            return reason
    return "unknown"


def mark_failed(
    mst: str,
    reason: str,
    detail: str = "",
    step: str = "",
    law_name: str = "",
) -> None:
    """Record a failed MST in the failed_msts section."""
    with _LOCK:
        data = _load()
        data["failed_msts"][str(mst)] = {
            "reason": reason,
            "detail": detail[:500],
            "step": step,
            "law_name": law_name,
            "failed_at": time.time(),
        }
        _write(data)


def mark_search_miss(
    name: str,
    reason: str = "search_miss",
    detail: str = "",
    step: str = "search_api",
) -> None:
    """Record a search miss in the search_misses section."""
    with _LOCK:
        data = _load()
        data["search_misses"][name] = {
            "reason": reason,
            "detail": detail[:500],
            "step": step,
            "last_attempt_at": time.time(),
        }
        _write(data)


def mark_failed_and_quarantine(
    mst: str,
    reason: str,
    detail: str,
    path: Path,
    step: str = "",
    law_name: str = "",
) -> None:
    """Record failure and rename the file to a .stale quarantine name."""
    mark_failed(mst, reason, detail, step=step, law_name=law_name)
    if path.exists():
        stale = path.with_name("." + path.name + ".stale")
        path.rename(stale)
        logger.warning(
            "quarantined stale file",
            extra={"mst": mst, "from": str(path), "to": str(stale)},
        )


def get_failed_msts() -> dict[str, dict]:
    """Return a copy of the failed_msts section."""
    return _load()["failed_msts"]


def get_search_misses() -> dict[str, dict]:
    """Return a copy of the search_misses section."""
    return _load()["search_misses"]


def log_failure(step: str, mst: str, law_name: str, exc: BaseException) -> None:
    """Emit a structured error log record for an import failure.

    Two-channel design: diagnostic fields are attached as ``extra={...}`` (for
    structured handlers and the test suite, which asserts on
    ``record.step``/``record.exc_type``/etc.) AND inlined into the rendered
    message (so the default root-logger format
    ``%(asctime)s %(levelname)s %(message)s`` still surfaces them on the
    console — otherwise every failure collapses to a bare "import_failure"
    line with no way to triage).
    """
    exc_type = type(exc).__name__
    exc_msg = str(exc)[:500]
    logger.error(
        "import_failure step=%s mst=%s law_name=%r exc_type=%s exc_msg=%s",
        step,
        mst,
        law_name,
        exc_type,
        exc_msg,
        extra={
            "step": step,
            "mst": mst,
            "exc_type": exc_type,
            "exc_msg": exc_msg,
        },
    )
