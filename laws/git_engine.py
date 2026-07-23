import re
from pathlib import Path

from core.git_engine import _run_git as _core_run_git
from core.git_engine import commit_with_historical_date
from .config import BOT_AUTHOR, LAW_REPO


def _run_git(*args: str, env: dict | None = None) -> str:
    return _core_run_git(*args, cwd=LAW_REPO, env=env)


# YAML scalars reach us quoted or bare depending on which writer produced the
# file, so strip a matching pair of quotes rather than trusting either form.
_FRONTMATTER_VALUE = r"^{key}:\s*(?:'([^']*)'|\"([^\"]*)\"|(\S+))\s*$"


def _frontmatter_value(blob: str, key: str) -> str | None:
    match = re.search(_FRONTMATTER_VALUE.format(key=re.escape(key)), blob, re.M)
    if not match:
        return None
    return next((g for g in match.groups() if g is not None), "")


def head_law_version(file_path: str) -> tuple[str, str, str] | None:
    """(공포일자, 공포번호, 법령MST) of ``file_path`` at HEAD, or None.

    공포일자 comes back without separators (YYYYMMDD) so it orders directly
    against the raw API value. 공포번호 is the tie-breaker for same-day
    amendments, matching the canonical ingestion order.

    Every field is read through _FRONTMATTER_VALUE: build_csv_markdown emits
    quoted scalars (``공포일자: '2024-01-15'``) while the API path emits bare
    ones, and a stray quote sorts below every digit — which would silently
    park the HEAD baseline at the bottom and defeat the regression guard.
    """
    try:
        blob = _run_git("show", f"HEAD:{file_path}")
    except RuntimeError:
        return None
    prom = _frontmatter_value(blob, "공포일자")
    mst = _frontmatter_value(blob, "법령MST")
    if prom is None or mst is None:
        return None
    return (
        prom.replace("-", ""),
        _frontmatter_value(blob, "공포번호") or "",
        mst,
    )


def commit_law(
    file_path: str,
    message: str,
    date: str,
    mst: str,
    *,
    author: str | None = None,
    skip_dedup: bool = False,
    extra_paths: list[str] | None = None,
) -> bool:
    key = None if skip_dedup else f"법령MST: {mst}"
    paths = [Path(file_path), *[Path(path) for path in (extra_paths or [])]]
    return commit_with_historical_date(
        LAW_REPO,
        paths,
        message,
        date,
        author=author or BOT_AUTHOR,
        dedup_grep_key=key,
    )


def commit_law_changes(
    file_paths: list[str],
    message: str,
    date: str,
    *,
    author: str | None = None,
) -> bool:
    """Commit a grouped law-tree maintenance change without an MST marker."""

    return commit_with_historical_date(
        LAW_REPO,
        [Path(path) for path in file_paths],
        message,
        date,
        author=author or BOT_AUTHOR,
    )
