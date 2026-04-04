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

# Precedent-specific paths
PREC_CACHE_DIR = WORKSPACE_ROOT / ".cache" / "precedent"
