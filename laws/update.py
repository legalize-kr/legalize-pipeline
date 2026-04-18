"""Incremental updater for new/amended laws.

Uses search API to find recently changed laws, then fetches and commits
only the new versions directly (no full history traversal).

Usage (from legalize-pipeline root):
    python -m laws.update                    # Update recent laws (default 7 days)
    python -m laws.update --days 30          # Look back 30 days
    python -m laws.update --law-type 법률    # Only 법률
    python -m laws.update --dry-run          # Preview only
"""

import argparse
import logging
from datetime import datetime, timedelta

from .api_client import get_law_detail, search_laws
from .checkpoint import get_last_update, get_processed_msts, mark_processed, set_last_update
from .config import KR_DIR, LAW_API_KEY
from .converter import (
    entry_sort_key,
    format_date,
    get_law_path,
    law_to_markdown,
    reset_path_registry,
)
from .git_engine import commit_law
from .import_laws import build_commit_msg

logger = logging.getLogger(__name__)


def update(
    days: int = 7,
    law_type_filter: str | None = None,
    dry_run: bool = False,
    max_pages: int = 50,
) -> int:
    """Query API for recently amended laws and import their latest versions."""
    if not LAW_API_KEY:
        logger.error("No API key (LAW_OC) configured. Cannot update.")
        return 0

    reset_path_registry()

    last = get_last_update()
    since = last.replace("-", "") if last else (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    today = datetime.now().strftime("%Y%m%d")

    logger.info(f"Searching amendments from {since} to {today}")

    # Collect all search results with their MSTs.
    # Bounded-iteration invariant: abort if pagination exceeds max_pages to
    # catch pagination regressions loudly (mirror of fetch_cache.py's invariant).
    all_laws: list[dict] = []
    page = 1
    while True:
        result = search_laws(query="", page=page, display=100, date_from=since, date_to=today)
        all_laws.extend(result["laws"])
        if page * 100 >= result["totalCnt"]:
            break
        if page >= max_pages:
            raise RuntimeError(
                f"laws.update pagination exceeded max_pages={max_pages} "
                f"(totalCnt={result['totalCnt']}, collected={len(all_laws)}). "
                f"Likely pagination regression, unexpected window size, or backfill — "
                f"raise --max-pages explicitly if this is intentional."
            )
        page += 1

    # Filter out already-processed MSTs via checkpoint (in-memory, no git log)
    processed = get_processed_msts()
    new_laws = [law for law in all_laws if law["법령일련번호"] and law["법령일련번호"] not in processed]
    new_laws.sort(key=lambda x: entry_sort_key(
        x.get("공포일자", ""),
        x.get("법령명한글", ""),
        x.get("공포번호", ""),
        x.get("법령일련번호", ""),
    ))

    logger.info(f"Found {len(all_laws)} results, {len(new_laws)} new after checkpoint filter")

    committed = 0
    errors = 0

    for i, law in enumerate(new_laws, 1):
        mst = law["법령일련번호"]
        name = law.get("법령명한글", "")

        file_path = None
        try:
            detail = get_law_detail(mst)
            meta = detail["metadata"]
            law_type = meta.get("법령구분", "")

            if law_type_filter and law_type_filter != law_type:
                continue

            fetched_name = meta.get("법령명한글", name)
            law_id = meta.get("법령ID", "")
            file_path = get_law_path(fetched_name, law_type, law_id)
            abs_path = KR_DIR.parent / file_path

            meta["제개정구분"] = law.get("제개정구분명", meta.get("제개정구분", ""))
            if not meta.get("공포번호"):
                meta["공포번호"] = law.get("공포번호", "")

            prom_date = format_date(meta.get("공포일자", ""))

            if dry_run:
                logger.info(f"  [{i}/{len(new_laws)}] [DRY-RUN] MST={mst} {prom_date} {fetched_name} -> {file_path}")
                continue

            content = law_to_markdown(detail)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")

            commit_msg = build_commit_msg(fetched_name, law_type, mst, meta)
            if not prom_date or len(prom_date) != 10:
                prom_date = "2000-01-01"

            result = commit_law(file_path, commit_msg, prom_date, mst, skip_dedup=True)
            if result:
                mark_processed(mst)
                committed += 1
                logger.info(f"  [{i}/{len(new_laws)}] Committed MST={mst} {prom_date} {fetched_name}")

        except ValueError as e:  # empty body (P1)
            from .failures import log_failure, mark_failed, mark_failed_and_quarantine
            log_failure("update", str(mst), name, e)
            if file_path is not None:
                mark_failed_and_quarantine(
                    mst=str(mst), reason="empty_body", detail=str(e),
                    path=KR_DIR.parent / file_path,
                    step="update", law_name=name,
                )
            else:
                mark_failed(mst=str(mst), reason="empty_body", detail=str(e),
                            step="update", law_name=name)
            errors += 1
        except Exception as e:  # all other failures (P3)
            from .failures import log_failure, classify, mark_failed
            log_failure("update", str(mst), name, e)
            mark_failed(mst=str(mst), reason=classify(e), detail=str(e),
                        step="update", law_name=name)
            errors += 1

        if i % 50 == 0:
            logger.info(f"Progress: {i}/{len(new_laws)} (committed={committed}, errors={errors})")

    if not dry_run:
        set_last_update(format_date(today))

    logger.info(f"Update done: committed={committed}, errors={errors}")
    return committed


def main():
    parser = argparse.ArgumentParser(description="Incremental law updater")
    parser.add_argument("--days", type=int, default=7, help="Look back N days (default: 7)")
    parser.add_argument("--law-type", help="Filter by 법령구분 (e.g., 법률)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help=(
            "Abort if pagination exceeds N pages (100 items/page). "
            "Default 50 = 5000 items, sized for daily cron. "
            "Raise for backfill (e.g. --days 3650 --max-pages 500)."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    committed = update(
        days=args.days,
        law_type_filter=args.law_type,
        dry_run=args.dry_run,
        max_pages=args.max_pages,
    )

    if not args.dry_run:
        from .generate_metadata import save as save_metadata
        save_metadata()

    logger.info(f"Update complete: {committed} laws committed")


if __name__ == "__main__":
    main()
