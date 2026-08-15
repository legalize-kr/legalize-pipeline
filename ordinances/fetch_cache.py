"""Fetch and cache ordinance detail XML responses."""

import argparse
import logging
import math
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import requests

from core.counter import Counter
from core.quota_budget import ensure_headroom, record_requests

from . import cache, checkpoint, detail_failure_allowlist
from .api_client import NoResultError, get_ordinance_detail, search_ordinances
from .config import API_TYPES, CONCURRENT_WORKERS
from .failures import append_failure

logger = logging.getLogger(__name__)


class _QuotaBatch:
    """Persist actual detail request attempts in bounded, interruption-safe batches."""

    def __init__(self, flush_every: int = 100):
        self._flush_every = flush_every
        self._pending = 0
        self._lock = threading.Lock()

    def record_attempt(self) -> None:
        with self._lock:
            self._pending += 1
            if self._pending >= self._flush_every:
                record_requests(self._pending, corpus="ordinances")
                self._pending = 0

    def flush(self) -> None:
        with self._lock:
            if self._pending:
                record_requests(self._pending, corpus="ordinances")
                self._pending = 0


def _exit_if_errors(errors: int) -> None:
    if errors:
        raise SystemExit(f"ordinance detail fetch failed: errors={errors}")


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
    history: bool = False,
    list_workers: int = 1,
) -> list[dict]:
    """Fetch ordinance list pages and filter selected types client-side.

    The law.go.kr ordinance ``knd`` parameter has shown inconsistent behavior
    during probes. Fetching unfiltered pages once and classifying by
    ``자치법규종류`` avoids duplicate detail fetches and matches the plan's
    fallback policy.
    """
    entries: list[dict] = []
    wanted = set(ordinance_types or API_TYPES)

    def fetch_page(page: int) -> dict:
        return search_ordinances(
            page=page,
            display=display,
            org=org,
            sborg=sborg,
            date_range=date_range,
            nw="2" if history else "1",
        )

    def append_page(result: dict, page: int) -> None:
        entries.extend(
            entry
            for entry in result["ordinances"]
            if entry.get("자치법규종류", "") in wanted and _within_date_range(entry, "공포일자", date_range)
        )
        logger.info(
            "ordin types=%s org=%s sborg=%s page=%s: %s/%s",
            ",".join(sorted(wanted)),
            org or "*",
            sborg or "*",
            page,
            min(page * display, total),
            total,
        )

    first = fetch_page(1)
    record_requests(1, corpus="ordinances")
    total = first["totalCnt"]
    append_page(first, 1)
    if max_entries is not None and len(entries) >= max_entries:
        return entries[:max_entries]

    total_pages = math.ceil(total / display)
    if total_pages <= 1:
        return entries

    if list_workers > 1 and max_entries is None:
        pages = range(2, total_pages + 1)
        with ThreadPoolExecutor(max_workers=list_workers) as pool:
            for page, result in zip(pages, pool.map(fetch_page, pages), strict=True):
                append_page(result, page)
        record_requests(total_pages - 1, corpus="ordinances")
        return entries

    for page in range(2, total_pages + 1):
        result = fetch_page(page)
        record_requests(1, corpus="ordinances")
        append_page(result, page)
        if max_entries is not None and len(entries) >= max_entries:
            return entries[:max_entries]
    return entries


def fetch_history_for_entries(
    entries: list[dict],
    ordinance_types: list[str] | None = None,
    *,
    display: int = 100,
) -> list[dict]:
    """Fetch full ``nw=2`` history for the identities represented by entries."""
    wanted = set(ordinance_types or API_TYPES)
    history_entries: list[dict] = []
    seen_queries: set[tuple[str, str]] = set()
    seen_serials: set[str] = set()
    for entry in entries:
        ordinance_id = str(entry.get("자치법규ID", ""))
        query = str(entry.get("자치법규명", ""))
        if not ordinance_id or not query:
            continue
        query_key = (ordinance_id, query)
        if query_key in seen_queries:
            continue
        seen_queries.add(query_key)

        # lawSearch.do returns smart quotes as undefined HTML entities in its
        # XML response and does not match the quoted title. The ordinance ID
        # filter below still limits results to the requested identity.
        search_query = query.translate(str.maketrans("", "", "‘’“”"))

        page = 1
        while True:
            result = search_ordinances(query=search_query, page=page, display=display, nw="2")
            record_requests(1, corpus="ordinances")
            for candidate in result["ordinances"]:
                serial = str(candidate.get("자치법규일련번호", ""))
                if (
                    candidate.get("자치법규ID") == ordinance_id
                    and candidate.get("자치법규종류", "") in wanted
                    and serial
                    and serial not in seen_serials
                ):
                    seen_serials.add(serial)
                    history_entries.append(candidate)
            total = result["totalCnt"]
            logger.info("ordin history ID=%s page=%s: %s/%s", ordinance_id, page, min(page * display, total), total)
            if page * display >= total:
                break
            page += 1
    return history_entries


