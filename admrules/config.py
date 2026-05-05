"""Configuration for the administrative rules pipeline."""

from core.config import (  # noqa: F401 - re-exported for package modules
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

ADMRULE_REPO = WORKSPACE_ROOT / "admrule-kr"
ADMRULE_CACHE_DIR = WORKSPACE_ROOT / ".cache" / "admrule"

ADMRULE_TYPES = {
    "1": "훈령",
    "2": "예규",
    "3": "고시",
    "4": "공고",
    "5": "지침",
    "6": "기타",
    "7": "대통령훈령",
    "8": "국무총리훈령",
}

VALID_ADMRULE_TYPES = frozenset(ADMRULE_TYPES.values())
BODY_SOURCES = frozenset({"api-text", "parsed-from-hwp", "parsing-failed"})
BINARY_SUFFIXES = frozenset({".hwp", ".pdf", ".jpg", ".jpeg", ".png", ".gif"})
