"""Incremental ordinance update entrypoint."""

import argparse
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from core.github_actions import report_partial_fetch

from .config import CONCURRENT_WORKERS, ORDINANCE_REPO
from .fetch_cache import fetch_all_current, fetch_details, fetch_history_for_entries
from .import_ordinances import import_from_cache

logger = logging.getLogger(__name__)


def _date_range(days: int) -> str:
    today = datetime.now()
    since = today - timedelta(days=days)
    return f"{since:%Y%m%d}~{today:%Y%m%d}"


def _current_serials(entries: list[dict], limit: int | None = None) -> list[str]:
    serials = []
    seen = set()
    for entry in entries:
        serial = str(entry.get("자치법규일련번호", "")) or str(entry.get("자치법규ID", ""))
        if serial and serial not in seen:
            seen.add(serial)
            serials.append(serial)
    return serials[:limit] if limit is not None else serials


def _committed_metadata(repo: Path) -> tuple[set[str], set[str]]:
    if not (repo / ".git").exists():
        return set(), set()
    result = subprocess.run(
        ["git", "log", "--all", "--format=%B"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set(), set()
    serial_prefix = "자치법규일련번호: "
    identity_prefix = "자치법규ID: "
    serials = set()
    identities = set()
    for line in result.stdout.splitlines():
        if line.startswith(serial_prefix) and line[len(serial_prefix):].strip():
            serials.add(line[len(serial_prefix):].strip())
        elif line.startswith(identity_prefix) and line[len(identity_prefix):].strip():
            identities.add(line[len(identity_prefix):].strip())
    return serials, identities


def _compact_date(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def _within_date_range(entry: dict, date_range: str) -> bool:
    try:
        start, end = date_range.split("~", 1)
    except ValueError:
        return True
    value = _compact_date(entry.get("공포일자", ""))
    return bool(value) and start <= value <= end


def _import_serials(entries: list[dict], repo: Path, date_range: str, *, commit: bool) -> list[str]:
    current_serials = _current_serials(entries)
    if not commit:
        return current_serials

    committed_serials, committed_identities = _committed_metadata(repo)
    serials = []
    for entry in entries:
        serial = str(entry.get("자치법규일련번호", "")) or str(entry.get("자치법규ID", ""))
        identity = str(entry.get("자치법규ID", ""))
        if not serial or serial in committed_serials or serial in serials:
            continue
        if identity not in committed_identities or _within_date_range(entry, date_range):
            serials.append(serial)
    return serials


def run(
    *,
    repo: Path = ORDINANCE_REPO,
    limit: int | None = None,
    workers: int = CONCURRENT_WORKERS,
    commit: bool = False,
    types: list[str] | None = None,
    org: str = "",
    sborg: str = "",
    days: int = 14,
) -> dict[str, int]:
    date_range = _date_range(days)
    logger.info("searching ordinances in date range %s", date_range)
    current_entries = fetch_all_current(types, org=org, sborg=sborg, max_entries=limit, date_range=date_range)
    entries = fetch_history_for_entries(current_entries, types) if current_entries else []
    if not entries:
        entries = current_entries
    import_serials = _import_serials(entries, repo, date_range, commit=commit)
    import_serial_set = set(import_serials)
    fetch_entries = [
        entry
        for entry in entries
        if (str(entry.get("자치법규일련번호", "")) or str(entry.get("자치법규ID", ""))) in import_serial_set
    ]
    fetch_counter = fetch_details(fetch_entries, workers=workers)
    cached, fetched, fetch_errors = fetch_counter.snapshot()
    import_stats = import_from_cache(
        repo,
        limit=None,
        commit=commit,
        serials=import_serials,
        skip_dedup=False,
    )
    stats = {
        "cached": cached,
        "fetched": fetched,
        "fetch_errors": fetch_errors,
        **import_stats,
    }
    logger.info("ordinance update done: %s", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and import ordinances")
    parser.add_argument("--repo", type=Path, default=ORDINANCE_REPO)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=CONCURRENT_WORKERS)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--type", dest="types", action="append", help="자치법규종류. Repeatable.")
    parser.add_argument("--org", default="", help="Optional law.go.kr 광역 org code")
    parser.add_argument("--sborg", default="", help="Optional law.go.kr 기초 sborg code")
    parser.add_argument("--days", type=int, default=14, help="Look back this many days for daily updates")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stats = run(
        repo=args.repo,
        limit=args.limit,
        workers=args.workers,
        commit=args.commit,
        types=args.types,
        org=args.org,
        sborg=args.sborg,
        days=args.days,
    )
    report_partial_fetch("Ordinances", stats)


if __name__ == "__main__":
    main()
