"""Ordinance-specific shim for shared historical-date commits."""

from pathlib import Path

from core.config import BOT_AUTHOR
from core.git_engine import commit_with_historical_date


def commit_ordinance(repo_dir: Path, file_path: str, message: str, date: str, ordinance_id: str, *, skip_dedup: bool = False) -> bool:
    key = None if skip_dedup else f"자치법규ID: {ordinance_id}"
    return commit_with_historical_date(repo_dir, [Path(file_path)], message, date, author=BOT_AUTHOR, dedup_grep_key=key)
