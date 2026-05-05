from pathlib import Path

from core.config import BOT_AUTHOR
from core.git_engine import commit_with_historical_date


def commit_admrule(
    repo_dir: Path,
    file_path: str,
    message: str,
    date: str,
    serial_no: str,
    *,
    skip_dedup: bool = False,
    stale_paths: list[str] | None = None,
) -> bool:
    key = None if skip_dedup else f"행정규칙일련번호: {serial_no}"
    paths = [Path(file_path), *[Path(path) for path in stale_paths or []]]
    return commit_with_historical_date(repo_dir, paths, message, date, author=BOT_AUTHOR, dedup_grep_key=key)
