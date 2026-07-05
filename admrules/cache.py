"""File-based cache for raw administrative rule XML responses."""

import os
from pathlib import Path

from core.atomic_io import atomic_write_bytes

from .config import ADMRULE_CACHE_DIR

CACHE_DIR = Path(os.environ["LEGALIZE_ADMRULE_CACHE_DIR"]) if os.environ.get("LEGALIZE_ADMRULE_CACHE_DIR") else ADMRULE_CACHE_DIR


def _detail_path(serial_no: str) -> Path:
    return CACHE_DIR / f"{serial_no}.xml"


def get_detail(serial_no: str) -> bytes | None:
    path = _detail_path(str(serial_no))
    if path.exists():
        return path.read_bytes()
    return None


def put_detail(serial_no: str, content: bytes) -> None:
    path = _detail_path(str(serial_no))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, content)


def list_cached_serials() -> list[str]:
    if not CACHE_DIR.exists():
        return []
    return sorted(p.stem for p in CACHE_DIR.glob("*.xml"))


def prune_details(allowed_serials: set[str]) -> list[str]:
    """Remove cached detail XML files not present in the current full-history search."""
    allowed = {str(serial) for serial in allowed_serials if serial}
    removed: list[str] = []
    for serial in list_cached_serials():
        if serial in allowed:
            continue
        _detail_path(serial).unlink(missing_ok=True)
        removed.append(serial)
    return removed