def _fetch_detail_task(
    ordinance_id: str,
    ordinance_mst: str,
    counter: Counter,
    quota: _QuotaBatch,
) -> None:
    cache_key = str(ordinance_mst or ordinance_id)
    if cache.get_detail(cache_key, historical=bool(ordinance_mst)) is not None:
        counter.inc("cached")
        return
    try:
        get_ordinance_detail(
            ordinance_id,
            mst=ordinance_mst,
            on_request_attempt=quota.record_attempt,
        )
        checkpoint.mark_detail_processed(cache_key)
        counter.inc("fetched")
    except NoResultError:
        if ordinance_mst:
            cache.add_no_result_serial(ordinance_mst)
            counter.inc("no_result")
            return
        logger.exception("No ordinance detail ID=%s", ordinance_id)
        append_failure({"자치법규ID": ordinance_id, "자치법규일련번호": "", "reason": "detail_fetch_failed"})
        counter.inc("errors")
    except Exception as exc:
        if (
            isinstance(exc, requests.HTTPError)
            and ordinance_mst
            and exc.response is not None
            and exc.response.status_code == 404
        ):
            cache.add_no_result_serial(ordinance_mst)
            counter.inc("no_result")
            return
        entry = detail_failure_allowlist.accepted_entry(ordinance_mst, exc)
        if entry is not None:
            logger.warning(
                "Known upstream ordinance detail failure MST=%s: %s [%s]",
                ordinance_mst,
                exc,
                entry["reason"],
            )
            counter.inc("known_failures")
            return
        logger.exception("Failed ordinance detail ID=%s MST=%s", ordinance_id, ordinance_mst)
        append_failure({"자치법규ID": ordinance_id, "자치법규일련번호": ordinance_mst, "reason": "detail_fetch_failed"})
        counter.inc("errors")


def fetch_details(entries: list[dict], workers: int = CONCURRENT_WORKERS, limit: int | None = None) -> Counter:
    ids = []
    seen = set()
    for entry in entries:
        ordinance_id = str(entry.get("자치법규ID", ""))
        ordinance_mst = str(entry.get("자치법규일련번호", ""))
        cache_key = ordinance_mst or ordinance_id
        if ordinance_id and cache_key and cache_key not in seen:
            seen.add(cache_key)
            ids.append((ordinance_id, ordinance_mst))
    if limit is not None:
        ids = ids[:limit]

    counter = Counter()
    quota = _QuotaBatch()
    completed = 0
    pool = ThreadPoolExecutor(max_workers=workers)
    source = iter(ids)
    pending = set()

    def submit_next() -> bool:
        try:
            ordinance_id, ordinance_mst = next(source)
        except StopIteration:
            return False
        pending.add(pool.submit(_fetch_detail_task, ordinance_id, ordinance_mst, counter, quota))
        return True

    for _ in range(min(workers, len(ids))):
        submit_next()
    try:
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                pending.remove(future)
                future.result()
                completed += 1
                if completed % 500 == 0:
                    logger.info("ordinance detail progress: completed=%s/%s stats=%s", completed, len(ids), counter.snapshot_all())
                submit_next()
    except BaseException:
        for future in pending:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        pool.shutdown()
    finally:
        quota.flush()
    return counter


