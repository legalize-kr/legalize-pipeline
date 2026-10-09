"""Fetch and cache administrative rule detail XML responses."""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.etree import ElementTree

from core.counter import Counter
from core.quota_budget import ensure_headroom, record_requests

from . import cache, checkpoint, detail_failure_allowlist
from .api_client import get_admrule_detail, search_admrules
from .config import ADMRULE_TYPES, CONCURRENT_WORKERS, VALID_ADMRULE_TYPES

logger = logging.getLogger(__name__)


def _exit_if_errors(errors: int) -> None:
    if errors:
        raise SystemExit(f"admrule detail fetch failed: errors={errors}")


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
    history: bool = True,
) -> list[dict]:
    """Fetch administrative-rule history list pages for the selected kinds."""
    entries: list[dict] = []
    seen: set[str] = set()
    for knd in knd_values or [""]:
        page = 1
        expected_total = None
        kind_seen: set[str] = set()
        while True:
            result = search_admrules(
                page=page,
                display=100,
                knd=knd,
                org=org,
                date_range=date_range,
                history=history,
            )
            record_requests(1, corpus="admrules")
            total = result["totalCnt"]
            if expected_total is None:
                expected_total = total
            page_entries = result["admrules"]
            expected_size = min(100, max(0, total - (page - 1) * 100))
            if total != expected_total or len(page_entries) != expected_size:
                raise RuntimeError(f"Incomplete admrule list: knd={knd} page={page} total={total}")
            for entry in page_entries:
                serial = entry.get("행정규칙일련번호", "")
                if not serial or serial in kind_seen:
                    raise RuntimeError(f"Missing or repeated admrule serial: knd={knd} page={page}")
                kind_seen.add(serial)
                if serial not in seen and _within_date_range(entry, "발령일자", date_range):
                    seen.add(serial)
                    entries.append(entry)
            unknown = {entry.get("행정규칙종류", "") for entry in page_entries} - VALID_ADMRULE_TYPES
            if unknown:
                logger.warning("Unrecognized administrative rule types: %s", sorted(unknown))
            logger.info("admrul knd=%s page=%s: %s/%s", knd, page, min(page * 100, total), total)

            if max_entries is not None and len(entries) >= max_entries:
                return entries[:max_entries]
            if page * 100 >= total:
                break
            page += 1
    return entries


def _fetch_detail_task(serial_no: str, counter: Counter, refresh_current: bool = False) -> None:
    cached = cache.get_detail(serial_no)
    refresh = False
    if cached is not None:
        if refresh_current:
            root = ElementTree.fromstring(cached)
            refresh = root.findtext(".//현행여부", "").strip().upper() == "N"
        if not refresh:
            counter.inc("cached")
            return
    try:
        if refresh:
            get_admrule_detail(serial_no, refresh=True)
        else:
            get_admrule_detail(serial_no)
        record_requests(1, corpus="admrules")
        checkpoint.mark_detail_processed(serial_no)
        counter.inc("fetched")
    except Exception as e:
        entry = detail_failure_allowlist.accepted_entry(serial_no, e)
        if entry is not None:
            logger.warning(
                "Known upstream admrule detail failure ID=%s: %s [%s]",
                serial_no,
                e,
                entry["reason"],
            )
            counter.inc("known_failures")
            return
        logger.exception("Failed admrule detail ID=%s", serial_no)
        counter.inc("errors")


def fetch_details(entries: list[dict], workers: int = CONCURRENT_WORKERS, limit: int | None = None, *, refresh_current: bool = False) -> Counter:
    serials = []
    seen = set()
    for entry in entries:
        serial = str(entry.get("행정규칙일련번호", ""))
        if serial and serial not in seen:
            seen.add(serial)
            serials.append(serial)
    if limit is not None:
        serials = serials[:limit]

    current_serials = {entry.get("행정규칙일련번호") for entry in entries if entry.get("현행연혁구분") == "현행"}
    counter = Counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fetch_detail_task, serial, counter, refresh_current and serial in current_serials) for serial in serials]
        for future in as_completed(futures):
            future.result()
    return counter


def prune_stale_cache(entries: list[dict]) -> list[str]:
    serials = {str(entry.get("행정규칙일련번호", "")) for entry in entries if entry.get("행정규칙일련번호")}
    removed = cache.prune_details(serials)
    if removed:
        logger.info("archived withdrawn admrule detail cache files: count=%s", len(removed))
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and cache admrule history detail XML")
    parser.add_argument("--knd", action="append", choices=sorted(ADMRULE_TYPES), help="Optional 행정규칙종류 code 1..8. Repeatable; omitted means all types.")
    parser.add_argument("--org", default="", help="Optional law.go.kr org code filter")
    parser.add_argument("--limit", type=int, help="Limit detail fetches for testing")
    parser.add_argument("--workers", type=int, default=CONCURRENT_WORKERS)
    parser.add_argument("--skip-quota-check", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.skip_quota_check:
        ensure_headroom(expected_requests=args.limit or 60000, corpus="admrules")
    entries = fetch_all_current(knd_values=args.knd, org=args.org, max_entries=args.limit)
    full_run = args.limit is None and args.knd is None and not args.org
    current = fetch_all_current(history=False) if full_run else []
    if full_run and (not entries or not current):
        raise RuntimeError("Empty full administrative rule list; cache remains unchanged")
    counter = fetch_details(entries + current, workers=args.workers, limit=args.limit, refresh_current=full_run)
    cached, fetched, errors = counter.snapshot()
    known = counter.snapshot_all().get("known_failures", 0)
    logger.info(
        "admrule fetch done: cached=%s fetched=%s known_failures=%s errors=%s",
        cached,
        fetched,
        known,
        errors,
    )
    if known:
        logger.warning("Known admrule detail failures skipped: known_failures=%s", known)
    _exit_if_errors(errors)
    if full_run:
        from .snapshot import write_current_snapshot

        write_current_snapshot(current, history_entries=entries)
        prune_stale_cache(entries + current)


if __name__ == "__main__":
    main()
