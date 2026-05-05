"""Configuration for the images pipeline."""

from pathlib import Path

from core.config import (  # noqa: F401 — re-exported
    BACKOFF_BASE_SECONDS,
    CACHE_ROOT,
    CONCURRENT_WORKERS,
    LEGALIZE_KR_REPO,
    MAX_RETRIES,
    REQUEST_DELAY_SECONDS,
    WORKSPACE_ROOT,
)

# Image-specific paths
LAW_REPO = LEGALIZE_KR_REPO
KR_DIR = LAW_REPO / "kr"
IMAGE_CACHE_DIR = CACHE_ROOT / "images"
MANIFEST_PATH = IMAGE_CACHE_DIR / "manifest.json"
CHECKSUMS_PATH = IMAGE_CACHE_DIR / "checksums.json"

# Image download base URL
IMAGE_DOWNLOAD_URL = "https://www.law.go.kr/LSW/flDownload.do"

# CDN settings (fixed — change here if domain or structure changes)
CDN_BASE = "https://img.legalize.kr"
LAW_IMAGE_PREFIX = "laws"  # R2 key prefix for law images: laws/{image_id}.gif


def set_cache_dir(path: Path) -> None:
    """Override IMAGE_CACHE_DIR and derived paths at runtime."""
    global IMAGE_CACHE_DIR, MANIFEST_PATH, CHECKSUMS_PATH
    IMAGE_CACHE_DIR = path
    MANIFEST_PATH = path / "manifest.json"
    CHECKSUMS_PATH = path / "checksums.json"


def set_kr_dir(path: Path) -> None:
    """Override KR_DIR (markdown source directory) at runtime."""
    global KR_DIR
    KR_DIR = path