def missing_detail_entries(entries: list[dict]) -> list[dict]:
    missing = []
    no_result_serials = cache.load_no_result_serials()
    for entry in entries:
        ordinance_id = str(entry.get("자치법규ID", ""))
        ordinance_mst = str(entry.get("자치법규일련번호", ""))
        cache_key = ordinance_mst or ordinance_id
        if ordinance_mst and detail_failure_allowlist.is_listed(ordinance_mst):
            continue
        if ordinance_mst in no_result_serials:
            continue
        if cache_key and cache.get_detail(cache_key, historical=bool(ordinance_mst)) is None:
            missing.append(entry)
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and cache ordinance detail XML")
    parser.add_argument("--type", dest="types", action="append", choices=API_TYPES, help="자치법규종류. Repeatable.")
    parser.add_argument("--org", default="", help="Optional law.go.kr 광역 org code")
    parser.add_argument("--sborg", default="", help="Optional law.go.kr 기초 sborg code")
    parser.add_argument("--display", type=int, default=100)
    parser.add_argument("--limit", type=int, help="Limit detail fetches for testing/probe runs")
    parser.add_argument(
        "--max-new-details",
        type=int,
        help="Fetch at most this many currently missing details (safe resumable backfill batch)",
    )
    parser.add_argument("--workers", type=int, default=CONCURRENT_WORKERS)
    parser.add_argument("--history", action="store_true", help="Fetch nw=2 ordinance history list instead of current list")
    parser.add_argument("--skip-list", action="store_true", help="Reuse the persisted full history list")
    parser.add_argument("--skip-quota-check", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.skip_quota_check:
        ensure_headroom(expected_requests=10000 if args.history else args.limit or 200000, corpus="ordinances")
    if args.history and args.skip_list:
        entries = cache.get_history_entries()
        if not entries:
            raise SystemExit("persisted ordinance history list is missing or empty")
        logger.info("reusing persisted ordinance history list: entries=%s", len(entries))
    else:
        entries = fetch_all_current(
            args.types,
            org=args.org,
            sborg=args.sborg,
            display=args.display,
            max_entries=args.limit,
            history=args.history,
            list_workers=args.workers if args.history else 1,
        )
        if args.history and args.limit is None and not args.org and not args.sborg and not args.types:
            cache.put_history_entries(entries)
            logger.info("persisted ordinance history list: entries=%s", len(entries))
    if args.history:
        seed_stats = cache.seed_history_from_current()
        logger.info("ordinance history seed done: %s", seed_stats)
        if seed_stats["errors"]:
            raise SystemExit(f"ordinance history seed failed: errors={seed_stats['errors']}")
    fetch_entries = missing_detail_entries(entries)
    missing_total = len(fetch_entries)
    if args.max_new_details is not None:
        fetch_entries = fetch_entries[:args.max_new_details]
    if not args.skip_quota_check:
        ensure_headroom(expected_requests=len(fetch_entries), corpus="ordinances")
    logger.info(
        "ordinance detail backfill: missing_total=%s selected=%s",
        missing_total,
        len(fetch_entries),
    )
    counter = fetch_details(fetch_entries, workers=args.workers, limit=args.limit)
    cached, fetched, errors = counter.snapshot()
    known = counter.snapshot_all().get("known_failures", 0)
    no_result = counter.snapshot_all().get("no_result", 0)
    if errors:
        recovery_entries = missing_detail_entries(fetch_entries)
        if recovery_entries:
            logger.warning(
                "retrying ordinance detail recovery pass: unresolved=%s",
                len(recovery_entries),
            )
            if not args.skip_quota_check:
                ensure_headroom(expected_requests=len(recovery_entries), corpus="ordinances")
            recovery = fetch_details(recovery_entries, workers=args.workers, limit=args.limit)
            recovery_stats = recovery.snapshot_all()
            logger.info("ordinance detail recovery done: %s", recovery_stats)
            cached += recovery_stats["cached"]
            fetched += recovery_stats["fetched"]
            errors = recovery_stats["errors"]
            known += recovery_stats.get("known_failures", 0)
            no_result += recovery_stats.get("no_result", 0)
    logger.info(
        "ordinance fetch done: cached=%s fetched=%s no_result=%s known_failures=%s errors=%s",
        cached,
        fetched,
        no_result,
        known,
        errors,
    )
    _exit_if_errors(errors)


if __name__ == "__main__":
    main()
