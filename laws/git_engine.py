from pathlib import Path

from core.git_engine import _run_git as _core_run_git
from core.git_engine import commit_with_historical_date
from .config import BOT_AUTHOR, LAW_REPO


def _run_git(*args: str, env: dict | None = None) -> str:
    return _core_run_git(*args, cwd=LAW_REPO, env=env)


def commit_law(file_path: str, message: str, date: str, mst: str, *, author: str | None = None, skip_dedup: bool = False) -> bool:
    key = None if skip_dedup else f"법령MST: {mst}"
    return commit_with_historical_date(LAW_REPO, [Path(file_path)], message, date, author=author or BOT_AUTHOR, dedup_grep_key=key)
