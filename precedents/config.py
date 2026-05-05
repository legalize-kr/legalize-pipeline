"""Configuration for the precedents pipeline."""

from core.config import (  # noqa: F401 — re-exported
    BACKOFF_BASE_SECONDS,
    CACHE_ROOT,
    CONCURRENT_WORKERS,
    LAW_API_BASE,
    LAW_API_KEY,
    MAX_RETRIES,
    PRECEDENT_KR_REPO,
    REQUEST_DELAY_SECONDS,
    WORKSPACE_ROOT,
)

# Precedent-specific paths.
PREC_CACHE_DIR = CACHE_ROOT / "precedent"
PRECEDENT_KR_DIR = PRECEDENT_KR_REPO

COURT_TIER_MAP = {"400201": "대법원", "400202": "하급심"}
KNOWN_CASE_TYPES = {"민사", "형사", "일반행정", "세무", "특허", "가사"}
