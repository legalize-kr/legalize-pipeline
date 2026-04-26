"""Import precedents from cached XML files to Markdown.

Usage:
    python -m precedents.import_precedents
    python -m precedents.import_precedents --limit 100 --dry-run
    python -m precedents.import_precedents --workers 8 --output-dir /path/to/output
    python -m precedents.import_precedents --git          # commit each with 선고일자
"""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from core.atomic_io import atomic_write_text
from core.counter import Counter

from .config import CONCURRENT_WORKERS, PREC_CACHE_DIR, PRECEDENT_KR_DIR
from .converter import (
    get_precedent_path,
    parse_precedent_xml,
    precedent_to_markdown,
    reset_path_registry,
)
from .git_engine import commit_precedent

logger = logging.getLogger(__name__)


def _write_task(
    parsed: dict,
    path: str,
    output_dir: Path,
    dry_run: bool,
    counter: Counter,
) -> None:
    """Write a single precedent Markdown file (runs in thread pool)."""
    try:
        md = precedent_to_markdown(parsed)
        if not dry_run:
            abs_path = output_dir / path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(abs_path, md)
        counter.inc("fetched")  # converted
    except Exception as e:
        logger.error(f"Failed to write {path}: {e}")
        counter.inc("errors")


def run(
    limit: int | None = None,
    dry_run: bool = False,
    workers: int = CONCURRENT_WORKERS,
    output_dir: Path = PRECEDENT_KR_DIR,
    git: bool = False,
    skip_dedup: bool = False,
) -> dict:
    """Run the full import pipeline. Returns stats dict.

    Args:
        git: If True, commit each file with 선고일자 as commit date (sequential).
        skip_dedup: Skip git commit dedup check (for rebuild).
    """
    reset_path_registry()

    xml_files = sorted(PREC_CACHE_DIR.glob("*.xml"))
    if limit is not None:
        xml_files = xml_files[:limit]

    total = len(xml_files)
    logger.info(f"Found {total} cached XML files")

    # Phase 1: single-threaded parse + path assignment (builds collision registry)
    entries: list[tuple[dict, str]] = []
    skipped_empty = 0
    parse_errors = 0

    for i, xml_file in enumerate(xml_files, 1):
        try:
            raw = xml_file.read_bytes()
            parsed = parse_precedent_xml(raw)
            if parsed is None:
                logger.debug(f"Skipping error XML: {xml_file.name}")
                parse_errors += 1
                continue
            if not parsed.get("판례정보일련번호"):
                skipped_empty += 1
                continue
            path = get_precedent_path(parsed)
            entries.append((parsed, path))
        except Exception as e:
            logger.error(f"Failed to parse {xml_file}: {e}")
            parse_errors += 1

        if i % 1000 == 0:
            logger.info(f"Parse progress: {i}/{total}")

    logger.info(
        f"Parsed {len(entries)} valid records "
        f"(skipped_empty={skipped_empty}, parse_errors={parse_errors})"
    )

    # Composite-key collision audit (Plan §3 Phase 1 acceptance).
    # `get_precedent_path` only appends `_{serial}.md` on registry collisions,
    # which the new composite grammar should make impossible. Surface the count
    # so dry-run runs can verify zero.
    composite_collisions = sum(
        1
        for parsed, path in entries
        if (sn := parsed.get("판례정보일련번호") or "") and path.endswith(f"_{sn}.md")
    )
    logger.info(f"Composite-key collisions (serial-suffixed paths): {composite_collisions}")

    if git:
        # Sort by 선고일자 for chronological commit history
        entries.sort(key=lambda e: e[0].get("선고일자", "") or "99999999")

    # Phase 2: write (+ optional git commit)
    counter = Counter()

    if git:
        # Sequential: write file then commit with 선고일자
        for i, (parsed, path) in enumerate(entries, 1):
            if dry_run:
                counter.inc("fetched")
            else:
                try:
                    md = precedent_to_markdown(parsed)
                    abs_path = output_dir / path
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write_text(abs_path, md)
                    commit_precedent(
                        path, parsed, cwd=output_dir, skip_dedup=skip_dedup,
                    )
                    counter.inc("fetched")
                except Exception as e:
                    logger.error(f"Failed {path}: {e}")
                    counter.inc("errors")
            if i % 500 == 0:
                _, converted, write_errors = counter.snapshot()
                logger.info(
                    f"Git progress: {i}/{len(entries)} "
                    f"(committed={converted}, errors={write_errors})"
                )
    else:
        # Parallel: write files only (no git)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_write_task, parsed, path, output_dir, dry_run, counter)
                for parsed, path in entries
            ]
            for i, fut in enumerate(as_completed(futures), 1):
                fut.result()
                if i % 1000 == 0:
                    _, converted, write_errors = counter.snapshot()
                    logger.info(
                        f"Write progress: {i}/{len(entries)} "
                        f"(converted={converted}, errors={write_errors})"
                    )

    _, converted, write_errors = counter.snapshot()

    stats = {
        "total": total,
        "converted": converted,
        "skipped_errors": parse_errors + write_errors,
        "skipped_empty": skipped_empty,
        "composite_collisions": composite_collisions,
    }
    logger.info(f"Import done: {stats}")
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Import cached precedent XMLs to Markdown")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Process only N precedents")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and report without writing files")
    parser.add_argument("--workers", type=int, default=CONCURRENT_WORKERS, metavar="N",
                        help="Parallel workers (default: %(default)s)")
    parser.add_argument("--output-dir", type=Path, default=PRECEDENT_KR_DIR, metavar="PATH",
                        help="Output directory (default: %(default)s)")
    parser.add_argument("--git", action="store_true",
                        help="Commit each file with 선고일자 as git date (sequential, slow)")
    parser.add_argument("--skip-dedup", action="store_true",
                        help="Skip git commit dedup check (for rebuild)")
    args = parser.parse_args()

    stats = run(
        limit=args.limit,
        dry_run=args.dry_run,
        workers=args.workers,
        output_dir=args.output_dir,
        git=args.git,
        skip_dedup=args.skip_dedup,
    )
    print(
        f"total={stats['total']} converted={stats['converted']} "
        f"skipped_errors={stats['skipped_errors']} skipped_empty={stats['skipped_empty']}"
    )
