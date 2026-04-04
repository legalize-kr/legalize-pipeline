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
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import cache
from .api_client import get_law_detail, get_law_history, search_laws
from .config import CONCURRENT_WORKERS
from core.counter import Counter

logger = logging.getLogger(__name__)


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


def _fetch_history_task(name: str, counter: Counter, all_msts: list, msts_lock: threading.Lock) -> None:
    """Fetch history for a single law name."""
    try:
        already_cached = cache.get_history(name) is not None
        entries = get_law_history(name)
        new_msts = [e.get("법령일련번호", "") for e in entries if e.get("법령일련번호")]
        with msts_lock:
            all_msts.extend(new_msts)
        if already_cached:
            counter.inc("cached")
        else:
            counter.inc("fetched")
    except Exception as e:
        logger.error(f"Failed history for {name}: {e}")
        counter.inc("errors")


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
        "--workers",
        type=int,
        default=CONCURRENT_WORKERS,
        help=f"Number of concurrent workers (default: {CONCURRENT_WORKERS})",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

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
            pool.submit(_fetch_history_task, name, history_counter, all_msts, msts_lock): name
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
