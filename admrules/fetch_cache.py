"""Fetch and cache administrative rule detail XML responses."""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.counter import Counter
from core.quota_budget import ensure_headroom, record_requests

from . import cache, checkpoint
from .api_client import get_admrule_detail, search_admrules
from .config import ADMRULE_TYPES, CONCURRENT_WORKERS

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
    knd_values: list[str] | None = None,
    org: str = "",
    max_entries: int | None = None,
    date_range: str = "",
) -> list[dict]:
    """Fetch current administrative rule list pages for the selected kinds."""
    entries: list[dict] = []
    for knd in knd_values or list(ADMRULE_TYPES):
        page = 1
        while True:
            result = search_admrules(page=page, display=100, knd=knd, org=org, date_range=date_range)
            record_requests(1, corpus="admrules")
            entries.extend(entry for entry in result["admrules"] if _within_date_range(entry, "발령일자", date_range))
            total = result["totalCnt"]
            logger.info("admrul knd=%s page=%s: %s/%s", knd, page, min(page * 100, total), total)

            if max_entries is not None and len(entries) >= max_entries:
                return entries[:max_entries]
            if page * 100 >= total:
                break
            page += 1
    return entries


def _fetch_detail_task(serial_no: str, counter: Counter) -> None:
    if cache.get_detail(serial_no) is not None:
        counter.inc("cached")
        return
    try:
        get_admrule_detail(serial_no)
        record_requests(1, corpus="admrules")
        checkpoint.mark_detail_processed(serial_no)
        counter.inc("fetched")
    except Exception:
        logger.exception("Failed admrule detail ID=%s", serial_no)
        counter.inc("errors")


def fetch_details(entries: list[dict], workers: int = CONCURRENT_WORKERS, limit: int | None = None) -> Counter:
    serials = []
    seen = set()
    for entry in entries:
        serial = str(entry.get("행정규칙일련번호", ""))
        if serial and serial not in seen:
            seen.add(serial)
            serials.append(serial)
    if limit is not None:
        serials = serials[:limit]

    counter = Counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fetch_detail_task, serial, counter) for serial in serials]
        for future in as_completed(futures):
            future.result()
    return counter


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and cache admrule detail XML")
    parser.add_argument("--knd", action="append", choices=sorted(ADMRULE_TYPES), help="행정규칙종류 code 1..6. Repeatable.")
    parser.add_argument("--org", default="", help="Optional law.go.kr org code filter")
    parser.add_argument("--limit", type=int, help="Limit detail fetches for testing")
    parser.add_argument("--workers", type=int, default=CONCURRENT_WORKERS)
    parser.add_argument("--skip-quota-check", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.skip_quota_check:
        ensure_headroom(expected_requests=args.limit or 20000, corpus="admrules")
    entries = fetch_all_current(knd_values=args.knd, org=args.org, max_entries=args.limit)
    counter = fetch_details(entries, workers=args.workers, limit=args.limit)
    logger.info("admrule fetch done: cached=%s fetched=%s errors=%s", *counter.snapshot())


if __name__ == "__main__":
    main()
