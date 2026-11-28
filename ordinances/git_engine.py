"""Ordinance-specific shim for shared historical-date commits."""

import datetime
import subprocess
from pathlib import Path

from core.config import BOT_AUTHOR
from core.git_engine import commit_with_historical_date


def commit_ordinance(
    repo_dir: Path,
    file_path: str,
    message: str,
    date: str,
    ordinance_id: str,
    serial_no: str,
    *,
    skip_dedup: bool = False,
    stale_paths: list[str] | None = None,
) -> bool:
    del ordinance_id
    key = None if skip_dedup else f"자치법규일련번호: {serial_no}"
    paths = [Path(file_path), *[Path(path) for path in stale_paths or []]]
    return commit_with_historical_date(repo_dir, paths, message, date, author=BOT_AUTHOR, dedup_grep_key=key)


def commit_ordinance_deletion(
    repo_dir: Path,
    file_path: str | None,
    message: str,
    date: str,
    serial_no: str,
    *,
    skip_dedup: bool = False,
    preserve_message: bool = False,
) -> bool:
    key = None if skip_dedup else f"자치법규일련번호: {serial_no}"
    return commit_with_historical_date(
        repo_dir,
        [Path(file_path)] if file_path else [],
        message,
        date,
        author=BOT_AUTHOR,
        dedup_grep_key=key,
        allow_empty=file_path is None,
        preserve_message=preserve_message,
    )


def committed_metadata(repo: Path) -> tuple[set[str], dict[str, tuple[str, int]]]:
    if not (repo / ".git").exists():
        return set(), {}
    result = subprocess.run(
        ["git", "log", "-z", "HEAD", "--format=%as%n%B"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set(), {}
    serial_prefix = "자치법규일련번호: "
    identity_prefix = "자치법규ID: "
    serials = set()
    latest = {}
    for record in result.stdout.split("\0"):
        date, _, message = record.partition("\n")
        identity = serial = ""
        for line in message.splitlines():
            if line.startswith("공포일자: ") and line[6:].strip():
                source_date = line[6:].strip()
                try:
                    date = datetime.date.fromisoformat(source_date).isoformat()
                except ValueError:
                    pass
            elif line.startswith(identity_prefix) and not identity:
                identity = line[len(identity_prefix):].strip()
            elif line.startswith(serial_prefix) and not serial:
                serial = line[len(serial_prefix):].strip()
            if identity and serial:
                break
        if serial:
            serials.add(serial)
        if identity:
            version = date, int(serial) if serial.isdecimal() else 2**63 - 1
            latest[identity] = max(latest.get(identity, version), version)
    return serials, latest
