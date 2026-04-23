"""Fetch and cache all raw law detail API responses and amendment histories.

Fetches the current law list via search API, then for each unique law name
fetches the full amendment history (caching it), collects all historical MSTs,
and caches the detail XML for each one.

Uses ThreadPoolExecutor for concurrent fetching with thread-safe throttling.

Usage (from legalize-pipeline root):
    python -m laws.fetch_cache                   # Fetch history + all historical details
    python -m laws.fetch_cache --skip-history    # Only cache current detail (old behavior)
    python -m laws.fetch_cache --limit 10        # Limit for testing
    python -m laws.fetch_cache --workers 3       # Override concurrent workers (default: 5)
"""

import argparse
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import cache
from .api_client import get_law_detail, get_law_history, search_laws
from .config import CONCURRENT_WORKERS
from .history_allowlist import filter_and_check
from core.counter import Counter

logger = logging.getLogger(__name__)


def _assert_no_empty_history_cache() -> None:
    """Raise if any history cache file is empty [] or malformed JSON.

    Turns silent cache poisoning into a loud end-of-run crash.
    Collects all offenders in a single pass for full visibility.
    """
    from .history_allowlist import filter_and_check
    from datetime import date

    empty: list[str] = []
    malformed: list[tuple[str, str]] = []
    all_cached = cache.list_cached_history_names()
    for name in all_cached:
        path = cache.history_path_for(name)
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            malformed.append((str(path), str(e)))
            continue
        if data == []:
            empty.append(name)

    unallowed, expired, orphaned = filter_and_check(
        empty_stems=empty,
        all_cached_stems=all_cached,
        today=date.today(),
    )

    # Informational: orphans do not fail the invariant.
    for o in orphaned:
        logger.warning(
            f"::notice::allowlist_orphan stem={o['stem']} "
            f"original_name={o['original_name']} "
            f"tracking_issue={o['tracking_issue']} — "
            f"cache file no longer present; candidate for removal from allowlist"
        )

    if unallowed or expired or malformed:
        # R1: enrich with original_name and long-name recovery hint.
        unallowed_render = [
            f"{u['stem']} (hint: {u['original_name_hint']})" if u['original_name_hint']
            else u['stem']
            for u in unallowed
        ]
        expired_render = [
            f"{e['stem']} [{e['original_name']}] tracking={e['tracking_issue']} expired={e['expires_on']}"
            for e in expired
        ]
        raise RuntimeError(
            f"History cache invariant violated. "
            f"Unallowlisted empty ({len(unallowed)}): {unallowed_render}. "
            f"Expired allowlist entries ({len(expired)}): {expired_render}. "
            f"Malformed ({len(malformed)}): {malformed}. "
            f"This indicates pagination regression, cache corruption, or a stale allowlist. "
            f"For stems matching '_<16hex>' suffix pattern: the law name exceeded 200 bytes "
            f"and was hash-truncated by cache._safe_filename; cross-reference original_name "
            f"via laws.api_client.search_laws."
        )


def fetch_all_msts() -> list[dict]:
    """Fetch all law entries from search API (all pages)."""
    all_laws = []
    page = 1

    while True:
        result = search_laws(query="", page=page, display=100)
        all_laws.extend(result["laws"])
        total = result["totalCnt"]
        logger.info(f"Search page {page}: {len(all_laws)}/{total}")

        if page * 100 >= total:
            break
        page += 1

    return all_laws


def _fetch_detail_task(mst: str, name: str, counter: Counter) -> None:
    """Fetch a single detail, skipping if cached."""
    if cache.get_detail(mst) is not None:
        counter.inc("cached")
        return
    try:
        get_law_detail(mst)
        counter.inc("fetched")
    except Exception as e:
        logger.error(f"Failed MST {mst} ({name}): {e}")
        counter.inc("errors")


def _fetch_history_task(
    name: str,
    counter: Counter,
    all_msts: list,
    msts_lock: threading.Lock,
    refresh: bool = False,
) -> None:
    """Fetch history for a single law name."""
    try:
        already_cached = bool(cache.get_history(name))
        entries = get_law_history(name, refresh=refresh)
        new_msts = [e.get("법령일련번호", "") for e in entries if e.get("법령일련번호")]
        with msts_lock:
            all_msts.extend(new_msts)
        if already_cached and not refresh:
            counter.inc("cached")
        else:
            counter.inc("fetched")
    except Exception as e:
        logger.error(f"Failed history for {name}: {e}")
        counter.inc("errors")


