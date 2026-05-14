"""Incremental precedent update: fetch recent, convert, commit.

Searches for precedents with 선고일자 in the last N days, fetches
detail XML for any not already cached, converts to Markdown, and
commits each with 선고일자 as git date.

Usage:
    python -m precedents.update                  # Last 30 days
    python -m precedents.update --days 7         # Last 7 days
    python -m precedents.update --dry-run        # Report without writing
"""

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.atomic_io import atomic_write_text

from . import cache
from .api_client import NoResultError, get_precedent_detail, search_precedents
from .config import PRECEDENT_KR_DIR
from .converter import (
    get_precedent_path,
    parse_precedent_xml,
    precedent_to_markdown,
    reset_path_registry,
)
from .git_engine import commit_precedent

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))


def _date_range(days: int) -> str:
    """Return prncYd parameter for the last N days (YYYYMMDD~YYYYMMDD)."""
    end = datetime.now(_KST)
    start = end - timedelta(days=days)
    return f"{start.strftime('%Y%m%d')}~{end.strftime('%Y%m%d')}"


def _precedent_sort_key(prec: dict) -> tuple[str, str]:
    return (prec.get("선고일자", "") or "99999999", str(prec.get("판례일련번호", "") or ""))


def _collect_recent_ids(days: int) -> list[dict]:
    """Search API for precedents with 선고일자 in the last N days."""
    date_range = _date_range(days)
    logger.info(f"Searching precedents in date range: {date_range}")

    all_precs: list[dict] = []
    seen: set[str] = set()
    page = 1

    while True:
        result = search_precedents(
            query="", page=page, display=100, sort="ddes",
            date_range=date_range,
        )
        total = result["totalCnt"]

        for prec in result["precedents"]:
            prec_id = prec.get("판례일련번호", "")
            if prec_id and prec_id not in seen:
                seen.add(prec_id)
                all_precs.append(prec)

        logger.info(f"Search page {page}: {len(all_precs)}/{total}")

        if page * 100 >= total or not result["precedents"]:
            break
        page += 1

    all_precs.sort(key=_precedent_sort_key)
    return all_precs


def run(
    days: int = 180,
    dry_run: bool = False,
    output_dir: Path = PRECEDENT_KR_DIR,
) -> dict:
    """Run incremental update. Returns stats dict."""
    reset_path_registry()

    # Step 1: find recent precedents
    recent = _collect_recent_ids(days)
    logger.info(f"Found {len(recent)} precedents in last {days} days")

    if not recent:
        return {"found": 0, "committed": 0, "errors": 0, "no_result": 0}

    # Known upstream no-result IDs (search lists them, detail cannot resolve).
    no_result_ids = cache.load_no_result_ids()

    # Step 2: fetch detail for each and write/commit (git detects zero-diff)
    committed = 0
    errors = 0
    no_result = 0

    for i, prec_meta in enumerate(recent, 1):
        prec_id = prec_meta["판례일련번호"]

        if prec_id in no_result_ids:
            no_result += 1
            continue

        try:
            # Fetch detail (cache-aware: skips if already cached)
            raw = get_precedent_detail(prec_id)

            parsed = parse_precedent_xml(raw)
            if parsed is None:
                logger.debug(f"Skipping error response: {prec_id}")
                continue

            path = get_precedent_path(parsed)
            abs_path = output_dir / path

            if dry_run:
                logger.info(f"[dry-run] Would write: {path}")
                continue

            md = precedent_to_markdown(parsed)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(abs_path, md)

            result = commit_precedent(path, parsed, cwd=output_dir, skip_dedup=False)
            if result:
                committed += 1

        except NoResultError:
            cache.add_no_result_id(prec_id)
            no_result_ids.add(prec_id)
            no_result += 1
            logger.debug(f"No-result prec_id {prec_id} recorded")

        except Exception as e:
            logger.error(f"Failed prec_id {prec_id}: {e}")
            errors += 1

        if i % 50 == 0:
            logger.info(
                f"Progress: {i}/{len(recent)} "
                f"(committed={committed}, no_result={no_result}, errors={errors})"
            )

    stats = {
        "found": len(recent),
        "committed": committed,
        "errors": errors,
        "no_result": no_result,
    }
    logger.info(f"Update done: {stats}")
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Incremental precedent update")
    parser.add_argument("--days", type=int, default=180, help="Lookback days (default: 180)")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    parser.add_argument("--output-dir", type=Path, default=PRECEDENT_KR_DIR)
    args = parser.parse_args()

    stats = run(days=args.days, dry_run=args.dry_run, output_dir=args.output_dir)
    print(
        f"found={stats['found']} committed={stats['committed']} "
        f"no_result={stats['no_result']} errors={stats['errors']}"
    )
