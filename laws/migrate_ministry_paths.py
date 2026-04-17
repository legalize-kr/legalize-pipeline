"""Migrate existing fragmented 시행규칙 files to canonical paths.

Usage:
    cd /opt/data/legalize-kr/legalize-pipeline
    python -m laws.migrate_ministry_paths           # dry-run (default)
    python -m laws.migrate_ministry_paths --execute # apply changes

Background:
    Before the 법령ID-based path fix, ministry renames caused the same law
    to be stored as multiple files: 시행규칙(안전행정부령).md + 시행규칙(행정안전부령).md.
    This script consolidates those pairs into the single canonical path by
    keeping the file with the latest 공포일자 and removing the rest.
"""

import argparse
import logging
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import KR_DIR, WORKSPACE_ROOT

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(message)s",
)


@dataclass
class MigrationOp:
    law_id: str
    winner: Path           # file to keep (latest 공포일자)
    losers: list[Path]     # files to delete
    canonical: Path        # target canonical path
    needs_rename: bool     # winner is not already at canonical path
    lossy: bool = False    # True if loser body differs significantly from winner


@dataclass
class MigrationReport:
    ops: list[MigrationOp] = field(default_factory=list)
    cross_dir_cases: list[tuple[str, list[Path]]] = field(default_factory=list)
    skipped_empty_id: int = 0


def _read_frontmatter(path: Path) -> dict:
    """Parse YAML frontmatter from a Markdown file."""
    try:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}
        return yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}


def _body_lines(path: Path) -> list[str]:
    """Return body lines (after frontmatter) of a Markdown file."""
    try:
        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].splitlines()
        return text.splitlines()
    except Exception:
        return []


def _lossy_check(winner: Path, loser: Path, ratio: float = 0.3) -> bool:
    """Return True if winner has significantly less content than loser.

    Law amendments change content over time — content differences between
    old and new versions are expected and NOT data loss.  We only flag when
    the winner (newest version) has fewer than `ratio` * loser's line count,
    which suggests the winner might be a stub or incomplete entry.
    """
    winner_count = sum(1 for l in _body_lines(winner) if l.strip())
    loser_count = sum(1 for l in _body_lines(loser) if l.strip())
    if loser_count == 0:
        return False
    return winner_count < loser_count * ratio


def _canonical_path(group: str, filename: str) -> Path:
    """Unqualified canonical path relative to WORKSPACE_ROOT."""
    return WORKSPACE_ROOT / "kr" / group / f"{filename}.md"


def _parse_group_filename(rel_path: str) -> tuple[str, str]:
    """Extract (group, filename_without_ext) from a kr/... relative path."""
    parts = Path(rel_path).parts
    if len(parts) < 3:
        return "", ""
    group = parts[1]
    stem = Path(parts[2]).stem
    # Strip qualifier like (안전행정부령)
    base = stem.split("(")[0]
    return group, base


def scan(kr_root: Path = KR_DIR) -> MigrationReport:
    """Scan kr/ directory and build migration ops grouped by 법령ID."""
    by_law_id: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
    report = MigrationReport()

    for md in kr_root.rglob("*.md"):
        fm = _read_frontmatter(md)
        law_id = fm.get("법령ID", "")
        if not law_id:
            report.skipped_empty_id += 1
            continue
        by_law_id[law_id].append((md, fm))

    for law_id, entries in by_law_id.items():
        if len(entries) == 1:
            continue

        # Split by parent directory
        by_dir: dict[Path, list[tuple[Path, dict]]] = defaultdict(list)
        for path, fm in entries:
            by_dir[path.parent].append((path, fm))

        # Cross-directory: law name change (separate report, no auto-merge)
        if len(by_dir) > 1:
            report.cross_dir_cases.append((law_id, [p for p, _ in entries]))
            continue

        # Same-directory fragmentation: consolidate
        dir_entries = list(by_dir.values())[0]
        if len(dir_entries) <= 1:
            continue

        # Pick winner by latest 공포일자, then latest 법령MST as tiebreaker.
        # PyYAML may parse YYYY-MM-DD as datetime.date — normalize to str.
        def sort_key(item: tuple[Path, dict]):
            fm = item[1]
            d = fm.get("공포일자", "") or ""
            date_str = str(d) if d else ""
            return (date_str, fm.get("법령MST", 0) or 0)

        dir_entries.sort(key=sort_key, reverse=True)
        winner_path, winner_fm = dir_entries[0]
        loser_paths = [p for p, _ in dir_entries[1:]]

        # Determine canonical (unqualified) path
        group, base = _parse_group_filename(winner_path.relative_to(WORKSPACE_ROOT).as_posix())
        canonical = _canonical_path(group, base)

        needs_rename = winner_path != canonical

        # Check if any loser has significant unique content
        lossy = any(_lossy_check(winner_path, lp) for lp in loser_paths)

        report.ops.append(MigrationOp(
            law_id=law_id,
            winner=winner_path,
            losers=loser_paths,
            canonical=canonical,
            needs_rename=needs_rename,
            lossy=lossy,
        ))

    return report


