"""File-based cache for raw precedent detail API responses."""

import logging

from core.atomic_io import atomic_write_bytes

from .config import PREC_CACHE_DIR

logger = logging.getLogger(__name__)


def get_detail(prec_id: str) -> bytes | None:
    path = PREC_CACHE_DIR / f"{prec_id}.xml"
    if path.exists():
        return path.read_bytes()
    return None


def put_detail(prec_id: str, content: bytes) -> None:
    path = PREC_CACHE_DIR / f"{prec_id}.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, content)


def list_cached_ids() -> list[str]:
    """List all precedent IDs that have cached detail XML."""
    if not PREC_CACHE_DIR.exists():
        return []
    return [p.stem for p in PREC_CACHE_DIR.glob("*.xml")]
