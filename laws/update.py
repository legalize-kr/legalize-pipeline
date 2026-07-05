"""Incremental updater for new/amended laws.

Uses search API to find recently changed laws, then fetches and commits
only the new versions directly (no full history traversal).

Usage (from legalize-pipeline root):
    python -m laws.update                    # Update recent laws (default 14 days)
    python -m laws.update --days 30          # Look back 30 days
    python -m laws.update --law-type 법률    # Only 법률
    python -m laws.update --dry-run          # Preview only
"""

import argparse
import logging
import subprocess
from datetime import datetime, timedelta

import yaml

from .api_client import get_law_detail, get_law_history, search_laws
from .audit_history_vs_git import DEFAULT_RECENT_DAYS, audit as audit_history_vs_git
from .checkpoint import get_last_update, get_processed_msts, mark_processed, set_last_update
from .config import KR_DIR, LAW_API_KEY
from .converter import (
    entry_sort_key,
    format_date,
    get_group_and_filename,
    get_law_path,
    law_to_markdown,
    reset_path_registry,
)
from .git_engine import commit_law
from core.git_engine import commit_exists
from .import_laws import build_commit_msg

logger = logging.getLogger(__name__)


def _markdown_law_id(md_file) -> str | None:
    try:
        text = md_file.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    try:
        yaml_str, _body = text.removeprefix("---\n").split("\n---\n", 1)
    except ValueError:
        return None
    try:
        fm = yaml.safe_load(yaml_str)
    except yaml.YAMLError:
        return None
    if isinstance(fm, dict):
        return str(fm.get("법령ID", ""))
    return None


def _find_existing_path_for_law_id(law_name: str, law_type: str, law_id: str) -> str | None:
    """Return the relative path of an existing on-disk file matching ``law_id``.

    ``update.py`` runs with an empty ``PathRegistry`` every invocation, so
    ``get_law_path`` cannot honor the compiler's first-write-wins reverse
    index across runs. Without this lookup, a law whose canonical path was
    previously qualified (e.g. ``법률(법률).md``) or whose ``법령구분`` shifted
    (e.g. ``기획재정부령`` → ``재정경제부령``), or whose title changes enough
    to compute a new group directory, gets a *new* file written at the
    freshly computed canonical path, while the old file is left behind as an
    orphan. ``laws.validate`` then fails because two files share one MST and
    only one survives ``generate_metadata``'s MST-keyed dict.

    The fix mirrors compiler::PathRegistry's ``_by_id`` semantics by
    consulting the file system: prefer the expected group directory for the
    common law-type rename case, then fall back to all ``kr/**/*.md`` files
    for law title renames that move the group directory.
    """
    if not law_id:
        return None

    group, _ = get_group_and_filename(law_name, law_type)
    group_dir = KR_DIR / group
    candidates = []
    if group_dir.is_dir():
        candidates.extend(sorted(group_dir.glob("*.md")))
    candidates.extend(
        md_file
        for md_file in sorted(KR_DIR.rglob("*.md"))
        if md_file.parent != group_dir
    )

    for md_file in candidates:
        if _markdown_law_id(md_file) == str(law_id):
            return str(md_file.relative_to(KR_DIR.parent))

    return None


def _current_law_path(law_name: str, law_type: str, law_id: str) -> str:
    """Return the natural current-name path, avoiding different-ID collisions."""

    group, filename = get_group_and_filename(law_name, law_type)
    path = f"kr/{group}/{filename}.md"
    abs_path = KR_DIR.parent / path
    if abs_path.exists():
        existing_id = _markdown_law_id(abs_path)
        if existing_id and existing_id != str(law_id):
            return f"kr/{group}/{filename}({law_type}).md"
        if existing_id is None and law_id:
            return f"kr/{group}/{filename}({law_type}).md"
    return path


