"""Configuration for the precedents pipeline."""

from core.config import (  # noqa: F401 — re-exported
    BACKOFF_BASE_SECONDS,
    CONCURRENT_WORKERS,
    LAW_API_BASE,
    LAW_API_KEY,
    MAX_RETRIES,
    REQUEST_DELAY_SECONDS,
    WORKSPACE_ROOT,
)

# Precedent-specific paths.
# PRECEDENT_KR_DIR mirrors laws/config.py:KR_DIR pattern: in CI the precedent-kr
# repo is checked out directly into WORKSPACE_ROOT (same as legalize-kr for laws),
# so the data root IS WORKSPACE_ROOT. For local meta-workspace runs, set
# WORKSPACE_ROOT=/path/to/precedent-kr explicitly.
PREC_CACHE_DIR = WORKSPACE_ROOT / ".cache" / "precedent"
PRECEDENT_KR_DIR = WORKSPACE_ROOT

COURT_TIER_MAP = {"400201": "대법원", "400202": "하급심"}
KNOWN_CASE_TYPES = {"민사", "형사", "일반행정", "세무", "특허", "가사"}
