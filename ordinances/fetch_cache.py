"""Fetch and cache ordinance detail XML responses."""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.counter import Counter
from core.quota_budget import ensure_headroom, record_requests

from . import cache, checkpoint
from .api_client import get_ordinance_detail, search_ordinances
from .config import API_TYPES, CONCURRENT_WORKERS
from .failures import append_failure

logger = logging.getLogger(__name__)


def _compact_date(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def _within_date_range(entry: dict, field: str, date_range: str) -> bool:
    if not date_range:
        return True
    try:
        start, end = date_range.split("~", 1)
    except ValueError:
        return True
    value = _compact_date(entry.get(field, ""))
    return bool(value) and start <= value <= end


def fetch_all_current(
    ordinance_types: list[str] | None = None,
    *,
    org: str = "",
    sborg: str = "",
    display: int = 100,
    max_entries: int | None = None,
    date_range: str = "",
) -> list[dict]:
    """Fetch current ordinance list pages and filter selected types client-side.

    The law.go.kr ordinance ``knd`` parameter has shown inconsistent behavior
    during probes. Fetching unfiltered pages once and classifying by
    ``자치법규종류`` avoids duplicate detail fetches and matches the plan's
    fallback policy.
    """
    entries: list[dict] = []
    wanted = set(ordinance_types or API_TYPES)
    page = 1
    while True:
        result = search_ordinances(page=page, display=display, org=org, sborg=sborg, date_range=date_range)
        record_requests(1, corpus="ordinances")
        entries.extend(
            entry
            for entry in result["ordinances"]
            if entry.get("자치법규종류", "") in wanted and _within_date_range(entry, "공포일자", date_range)
        )
        total = result["totalCnt"]
        logger.info(
            "ordin types=%s org=%s sborg=%s page=%s: %s/%s",
            ",".join(sorted(wanted)),
            org or "*",
            sborg or "*",
            page,
            min(page * display, total),
            total,
        )
        if max_entries is not None and len(entries) >= max_entries:
            return entries[:max_entries]
        if page * display >= total:
            break
        page += 1
    return entries


def _fetch_detail_task(ordinance_id: str, counter: Counter) -> None:
    if cache.get_detail(ordinance_id) is not None:
        counter.inc("cached")
        return
    try:
        get_ordinance_detail(ordinance_id)
        record_requests(1, corpus="ordinances")
        checkpoint.mark_detail_processed(ordinance_id)
        counter.inc("fetched")
    except Exception:
        logger.exception("Failed ordinance detail ID=%s", ordinance_id)
        append_failure({"자치법규ID": ordinance_id, "reason": "detail_fetch_failed"})
        counter.inc("errors")


def fetch_details(entries: list[dict], workers: int = CONCURRENT_WORKERS, limit: int | None = None) -> Counter:
    ids = []
    seen = set()
    for entry in entries:
        ordinance_id = str(entry.get("자치법규ID", ""))
        if ordinance_id and ordinance_id not in seen:
            seen.add(ordinance_id)
            ids.append(ordinance_id)
    if limit is not None:
        ids = ids[:limit]

    counter = Counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fetch_detail_task, ordinance_id, counter) for ordinance_id in ids]
        for future in as_completed(futures):
            future.result()
    return counter


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and cache ordinance detail XML")
    parser.add_argument("--type", dest="types", action="append", choices=API_TYPES, help="자치법규종류. Repeatable.")
    parser.add_argument("--org", default="", help="Optional law.go.kr 광역 org code")
    parser.add_argument("--sborg", default="", help="Optional law.go.kr 기초 sborg code")
    parser.add_argument("--display", type=int, default=100)
    parser.add_argument("--limit", type=int, help="Limit detail fetches for testing/probe runs")
    parser.add_argument("--workers", type=int, default=CONCURRENT_WORKERS)
    parser.add_argument("--skip-quota-check", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.skip_quota_check:
        ensure_headroom(expected_requests=args.limit or 200000, corpus="ordinances")
    entries = fetch_all_current(args.types, org=args.org, sborg=args.sborg, display=args.display, max_entries=args.limit)
    counter = fetch_details(entries, workers=args.workers, limit=args.limit)
    logger.info("ordinance fetch done: cached=%s fetched=%s errors=%s", *counter.snapshot())


if __name__ == "__main__":
    main()
