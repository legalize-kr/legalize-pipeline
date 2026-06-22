"""Small pre-flight guard for shared law.go.kr API usage.

The upstream service does not publish a hard daily quota for every key. This
module therefore records local request counts as an operational guardrail, not
as an authoritative upstream quota.
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

from .atomic_io import atomic_write_text
from .config import CACHE_ROOT


def _parse_budget(value: str | None) -> float:
    """Parse a daily budget, accepting ``inf``/``unlimited`` to disable the guard."""
    text = str(value if value is not None else "100000").strip().lower()
    if text in {"inf", "infinity", "unlimited"}:
        return math.inf
    return int(text)


DEFAULT_DAILY_BUDGET = _parse_budget(os.environ.get("LAW_API_DAILY_BUDGET"))
STATE_FILE = CACHE_ROOT / "law_api_quota_budget.json"


def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load(path: Path = STATE_FILE) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def record_requests(count: int, *, corpus: str, path: Path = STATE_FILE) -> None:
    data = load(path)
    day = today_key()
    data.setdefault(day, {})
    data[day][corpus] = int(data[day].get(corpus, 0)) + int(count)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def used_today(path: Path = STATE_FILE) -> int:
    return sum(int(value) for value in load(path).get(today_key(), {}).values())


def ensure_headroom(
    *,
    expected_requests: int,
    corpus: str,
    daily_budget: float = DEFAULT_DAILY_BUDGET,
    path: Path = STATE_FILE,
    min_headroom_ratio: float = 0.30,
) -> None:
    if math.isinf(daily_budget):
        return
    used = used_today(path)
    projected = used + int(expected_requests)
    limit = int(daily_budget * (1 - min_headroom_ratio))
    if projected > limit:
        raise RuntimeError(
            f"{corpus} fetch would exceed quota guardrail: "
            f"used={used} expected={expected_requests} budget={daily_budget}"
        )