def report_dry_run(report: MigrationReport) -> None:
    """Print a human-readable dry-run report."""
    consolidate = [op for op in report.ops if not op.lossy]
    manual = [op for op in report.ops if op.lossy]

    print(f"\n{'='*60}")
    print(f"MIGRATION DRY-RUN REPORT")
    print(f"{'='*60}")
    print(f"총 파편화 법령: {len(report.ops)}건")
    print(f"  자동 통합 가능: {len(consolidate)}건")
    print(f"  수동 검토 필요 (winner 본문이 loser의 30% 미만): {len(manual)}건")
    print(f"  빈 법령ID 건너뜀: {report.skipped_empty_id}건")
    print(f"  법령명 변경 (다른 디렉토리): {len(report.cross_dir_cases)}건\n")

    if manual:
        print("[ 수동 검토 필요 (REQUIRES_MANUAL_REVIEW) ]")
        for op in manual:
            print(f"  법령ID {op.law_id}:")
            print(f"    winner  : {op.winner.relative_to(WORKSPACE_ROOT)}")
            for lp in op.losers:
                print(f"    loser   : {lp.relative_to(WORKSPACE_ROOT)}")
        print()

    if consolidate:
        print("[ 자동 통합 예정 ]")
        for op in consolidate[:20]:
            if op.needs_rename:
                print(f"  {op.winner.relative_to(WORKSPACE_ROOT)} -> {op.canonical.relative_to(WORKSPACE_ROOT)}")
            else:
                print(f"  {op.canonical.relative_to(WORKSPACE_ROOT)} (loser {len(op.losers)}개 삭제)")
        if len(consolidate) > 20:
            print(f"  ... 외 {len(consolidate)-20}건")
        print()

    if report.cross_dir_cases:
        print("[ 법령명 변경 케이스 (별도 처리 필요) ]")
        for law_id, paths in report.cross_dir_cases[:10]:
            print(f"  법령ID {law_id}:")
            for p in paths:
                print(f"    {p.relative_to(WORKSPACE_ROOT)}")
        print()

    print("실행하려면: python -m laws.migrate_ministry_paths --execute")


def apply_ops(report: MigrationReport, force_lossy: bool = False) -> None:
    """Apply migration: rename winners to canonical path, git rm losers."""
    # Verify no staged/modified tracked files (untracked files are OK)
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=WORKSPACE_ROOT,
        capture_output=True,
        text=True,
    )
    dirty = [l for l in result.stdout.splitlines() if not l.startswith("??")]
    if dirty:
        logger.error("Data repo has uncommitted changes. Commit or stash first.")
        sys.exit(1)

    to_process = report.ops if force_lossy else [op for op in report.ops if not op.lossy]
    skipped_lossy = [op for op in report.ops if op.lossy and not force_lossy]

    if skipped_lossy:
        logger.warning(f"{len(skipped_lossy)}건 본문 차이로 건너뜀 (--force-merge-lossy로 강제 적용)")

    renamed = 0
    removed = 0

    for op in to_process:
        try:
            # Rename winner to canonical if needed.
            # Use `git mv -f` so the source path's deletion is staged together
            # with the destination's addition (a plain os.rename + git add would
            # leave the source as an unstaged deletion, dropping it from the commit).
            if op.needs_rename:
                op.canonical.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    ["git", "mv", "-f",
                     str(op.winner.relative_to(WORKSPACE_ROOT)),
                     str(op.canonical.relative_to(WORKSPACE_ROOT))],
                    cwd=WORKSPACE_ROOT, check=True, capture_output=True,
                )
                renamed += 1
                logger.info(f"  renamed: {op.winner.name} -> {op.canonical.name}")

            # Remove losers (skip if loser == canonical — already overwritten by winner rename)
            for lp in op.losers:
                if lp == op.canonical:
                    continue
                if lp.exists():
                    subprocess.run(
                        ["git", "rm", "--force", str(lp.relative_to(WORKSPACE_ROOT))],
                        cwd=WORKSPACE_ROOT, check=True, capture_output=True,
                    )
                    removed += 1
                    logger.info(f"  removed: {lp.relative_to(WORKSPACE_ROOT)}")

        except Exception as e:
            logger.error(f"  Failed for 법령ID {op.law_id}: {e}")

    # Single commit for all changes
    n = renamed + removed
    if n > 0:
        msg = f"migration: 부처명 정규화 — {len(to_process)}건 법령 경로 통합 (rename={renamed}, rm={removed})"
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=WORKSPACE_ROOT, check=True,
        )
        logger.info(f"\n완료: {renamed}건 이동, {removed}건 삭제 → 커밋 완료")
    else:
        logger.info("변경 사항 없음.")


def main() -> None:
    parser = argparse.ArgumentParser(description="부처명 정규화 마이그레이션")
    parser.add_argument("--execute", action="store_true", help="실제 적용 (기본: dry-run)")
    parser.add_argument("--force-merge-lossy", action="store_true",
                        help="본문 차이가 있는 쌍도 강제 통합")
    args = parser.parse_args()

    report = scan()

    if not args.execute:
        report_dry_run(report)
        return

    logger.info(f"마이그레이션 시작: {len(report.ops)}건")
    apply_ops(report, force_lossy=args.force_merge_lossy)


if __name__ == "__main__":
    main()
