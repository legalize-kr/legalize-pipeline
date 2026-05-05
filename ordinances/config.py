"""Configuration for the ordinance pipeline."""

from core.config import (  # noqa: F401
    BACKOFF_BASE_SECONDS,
    BOT_AUTHOR,
    CONCURRENT_WORKERS,
    LAW_API_BASE,
    LAW_API_KEY,
    MAX_RETRIES,
    PROJECT_ROOT,
    REQUEST_DELAY_SECONDS,
    WORKSPACE_ROOT,
)

ORDINANCE_REPO = WORKSPACE_ROOT / "ordinance-kr"
ORDINANCE_CACHE_DIR = WORKSPACE_ROOT / ".cache" / "ordinance"
ORDINANCE_FAILURES_FILE = WORKSPACE_ROOT / ".cache" / "ordinance_failures.jsonl"

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
