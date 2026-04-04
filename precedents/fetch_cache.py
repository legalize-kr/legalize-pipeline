"""Fetch and cache all raw precedent detail API responses.

Pages through the precedent search API to collect all 판례일련번호 values,
then fetches and caches the detail XML for each one concurrently.

Usage (from legalize-pipeline root):
    python -m precedents.fetch_cache                  # Fetch list + all details
    python -m precedents.fetch_cache --skip-list      # Load IDs from all_ids.txt, skip pagination
    python -m precedents.fetch_cache --limit 10       # Limit for testing
    python -m precedents.fetch_cache --workers 3      # Override concurrent workers (default: 5)
"""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.counter import Counter

from . import cache
from .api_client import get_precedent_detail, search_precedents
from .config import CONCURRENT_WORKERS, PREC_CACHE_DIR

logger = logging.getLogger(__name__)

_ALL_IDS_PATH = PREC_CACHE_DIR / "all_ids.txt"


def fetch_all_ids() -> list[str]:
    """Page through search API to collect all 판례일련번호 values."""
    all_ids: list[str] = []
    seen: set[str] = set()
    page = 1

    while True:
        result = search_precedents(query="", page=page, display=100, sort="dasc")
        total = result["totalCnt"]

        for prec in result["precedents"]:
            prec_id = prec.get("판례일련번호", "")
            if prec_id and prec_id not in seen:
                seen.add(prec_id)
                all_ids.append(prec_id)

        logger.info(f"Search page {page}: {len(all_ids)}/{total}")

        if page * 100 >= total or not result["precedents"]:
            break
        page += 1

    # Save for future --skip-list runs
    PREC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _ALL_IDS_PATH.write_text("\n".join(all_ids), encoding="utf-8")
    logger.info(f"Saved {len(all_ids)} IDs to {_ALL_IDS_PATH}")

    return all_ids


def _fetch_detail_task(prec_id: str, counter: Counter) -> None:
    """Fetch a single precedent detail, skipping if already cached."""
    if cache.get_detail(prec_id) is not None:
        counter.inc("cached")
        return
    try:
        get_precedent_detail(prec_id)
        counter.inc("fetched")
    except Exception as e:
        logger.error(f"Failed prec_id {prec_id}: {e}")
        counter.inc("errors")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and cache precedent detail responses"
    )
    parser.add_argument("--limit", type=int, help="Limit number of precedents to fetch")
    parser.add_argument(
        "--skip-list",
        action="store_true",
        help="Skip list pagination; load IDs from all_ids.txt (for resuming)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=CONCURRENT_WORKERS,
        help=f"Number of concurrent workers (default: {CONCURRENT_WORKERS})",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.skip_list:
        if not _ALL_IDS_PATH.exists():
            logger.error(f"all_ids.txt not found at {_ALL_IDS_PATH}. Run without --skip-list first.")
            raise SystemExit(1)
        all_ids = [
            line.strip()
            for line in _ALL_IDS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        logger.info(f"Loaded {len(all_ids)} IDs from {_ALL_IDS_PATH}")
    else:
        logger.info("Fetching precedent ID list...")
        all_ids = fetch_all_ids()
        logger.info(f"Total precedents found: {len(all_ids)}")

    if args.limit:
        all_ids = all_ids[:args.limit]

    workers = args.workers
    logger.info(f"Fetching detail for {len(all_ids)} precedents (workers={workers})...")

    counter = Counter()
    done = 0
    total = len(all_ids)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_detail_task, prec_id, counter): prec_id
            for prec_id in all_ids
        }
        for future in as_completed(futures):
            future.result()
            done += 1
            if done % 500 == 0:
                c, f, e = counter.snapshot()
                logger.info(f"Progress: {done}/{total} (cached={c}, fetched={f}, errors={e})")

    c, f, e = counter.snapshot()
    logger.info(f"Done: cached={c}, fetched={f}, errors={e}")


if __name__ == "__main__":
    main()