def _assert_no_empty_history_cache() -> None:
    """Raise RuntimeError if any history cache entry is empty or malformed JSON.

    Empty entries allowlisted in known_empty_history.yaml are exempted.
    Raises with a message listing unallowlisted empty stems and malformed paths.
    """
    history_dir = cache.CACHE_DIR / "history"
    if not history_dir.exists():
        return

    all_stems = cache.list_cached_history_names()
    empty_stems: list[str] = []
    malformed_paths: list[str] = []

    for stem in all_stems:
        path = history_dir / f"{stem}.json"
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
            if not content:
                empty_stems.append(stem)
        except (json.JSONDecodeError, OSError):
            malformed_paths.append(str(path))

    unallowlisted, expired, _ = filter_and_check(empty_stems, all_stems)

    problems: list[str] = []
    if unallowlisted:
        parts = []
        for e in unallowlisted:
            piece = e["stem"]
            if e.get("original_name_hint"):
                piece += f" [hint: {e['original_name_hint']}]"
            parts.append(piece)
        problems.append(f"Unallowlisted empty ({len(unallowlisted)}): {parts}")
    if expired:
        parts = []
        for e in expired:
            parts.append(
                f"{e['stem']} (original_name={e['original_name']!r}, "
                f"tracking_issue={e['tracking_issue']}, expires_on={e['expires_on']})"
            )
        problems.append(f"Allowlist expired ({len(expired)}): {parts}")
    if malformed_paths:
        problems.append(f"Malformed ({len(malformed_paths)}): {malformed_paths}")

    if problems:
        raise RuntimeError("History cache invariant violated: " + "; ".join(problems))


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and cache law detail responses and amendment histories"
    )
    parser.add_argument("--limit", type=int, help="Limit number of laws to fetch")
    parser.add_argument(
        "--skip-history",
        action="store_true",
        help="Skip history fetching; only cache current detail (old behavior)",
    )
    parser.add_argument(
        "--refresh-history",
        action="store_true",
        help=(
            "Bypass local history cache and refetch from lsHistory. Use when the "
            "upstream may have new entries (e.g. 타법개정) that the cached history "
            "list does not reflect."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=CONCURRENT_WORKERS,
        help=f"Number of concurrent workers (default: {CONCURRENT_WORKERS})",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # R7: pre-flight allowlist schema validation. Fail in <1s rather than after a 30-min crawl.
    from .history_allowlist import load_allowlist
    try:
        load_allowlist()
    except Exception as e:
        logger.error(f"Allowlist pre-flight failed: {e}")
        raise

    logger.info("Fetching law list...")
    all_laws = fetch_all_msts()
    logger.info(f"Total laws found: {len(all_laws)}")

    workers = args.workers

    if args.skip_history:
        # Old behavior: deduplicate by MST, fetch current detail only
        seen: set[str] = set()
        unique: list[dict] = []
        for law in all_laws:
            mst = law["법령일련번호"]
            if mst and mst not in seen:
                seen.add(mst)
                unique.append(law)

        if args.limit:
            unique = unique[:args.limit]

        logger.info(f"Fetching detail for {len(unique)} unique laws (skip-history, workers={workers})...")

        counter = Counter()
        done = 0
        total = len(unique)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_fetch_detail_task, law["법령일련번호"], law.get("법령명한글", ""), counter): law
                for law in unique
            }
            for future in as_completed(futures):
                future.result()  # propagate unexpected exceptions
                done += 1
                if done % 100 == 0:
                    c, f, e = counter.snapshot()
                    logger.info(f"Progress: {done}/{total} (cached={c}, fetched={f}, errors={e})")

        c, f, e = counter.snapshot()
        logger.info(f"Detail fetch done: cached={c}, fetched={f}, errors={e}")
        return

    # Deduplicate by 법령명한글
    seen_names: set[str] = set()
    unique_names: list[str] = []
    for law in all_laws:
        name = law.get("법령명한글", "")
        if name and name not in seen_names:
            seen_names.add(name)
            unique_names.append(name)

    if args.limit:
        unique_names = unique_names[:args.limit]

    # Step 1: Fetch history concurrently
    logger.info(f"Fetching history for {len(unique_names)} unique law names (workers={workers})...")

    history_counter = Counter()
    all_msts: list[str] = []
    msts_lock = threading.Lock()
    done = 0
    total = len(unique_names)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _fetch_history_task,
                name,
                history_counter,
                all_msts,
                msts_lock,
                args.refresh_history,
            ): name
            for name in unique_names
        }
        for future in as_completed(futures):
            future.result()
            done += 1
            if done % 100 == 0:
                c, f, e = history_counter.snapshot()
                logger.info(f"History progress: {done}/{total} (msts_collected={len(all_msts)}, errors={e})")

    c, f, e = history_counter.snapshot()
    logger.info(f"History fetch done: cached={c}, fetched={f}, errors={e}, total_msts={len(all_msts)}")

    _assert_no_empty_history_cache()

    # Step 2: Fetch detail for each MST found in history
    mst_list = sorted(set(all_msts))
    logger.info(f"Fetching detail for {len(mst_list)} historical MSTs (workers={workers})...")

    detail_counter = Counter()
    done = 0
    total = len(mst_list)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_detail_task, mst, "", detail_counter): mst
            for mst in mst_list
        }
        for future in as_completed(futures):
            future.result()
            done += 1
            if done % 100 == 0:
                c, f, e = detail_counter.snapshot()
                logger.info(f"Progress: {done}/{total} (cached={c}, fetched={f}, errors={e})")

    c, f, e = detail_counter.snapshot()
    logger.info(f"Detail fetch done: cached={c}, fetched={f}, errors={e}")


if __name__ == "__main__":
    main()
