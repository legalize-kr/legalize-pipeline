"""Shared Git operations for historical-date data commits."""

import datetime as dt
import logging
import os
import subprocess
from pathlib import Path

from .config import BOT_AUTHOR

logger = logging.getLogger(__name__)


def _run_git(*args: str, cwd: Path, env: dict | None = None) -> str:
    """Run a git command in cwd and return stdout."""
    merged_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=merged_env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def file_has_changes(repo_dir: Path, file_paths: list[Path]) -> bool:
    """Check whether any path has uncommitted changes or is untracked."""
    args = ["status", "--porcelain", "--", *[str(p) for p in file_paths]]
    return bool(_run_git(*args, cwd=repo_dir))


def commit_exists(repo_dir: Path, grep_key: str) -> bool:
    """Check if a commit containing grep_key already exists."""
    try:
        return bool(_run_git("log", "--oneline", "--all", f"--grep={grep_key}", cwd=repo_dir))
    except RuntimeError:
        return False


def _coerce_date(value: dt.datetime | dt.date | str) -> str:
    if isinstance(value, dt.datetime):
        date = value.date().isoformat()
    elif isinstance(value, dt.date):
        date = value.isoformat()
    else:
        date = value[:10]
    return max(date, "1970-01-01")


def _relative_paths(repo_dir: Path, file_paths: list[Path]) -> list[Path]:
    rel_paths = []
    for path in file_paths:
        rel_paths.append(path.relative_to(repo_dir) if path.is_absolute() else path)
    return rel_paths


def commit_with_historical_date(
    repo_dir: Path,
    file_paths: list[Path],
    message: str,
    date: dt.datetime | dt.date | str,
    *,
    author: str = BOT_AUTHOR,
    dedup_grep_key: str | None = None,
) -> bool:
    """Stage and commit files with GIT_AUTHOR_DATE/GIT_COMMITTER_DATE set."""
    repo_dir = Path(repo_dir)
    rel_paths = _relative_paths(repo_dir, file_paths)
    missing = [str(repo_dir / p) for p in rel_paths if not (repo_dir / p).exists()]
    if missing:
        logger.error("File not found: %s", ", ".join(missing))
        return False

    if dedup_grep_key and commit_exists(repo_dir, dedup_grep_key):
        logger.info("Commit already exists for %s, skipping", dedup_grep_key)
        return False

    _run_git("add", *[str(p) for p in rel_paths], cwd=repo_dir)
    if not file_has_changes(repo_dir, rel_paths):
        logger.info("No changes for %s, skipping", ", ".join(str(p) for p in rel_paths))
        return False

    iso_date = f"{_coerce_date(date)}T12:00:00+09:00"
    env = {"GIT_AUTHOR_DATE": iso_date, "GIT_COMMITTER_DATE": iso_date}
    _run_git(
        "commit",
        "-m",
        message,
        "--author",
        author,
        "--",
        *[str(p) for p in rel_paths],
        cwd=repo_dir,
        env=env,
    )
    logger.info("Committed %s date=%s", ", ".join(str(p) for p in rel_paths), iso_date)
    return True
