"""Configuration for the administrative rules pipeline."""

from core.config import (  # noqa: F401 - re-exported for package modules
    ADMRULE_KR_REPO,
    BACKOFF_BASE_SECONDS,
    BOT_AUTHOR,
    CACHE_ROOT,
    CONCURRENT_WORKERS,
    LAW_API_BASE,
    LAW_API_KEY,
    MAX_RETRIES,
    PROJECT_ROOT,
    REQUEST_DELAY_SECONDS,
    WORKSPACE_ROOT,
)

ADMRULE_REPO = ADMRULE_KR_REPO
ADMRULE_CACHE_DIR = CACHE_ROOT / "admrule"

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

VALID_ADMRULE_TYPES = frozenset(ADMRULE_TYPES.values()) | {
    "가족관계등록예규", "계약예규", "규격", "규정", "규칙", "내규", "대통령공고",
    "등기예규", "매뉴얼", "세칙", "재판예규", "행정예규", "회계예규",
}
BODY_SOURCES = frozenset({"api-text", "parsed-from-hwp", "parsing-failed"})
BINARY_SUFFIXES = frozenset({".hwp", ".pdf", ".jpg", ".jpeg", ".png", ".gif"})
