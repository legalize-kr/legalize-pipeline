"""Incremental administrative-rule update entrypoint."""

import argparse
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from core.github_actions import report_partial_fetch

from .config import ADMRULE_REPO, CONCURRENT_WORKERS
from .fetch_cache import fetch_all_current, fetch_details
from .git_engine import committed_serials as _committed_serials
from .import_admrules import import_from_cache
from .snapshot import RebuildRequired, reconcile_current_snapshot, require_current_snapshot, write_current_snapshot

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


def _publish_incremental(repo: Path, serials: list[str], selection: dict) -> dict[str, int]:
    def git(*args, check=True):
        return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True)

    if git("status", "--porcelain=v1").stdout:
        raise RuntimeError("Administrative rule update requires a clean worktree")
    base = git("rev-parse", "--verify", "HEAD", check=False)
    if base.returncode:
        raise RebuildRequired("Administrative rule rebuild required: daily updates require an existing HEAD")
    if not serials:
        require_current_snapshot(repo, selection)
        return import_from_cache(repo, serials=[])
    with TemporaryDirectory(prefix="admrule-update-") as temporary:
        candidate = Path(temporary) / "candidate"
        git("worktree", "add", "--detach", str(candidate), base.stdout.decode().strip())
        try:
            stats = import_from_cache(candidate, commit=True, serials=serials, skip_dedup=True)
            if not stats["errors"]:
                require_current_snapshot(candidate, selection)
                if git("rev-parse", "HEAD").stdout != base.stdout:
                    raise RuntimeError("Administrative rule branch changed during update")
                head = subprocess.check_output(["git", "-C", str(candidate), "rev-parse", "HEAD"])
                if head != base.stdout:
                    git("merge", "--ff-only", head.decode().strip())
            return stats
        finally:
            git("worktree", "remove", "--force", str(candidate))


def run(
    *,
    repo: Path = ADMRULE_REPO,
    limit: int | None = None,
    workers: int = CONCURRENT_WORKERS,
    commit: bool = False,
    knd: list[str] | None = None,
    org: str = "",
    days: int = 14,
) -> dict[str, int]:
    date_range = _date_range(days)
    logger.info("searching administrative rules in date range %s", date_range)
    entries = fetch_all_current(knd_values=knd, org=org, max_entries=limit, date_range=date_range)
    full_run = limit is None and knd is None and not org
    current = fetch_all_current(history=False) if full_run else []
    current_serials = _current_serials(entries + current, limit)
    committed_serials = _committed_serials(repo) if commit else set()
    import_serials = [serial for serial in current_serials if serial not in committed_serials] if commit else current_serials
    fetch_counter = fetch_details(entries + current, workers=workers, limit=limit, **({"refresh_current": True} if full_run else {}))
    cached, fetched, fetch_errors = fetch_counter.snapshot()
    if full_run and fetch_errors:
        raise RuntimeError(f"Incomplete administrative rule update: {fetch_errors} detail failures")
    if full_run:
        selection = write_current_snapshot(current, history_entries=entries, repo=repo, workers=workers)
    if full_run and commit:
        import_stats = _publish_incremental(repo, import_serials, selection)
    else:
        import_stats = import_from_cache(repo, limit=None, commit=commit, serials=import_serials, skip_dedup=commit)
        if full_run and not import_stats["errors"]:
            import_stats.update(reconcile_current_snapshot(repo))
    if full_run:
        import_stats["snapshot_refetched"] = selection["refreshed_details"]
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
    parser.add_argument("--days", type=int, default=14, help="Look back this many days for daily updates")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        stats = run(
            repo=args.repo,
            limit=args.limit,
            workers=args.workers,
            commit=args.commit,
            knd=args.knd,
            org=args.org,
            days=args.days,
        )
    except RebuildRequired as exc:
        raise SystemExit(str(exc)) from exc
    report_partial_fetch("Administrative rules", stats)
    if stats.get("errors"):
        raise SystemExit("Administrative rule import failed")


if __name__ == "__main__":
    main()