def _resolve_write_path_for_law(
    law_name: str,
    law_type: str,
    law_id: str,
    *,
    dry_run: bool = False,
) -> tuple[str, list[str]]:
    """Return write path and extra paths needed to commit path migration.

    Existing same-ID files are moved to the current-name path instead of
    preserving stale title/ministry paths. This prevents future path drift
    like 법률 files remaining under a pre-rename directory while 시행령 and
    시행규칙 are written under the current directory.
    """

    if not law_id:
        return get_law_path(law_name, law_type, law_id), []

    existing_path = _find_existing_path_for_law_id(law_name, law_type, law_id)
    current_path = _current_law_path(law_name, law_type, law_id)
    if not existing_path or existing_path == current_path:
        return current_path, []

    old_abs = KR_DIR.parent / existing_path
    new_abs = KR_DIR.parent / current_path
    logger.info("Moving law_id=%s path: %s -> %s", law_id, existing_path, current_path)
    if not dry_run:
        new_abs.parent.mkdir(parents=True, exist_ok=True)
        if new_abs.exists():
            subprocess.run(
                ["git", "rm", "--force", existing_path],
                cwd=KR_DIR.parent,
                check=True,
                capture_output=True,
                text=True,
            )
        else:
            subprocess.run(
                ["git", "mv", "-f", existing_path, current_path],
                cwd=KR_DIR.parent,
                check=True,
                capture_output=True,
                text=True,
            )
    elif old_abs.exists():
        logger.info("[DRY-RUN] would move %s -> %s", existing_path, current_path)
    return current_path, [existing_path]


def _commit_exists_for_mst(mst: str) -> bool:
    return commit_exists(KR_DIR.parent, f"법령MST: {mst}")


def _append_missing_cache_history_msts(
    all_laws: list[dict],
    seen_msts: set[str],
    *,
    recent_days: int = DEFAULT_RECENT_DAYS,
) -> int:
    """Append valid-detail history MSTs that are cached but absent from Git."""

    report = audit_history_vs_git(recent_days=recent_days)
    added = 0
    for record in report.missing_in_git_with_valid_detail:
        if not record.mst or record.mst in seen_msts:
            continue
        all_laws.append({
            "법령일련번호": record.mst,
            "법령명한글": record.law_name,
            "제개정구분명": record.amendment,
            "법령구분": record.law_type,
            "공포일자": record.promulgation_date,
            "공포번호": record.promulgation_number,
            "시행일자": "",
        })
        seen_msts.add(record.mst)
        added += 1
    return added


