from pathlib import Path

from core.config import BOT_AUTHOR, WORKSPACE_ROOT
from core.git_engine import commit_with_historical_date


def commit_law(file_path: str, message: str, date: str, mst: str, *, author: str | None = None, skip_dedup: bool = False) -> bool:
    key = None if skip_dedup else f"법령MST: {mst}"
    return commit_with_historical_date(WORKSPACE_ROOT, [Path(file_path)], message, date, author=author or BOT_AUTHOR, dedup_grep_key=key)
