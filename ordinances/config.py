"""Configuration for the ordinance pipeline."""

from core.config import (  # noqa: F401
    BACKOFF_BASE_SECONDS,
    BOT_AUTHOR,
    CACHE_ROOT,
    CONCURRENT_WORKERS,
    LAW_API_BASE,
    LAW_API_KEY,
    MAX_RETRIES,
    ORDINANCE_KR_REPO,
    PROJECT_ROOT,
    REQUEST_DELAY_SECONDS,
    WORKSPACE_ROOT,
)

ORDINANCE_REPO = ORDINANCE_KR_REPO
ORDINANCE_CACHE_DIR = CACHE_ROOT / "ordinance"
ORDINANCE_FAILURES_FILE = CACHE_ROOT / "ordinance_failures.jsonl"

API_TYPES = ("조례", "규칙", "훈령", "예규", "고시", "의회규칙", "기타")
STORAGE_TYPES = ("조례", "규칙", "훈령", "예규", "고시", "의회규칙")

TYPE_CODES = {
    "조례": "C0001",
    "규칙": "C0002",
    "훈령": "C0003",
    "예규": "C0004",
    "기타": "C0006",
    "고시": "C0010",
    "의회규칙": "C0011",
}