def update(
    days: int = 14,
    law_type_filter: str | None = None,
    dry_run: bool = False,
    max_pages: int = 50,
    augment_history: bool = True,
    backfill_discovered_history: bool = True,
    backfill_missing_from_cache: bool = False,
    cache_backfill_recent_days: int = DEFAULT_RECENT_DAYS,
) -> int:
    """Query API for recently amended laws and import their latest versions."""
    if not LAW_API_KEY:
        logger.error("No API key (LAW_OC) configured. Cannot update.")
        return 0

    reset_path_registry()

    last = get_last_update()
    fallback_since = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    since = min(last.replace("-", ""), fallback_since) if last else fallback_since
    today = datetime.now().strftime("%Y%m%d")

    logger.info(f"Searching amendments from {since} to {today}")

    # Collect all search results with their MSTs.
    # Bounded-iteration invariant: abort if pagination exceeds max_pages to
    # catch pagination regressions loudly (mirror of fetch_cache.py's invariant).
    all_laws: list[dict] = []
    page = 1
    while True:
        result = search_laws(query="", page=page, display=100, date_from=since, date_to=today)
        all_laws.extend(result["laws"])
        if page * 100 >= result["totalCnt"]:
            break
        if page >= max_pages:
            raise RuntimeError(
                f"laws.update pagination exceeded max_pages={max_pages} "
                f"(totalCnt={result['totalCnt']}, collected={len(all_laws)}). "
                f"Likely pagination regression, unexpected window size, or backfill — "
                f"raise --max-pages explicitly if this is intentional."
            )
        page += 1

    # lsHistory augmentation: lawSearch.do omits 타법개정 MSTs (whose 제개정구분 is
    # empty on the server), so for each law surfaced by the search, refresh its
    # amendment history from lsHistory and pick up any sibling MSTs that fall in
    # the [since, today] window. When a newly surfaced law reveals older history
    # whose commit is absent, backfill those MSTs too; otherwise window-bounded
    # daily updates can permanently miss historical entries discovered late.
    if augment_history:
        seen_msts = {law.get("법령일련번호", "") for law in all_laws}
        unique_names = {law.get("법령명한글", "") for law in all_laws if law.get("법령명한글")}
        added = 0
        backfilled = 0
        history_errors = 0
        for name in sorted(unique_names):
            try:
                history = get_law_history(name, refresh=True)
            except Exception as e:
                logger.warning(f"lsHistory refresh failed for {name}: {e}")
                history_errors += 1
                continue
            for entry in history:
                mst = entry.get("법령일련번호", "")
                prom = entry.get("공포일자", "")
                if not mst or mst in seen_msts:
                    continue
                in_window = since <= prom <= today
                backfill_missing = (
                    backfill_discovered_history
                    and not in_window
                    and not _commit_exists_for_mst(mst)
                )
                if not in_window and not backfill_missing:
                    continue
                all_laws.append({
                    "법령일련번호": mst,
                    "법령명한글": entry.get("법령명한글", ""),
                    "제개정구분명": entry.get("제개정구분명", ""),
                    "공포일자": prom,
                    "공포번호": entry.get("공포번호", ""),
                    "시행일자": entry.get("시행일자", ""),
                })
                seen_msts.add(mst)
                if backfill_missing:
                    backfilled += 1
                else:
                    added += 1
        logger.info(
            f"lsHistory augmentation: +{added} window MSTs, +{backfilled} backfill MSTs "
            f"from {len(unique_names)} laws "
            f"(errors={history_errors})"
        )

    if backfill_missing_from_cache:
        seen_msts = {law.get("법령일련번호", "") for law in all_laws}
        backfilled = _append_missing_cache_history_msts(
            all_laws,
            seen_msts,
            recent_days=cache_backfill_recent_days,
        )
        logger.info(
            f"cache history backfill: +{backfilled} valid-detail MSTs absent from Git"
        )

    # Checkpoints are only a cursor for the search window. Commit existence
    # must come from Git so a freshly cloned/generated result repo converges
    # even if the local checkpoint is stale or ahead.
    new_laws = [law for law in all_laws if law["법령일련번호"]]
    new_laws.sort(key=lambda x: entry_sort_key(
        x.get("공포일자", ""),
        x.get("법령명한글", ""),
        x.get("공포번호", ""),
        x.get("법령일련번호", ""),
    ))

    logger.info(f"Found {len(all_laws)} results, {len(new_laws)} commit candidates")

    committed = 0
    errors = 0

    for i, law in enumerate(new_laws, 1):
        mst = law["법령일련번호"]
        name = law.get("법령명한글", "")

        file_path = None
        try:
            detail = get_law_detail(mst)
            meta = detail["metadata"]
            law_type = meta.get("법령구분", "")

            if law_type_filter and law_type_filter != law_type:
                continue

            fetched_name = meta.get("법령명한글", name)
            law_id = meta.get("법령ID", "")
            file_path, extra_commit_paths = _resolve_write_path_for_law(
                fetched_name,
                law_type,
                law_id,
                dry_run=dry_run,
            )
            abs_path = KR_DIR.parent / file_path

            meta["제개정구분"] = law.get("제개정구분명", meta.get("제개정구분", ""))
            if not meta.get("공포번호"):
                meta["공포번호"] = law.get("공포번호", "")

            prom_date = format_date(meta.get("공포일자", ""))

            if dry_run:
                logger.info(f"  [{i}/{len(new_laws)}] [DRY-RUN] MST={mst} {prom_date} {fetched_name} -> {file_path}")
                continue

            content = law_to_markdown(detail)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")

            commit_msg = build_commit_msg(fetched_name, law_type, mst, meta)
            if not prom_date or len(prom_date) != 10:
                prom_date = "2000-01-01"

            result = commit_law(
                file_path,
                commit_msg,
                prom_date,
                mst,
                skip_dedup=False,
                extra_paths=extra_commit_paths,
            )
            if result:
                mark_processed(mst)
                committed += 1
                logger.info(f"  [{i}/{len(new_laws)}] Committed MST={mst} {prom_date} {fetched_name}")

        except ValueError as e:  # empty body (P1)
            from .failures import log_failure, mark_failed, mark_failed_and_quarantine
            log_failure("update", str(mst), name, e)
            if file_path is not None:
                mark_failed_and_quarantine(
                    mst=str(mst), reason="empty_body", detail=str(e),
                    path=KR_DIR.parent / file_path,
                    step="update", law_name=name,
                )
            else:
                mark_failed(mst=str(mst), reason="empty_body", detail=str(e),
                            step="update", law_name=name)
            errors += 1
        except Exception as e:  # all other failures (P3)
            from .failures import log_failure, classify, mark_failed
            log_failure("update", str(mst), name, e)
            mark_failed(mst=str(mst), reason=classify(e), detail=str(e),
                        step="update", law_name=name)
            errors += 1

        if i % 50 == 0:
            logger.info(f"Progress: {i}/{len(new_laws)} (committed={committed}, errors={errors})")

    if not dry_run:
        set_last_update(format_date(today))

    logger.info(f"Update done: committed={committed}, errors={errors}")
    return committed


