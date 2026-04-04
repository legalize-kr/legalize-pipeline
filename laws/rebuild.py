"""Rebuild entire git history from cached API data.

Creates an orphan branch, commits infrastructure files first,
then imports all laws from cache in chronological order.

Usage (from legalize-pipeline root):
    python -m laws.rebuild --dry-run     # Preview without git operations
    python -m laws.rebuild               # Full rebuild
"""

import argparse
import logging

from . import cache
from .api_client import get_law_detail
from .config import BOT_AUTHOR, WORKSPACE_ROOT
from .converter import (
    format_date,
    get_law_path,
    law_to_markdown,
    reset_path_registry,
)
from .git_engine import _run_git
from .import_laws import build_commit_msg

logger = logging.getLogger(__name__)

INFRA_AUTHOR = BOT_AUTHOR

# Files/dirs to include in the infra commit (relative to WORKSPACE_ROOT)
INFRA_PATHS = [
    ".github",
    ".gitignore",
    "CLAUDE.md",
    "KNOWN_ISSUES.md",
    "LICENSE",
    "README.md",
]


def create_orphan_branch(branch_name: str = "rebuild") -> None:
    """Create an orphan branch with no history."""
    _run_git("checkout", "--orphan", branch_name)
    # Unstage everything
    _run_git("rm", "-rf", "--cached", ".")
    logger.info(f"Created orphan branch: {branch_name}")


def commit_infra(dry_run: bool = False, infra_date: str | None = None) -> str | None:
    """Commit all infrastructure files as a single commit."""
    for path in INFRA_PATHS:
        abs_path = WORKSPACE_ROOT / path
        if abs_path.exists():
            _run_git("add", path)

    if dry_run:
        logger.info("[DRY-RUN] Infra commit with %d paths", len(INFRA_PATHS))
        return None

    env = {}
    if infra_date:
        env["GIT_AUTHOR_DATE"] = infra_date
        env["GIT_COMMITTER_DATE"] = infra_date

    _run_git(
        "commit",
        "-m", "feat: 법령 수집·변환·검증 파이프라인 및 웹사이트 구성",
        "--author", INFRA_AUTHOR,
        env=env or None,
    )
    commit_hash = _run_git("rev-parse", "HEAD")
    logger.info(f"Infra committed [{commit_hash[:8]}]")
    return commit_hash


def load_and_sort_entries() -> list[tuple[str, dict]]:
    """Load all cached entries and sort by promulgation date.

    Prefers history cache: collects all MSTs from cached histories, loads their
    detail XMLs, and merges 제개정구분명 from history metadata. Falls back to
    listing all cached detail XMLs directly if no history cache exists.
    """
    history_names = cache.list_cached_history_names()

    if history_names:
        logger.info(f"Loading entries from {len(history_names)} cached histories...")

        # Collect all MSTs with their history metadata
        mst_to_amendment: dict[str, str] = {}
        for name in history_names:
            hist = cache.get_history(name)
            if not hist:
                continue
            for entry in hist:
                mst = entry.get("법령일련번호", "")
                if mst:
                    mst_to_amendment[mst] = entry.get("제개정구분명", "")

        msts = list(mst_to_amendment.keys())
        logger.info(f"Loading detail for {len(msts)} MSTs from history...")
    else:
        logger.info("No history cache found, falling back to cached detail XMLs...")
        msts = cache.list_cached_msts()
        mst_to_amendment = {}
        logger.info(f"Loading {len(msts)} cached entries...")

    entries: list[tuple[str, dict]] = []
    errors = 0

    for mst in msts:
        try:
            detail = get_law_detail(mst)
            # Merge 제개정구분명 from history into detail metadata
            if mst in mst_to_amendment:
                detail["metadata"]["제개정구분"] = mst_to_amendment[mst]
            entries.append((mst, detail))
        except Exception as e:
            logger.error(f"Failed to parse MST {mst}: {e}")
            errors += 1

    if errors:
        logger.warning(f"{errors} entries failed to parse")

    # Sort by promulgation date (oldest first)
    entries.sort(key=lambda x: x[1]["metadata"].get("공포일자", ""))
    logger.info(f"Sorted {len(entries)} entries by date")
    return entries


