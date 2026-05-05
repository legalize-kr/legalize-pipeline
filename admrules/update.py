"""Incremental administrative-rule update entrypoint."""

import argparse
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from .config import ADMRULE_REPO, CONCURRENT_WORKERS
from .fetch_cache import fetch_all_current, fetch_details
from .import_admrules import import_from_cache

logger = logging.getLogger(__name__)


def _date_range(days: int) -> str:
    today = datetime.now()
    since = today - timedelta(days=days)
    return f"{since:%Y%m%d}~{today:%Y%m%d}"


def _current_serials(entries: list[dict], limit: int | None = None) -> list[str]:
    serials = []
    seen = set()
    for entry in entries:
        serial = str(entry.get("행정규칙일련번호", ""))
        if serial and serial not in seen:
            seen.add(serial)
            serials.append(serial)
    return serials[:limit] if limit is not None else serials


def _committed_serials(repo: Path) -> set[str]:
    if not (repo / ".git").exists():
        return set()
    result = subprocess.run(
        ["git", "log", "--all", "--format=%B"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    prefix = "행정규칙일련번호: "
    return {
        line[len(prefix):].strip()
        for line in result.stdout.splitlines()
        if line.startswith(prefix) and line[len(prefix):].strip()
    }


def run(
    *,
    repo: Path = ADMRULE_REPO,
    limit: int | None = None,
    workers: int = CONCURRENT_WORKERS,
    commit: bool = False,
    knd: list[str] | None = None,
    org: str = "",
    days: int = 10,
) -> dict[str, int]:
    date_range = _date_range(days)
    logger.info("searching administrative rules in date range %s", date_range)
    entries = fetch_all_current(knd_values=knd, org=org, max_entries=limit, date_range=date_range)
    current_serials = _current_serials(entries, limit)
    committed_serials = _committed_serials(repo) if commit else set()
    import_serials = [serial for serial in current_serials if serial not in committed_serials] if commit else current_serials
    fetch_counter = fetch_details(entries, workers=workers, limit=limit)
    cached, fetched, fetch_errors = fetch_counter.snapshot()
    import_stats = import_from_cache(
        repo,
        limit=None,
        commit=commit,
        serials=import_serials,
        skip_dedup=commit,
    )
    stats = {
        "cached": cached,
        "fetched": fetched,
        "fetch_errors": fetch_errors,
        **import_stats,
    }
    logger.info("admrule update done: %s", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and import administrative rules")
    parser.add_argument("--repo", type=Path, default=ADMRULE_REPO)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=CONCURRENT_WORKERS)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--knd", action="append", help="행정규칙종류 code. Repeatable.")
    parser.add_argument("--org", default="", help="Optional law.go.kr org code filter")
    parser.add_argument("--days", type=int, default=10, help="Look back this many days for daily updates")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(repo=args.repo, limit=args.limit, workers=args.workers, commit=args.commit, knd=args.knd, org=args.org, days=args.days)


if __name__ == "__main__":
    main()
