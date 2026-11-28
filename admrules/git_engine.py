import subprocess
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


def commit_admrule_deletion(
    repo_dir: Path,
    file_path: str | None,
    message: str,
    date: str,
    serial_no: str,
    *,
    skip_dedup: bool = False,
) -> bool:
    key = None if skip_dedup else f"행정규칙일련번호: {serial_no}"
    return commit_with_historical_date(
        repo_dir,
        [Path(file_path)] if file_path else [],
        message,
        date,
        author=BOT_AUTHOR,
        dedup_grep_key=key,
        allow_empty=file_path is None,
    )


def committed_serials(repo: Path) -> set[str]:
    if not (repo / ".git").exists():
        raise ValueError(f"Expected a published administrative rule checkout at {repo}")
    result = subprocess.run(
        ["git", "log", "HEAD", "--format=%B"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    prefix = "행정규칙일련번호: "
    return {
        line[len(prefix):].strip()
        for line in result.stdout.splitlines()
        if line.startswith(prefix) and line[len(prefix):].strip()
    }
