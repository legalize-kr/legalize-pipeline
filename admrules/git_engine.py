from pathlib import Path

from core.config import BOT_AUTHOR
from core.git_engine import commit_with_historical_date


def commit_admrule(repo_dir: Path, file_path: str, message: str, date: str, serial_no: str, *, skip_dedup: bool = False) -> bool:
    key = None if skip_dedup else f"행정규칙일련번호: {serial_no}"
    return commit_with_historical_date(repo_dir, [Path(file_path)], message, date, author=BOT_AUTHOR, dedup_grep_key=key)
