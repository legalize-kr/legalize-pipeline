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
    archived = CACHE_DIR / "retired" / path.name
    return archived.read_bytes() if archived.exists() else None


def put_detail(serial_no: str, content: bytes) -> None:
    path = _detail_path(str(serial_no))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, content)


def list_cached_serials() -> list[str]:
    if not CACHE_DIR.exists():
        return []
    return sorted({p.stem for directory in (CACHE_DIR, CACHE_DIR / "retired") for p in directory.glob("*.xml")})


def prune_details(allowed_serials: set[str]) -> list[str]:
    """Archive withdrawn XML so a rebuild retains earlier publication history."""
    allowed = {str(serial) for serial in allowed_serials if serial}
    removed: list[str] = []
    for serial in list_cached_serials():
        path = _detail_path(serial)
        if serial in allowed or not path.exists():
            continue
        archive = CACHE_DIR / "retired"
        archive.mkdir(exist_ok=True)
        path.replace(archive / path.name)
        removed.append(serial)
    return removed