def rebuild_law_commits(entries: list[tuple[str, dict]], dry_run: bool = False) -> int:
    """Create one commit per law entry, oldest first."""
    reset_path_registry()
    committed = 0
    errors = 0

    for i, (mst, detail) in enumerate(entries, 1):
        meta = detail["metadata"]
        law_name = meta.get("법령명한글", "")
        law_type = meta.get("법령구분", "")
        prom_date = format_date(meta.get("공포일자", ""))

        if not prom_date or len(prom_date) != 10:
            prom_date = "2000-01-01"

        file_path = get_law_path(law_name, law_type)

        if dry_run:
            if i <= 5 or i % 500 == 0 or i == len(entries):
                logger.info(f"  [{i}/{len(entries)}] [DRY-RUN] MST={mst} {prom_date} {law_name} -> {file_path}")
            continue

        try:
            abs_path = WORKSPACE_ROOT / file_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)

            content = law_to_markdown(detail)
            abs_path.write_text(content, encoding="utf-8")

            commit_msg = build_commit_msg(law_name, law_type, mst, meta)

            # Historical date
            if prom_date < "1970-01-01":
                prom_date = "1970-01-01"
            iso_date = f"{prom_date}T12:00:00+09:00"

            _run_git("add", file_path)
            _run_git(
                "commit",
                "-m", commit_msg,
                "--author", BOT_AUTHOR,
                "--", file_path,
                env={
                    "GIT_AUTHOR_DATE": iso_date,
                    "GIT_COMMITTER_DATE": iso_date,
                },
            )
            committed += 1

        except Exception as e:
            logger.error(f"  [{i}/{len(entries)}] Failed MST {mst} ({law_name}): {e}")
            errors += 1

        if i % 500 == 0:
            logger.info(f"Progress: {i}/{len(entries)} (committed={committed}, errors={errors})")

    logger.info(f"Law commits done: committed={committed}, errors={errors}")
    return committed


def commit_metadata(dry_run: bool = False) -> str | None:
    """Generate and commit metadata.json."""
    if dry_run:
        logger.info("[DRY-RUN] metadata commit")
        return None

    from .generate_metadata import save as save_metadata
    save_metadata()

    _run_git("add", "metadata.json", "stats.json")
    _run_git(
        "commit",
        "-m", "chore: generate metadata.json",
        "--author", BOT_AUTHOR,
    )
    commit_hash = _run_git("rev-parse", "HEAD")
    logger.info(f"Metadata committed [{commit_hash[:8]}]")
    return commit_hash


def main():
    parser = argparse.ArgumentParser(description="Rebuild git history from cache")
    parser.add_argument("--dry-run", action="store_true", help="Preview without git operations")
    parser.add_argument("--branch", default="rebuild", help="Orphan branch name (default: rebuild)")
    parser.add_argument(
        "--infra-date",
        help="ISO 8601 date for infra commit (e.g. 2026-03-30T12:00:00+09:00)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Pre-load entries before creating orphan branch
    entries = load_and_sort_entries()
    if not entries:
        logger.error("No cached entries found. Run fetch_cache.py first.")
        return

    logger.info(f"Ready to rebuild with {len(entries)} law entries")

    if not args.dry_run:
        # Save current branch
        try:
            current_branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
        except RuntimeError:
            current_branch = "main"

        create_orphan_branch(args.branch)

    # Step 1: Infrastructure commit
    logger.info("=== Step 1: Infrastructure commit ===")
    commit_infra(args.dry_run, infra_date=args.infra_date)

    # Step 2: Law commits (chronological)
    logger.info("=== Step 2: Law commits ===")
    committed = rebuild_law_commits(entries, args.dry_run)

    # Step 3: Metadata
    logger.info("=== Step 3: Metadata commit ===")
    commit_metadata(args.dry_run)

    if args.dry_run:
        logger.info(f"[DRY-RUN] Would create: 1 infra + {len(entries)} law + 1 metadata = {len(entries) + 2} commits")
    else:
        total = _run_git("rev-list", "--count", "HEAD")
        logger.info(f"Rebuild complete: {total} total commits on branch '{args.branch}'")
        logger.info(f"To finalize: git branch -M {args.branch} main && git push --force origin main")


if __name__ == "__main__":
    main()
