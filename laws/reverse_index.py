"""Map law name -> canonical MST from search API candidates."""

import logging

logger = logging.getLogger(__name__)


def resolve_canonical_mst(name: str, candidates: list[dict]) -> str | None:
    """Pick the canonical MST for a law name from search API candidates.

    Preference order:
    1. Exact name match AND 법령구분 == '법률' (not 시행령/시행규칙).
       If multiple, latest 공포일자 wins.
    2. Exact name match only, latest 공포일자 wins.
    3. None — caller routes to search_misses.

    Logs a WARNING with event="name_collision" when >1 primary candidate remains.
    """
    if not candidates:
        return None
    exact = [c for c in candidates if c.get("법령명한글", "") == name]
    if not exact:
        return None

    # Tier 1: 법률 matches
    primary = [c for c in exact if c.get("법령구분", "") == "법률"]
    if len(primary) > 1:
        logger.warning("name_collision", extra={
            "law_name": name, "count": len(primary),
            "msts": [c.get("법령일련번호", "") for c in primary],
        })
    pool = primary or exact

    # Latest 공포일자 wins (descending sort by string, YYYYMMDD compares correctly)
    pool.sort(key=lambda c: c.get("공포일자", ""), reverse=True)
    return pool[0].get("법령일련번호") or None
