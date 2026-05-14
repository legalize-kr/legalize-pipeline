"""Git operations for committing precedent files with historical dates."""

import logging
import os
import subprocess
from pathlib import Path

from core.config import BOT_AUTHOR
from core.git_engine import historical_commit_env

logger = logging.getLogger(__name__)


def _run_git(*args: str, cwd: Path, env: dict | None = None) -> str:
    """Run a git command in the given directory and return stdout."""
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


def commit_exists(prec_id: str, *, cwd: Path) -> bool:
    """Check if a commit for this 판례일련번호 already exists."""
    try:
        log = _run_git(
            "log", "--oneline", "--all",
            f"--grep=판례일련번호: {prec_id}",
            cwd=cwd,
        )
        return bool(log)
    except RuntimeError:
        return False


def commit_precedent(
    file_path: str,
    parsed: dict,
    *,
    cwd: Path,
    skip_dedup: bool = False,
) -> str | None:
    """Stage and commit a precedent file with 선고일자 as commit date.

    Args:
        file_path: Relative path to the .md file within the repo.
        parsed: Parsed precedent dict (from converter.parse_precedent_xml).
        cwd: Root directory of the precedent-kr repository.
        skip_dedup: Skip duplicate commit check.

    Returns:
        Commit hash if committed, None if skipped.
    """
    prec_id = parsed.get("판례정보일련번호", "")
    case_name = parsed.get("사건명", "")
    case_no = parsed.get("사건번호", "")
    court = parsed.get("법원명", "")
    case_type = parsed.get("사건종류명", "")
    date_raw = parsed.get("선고일자", "")

    abs_path = cwd / file_path
    if not abs_path.exists():
        logger.error(f"File not found: {abs_path}")
        return None

    if not skip_dedup and commit_exists(prec_id, cwd=cwd):
        logger.debug(f"Commit exists for 판례일련번호:{prec_id}, skipping")
        return None

    _run_git("add", file_path, cwd=cwd)

    # Check for actual changes
    status = _run_git("status", "--porcelain", "--", file_path, cwd=cwd)
    if not status:
        logger.debug(f"No changes for {file_path}, skipping")
        return None

    # Format date: YYYYMMDD → YYYY-MM-DD, clamp before 1970
    date = "1970-01-01"
    if date_raw and len(date_raw) == 8 and date_raw[:4] not in ("0000", "0001"):
        d = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
        date = d if d >= "1970-01-01" else "1970-01-01"

    env = historical_commit_env(date, author=BOT_AUTHOR)

    # Commit message
    title = f"판례: {case_name}" if case_name else f"판례: {case_no}"
    message = (
        f"{title}\n\n"
        f"판례: https://www.law.go.kr/LSW/precInfoP.do?precSeq={prec_id}\n"
        f"선고일자: {date}\n"
        f"법원명: {court}\n"
        f"사건종류: {case_type}\n"
        f"판례일련번호: {prec_id}"
    )

    _run_git(
        "commit", "-m", message,
        "--author", BOT_AUTHOR,
        "--", file_path,
        cwd=cwd, env=env,
    )

    commit_hash = _run_git("rev-parse", "HEAD", cwd=cwd)
    logger.info(f"Committed {file_path} [{commit_hash[:8]}] date={date}")
    return commit_hash