def main():
    parser = argparse.ArgumentParser(description="Incremental law updater")
    parser.add_argument("--days", type=int, default=14, help="Look back N days (default: 14)")
    parser.add_argument("--law-type", help="Filter by 법령구분 (e.g., 법률)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help=(
            "Abort if pagination exceeds N pages (100 items/page). "
            "Default 50 = 5000 items, sized for daily cron. "
            "Raise for backfill (e.g. --days 3650 --max-pages 500)."
        ),
    )
    parser.add_argument(
        "--no-augment-history",
        action="store_true",
        help=(
            "Disable the lsHistory augmentation pass that catches 타법개정 MSTs "
            "missed by lawSearch.do. Only use when troubleshooting — default on."
        ),
    )
    parser.add_argument(
        "--no-backfill-discovered-history",
        action="store_true",
        help=(
            "Do not import older missing MSTs discovered while refreshing histories "
            "for laws in the update window. Default on to prevent historical gaps."
        ),
    )
    parser.add_argument(
        "--backfill-missing-from-cache",
        action="store_true",
        help=(
            "Audit cached history against Git and import every missing MST that "
            "already has valid detail XML, even if lawSearch does not surface it."
        ),
    )
    parser.add_argument(
        "--cache-backfill-recent-days",
        type=int,
        default=DEFAULT_RECENT_DAYS,
        help=(
            "Recent-days window used only for cache-backfill audit reporting "
            f"(default: {DEFAULT_RECENT_DAYS})."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    committed = update(
        days=args.days,
        law_type_filter=args.law_type,
        dry_run=args.dry_run,
        max_pages=args.max_pages,
        augment_history=not args.no_augment_history,
        backfill_discovered_history=not args.no_backfill_discovered_history,
        backfill_missing_from_cache=args.backfill_missing_from_cache,
        cache_backfill_recent_days=args.cache_backfill_recent_days,
    )

    if not args.dry_run:
        from .generate_metadata import save as save_metadata
        save_metadata()

    logger.info(f"Update complete: {committed} laws committed")


if __name__ == "__main__":
    main()
