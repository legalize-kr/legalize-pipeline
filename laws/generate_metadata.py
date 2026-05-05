"""Generate metadata.json index at repository root."""

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .config import KR_DIR, LAW_REPO

logger = logging.getLogger(__name__)

METADATA_FILE = LAW_REPO / "metadata.json"
STATS_FILE = LAW_REPO / "stats.json"
ANOMALIES_FILE = LAW_REPO / "anomalies.json"


def classify_directories() -> dict:
    """Scan kr/ for child-only directories and quarantined stale files.

    Dotfiles (including '.법률.md.stale') are ignored when checking for
    'present 법률.md' AND tracked separately as quarantined. This means
    a directory with ONLY '.법률.md.stale' + '시행령.md' is classified
    child_only (stale doesn't count as present).
    """
    child_only_dirs: list[str] = []
    quarantined_stale: list[str] = []

    if not KR_DIR.exists():
        return {"child_only_dirs": [], "quarantined_stale": []}

    for law_dir in sorted(p for p in KR_DIR.iterdir() if p.is_dir()):
        files = list(law_dir.iterdir())
        non_hidden = [f for f in files if f.is_file() and not f.name.startswith(".")]
        hidden_stale = [
            f for f in files
            if f.is_file() and f.name.startswith(".") and f.name.endswith(".stale")
        ]

        basenames = {f.name for f in non_hidden}
        child_filenames = {"시행령.md", "시행규칙.md"}
        has_child = bool(basenames & child_filenames)
        has_parent = bool(basenames - child_filenames) and any(
            n.endswith(".md") for n in (basenames - child_filenames)
        )

        if has_child and not has_parent:
            child_only_dirs.append(str(law_dir.relative_to(LAW_REPO)))

        for st in hidden_stale:
            quarantined_stale.append(str(st.relative_to(LAW_REPO)))

    return {
        "child_only_dirs": child_only_dirs,
        "quarantined_stale": quarantined_stale,
    }


def parse_frontmatter(file_path: Path) -> dict | None:
    """Extract YAML frontmatter from a Markdown file."""
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(f"Cannot read {file_path}: {e}")
        return None

    if not text.startswith("---"):
        return None

    try:
        yaml_str, _body = text.removeprefix("---\n").split("\n---\n", 1)
    except ValueError:
        return None
    try:
        return yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        logger.warning(f"Invalid YAML in {file_path}: {e}")
        return None


def generate() -> dict:
    """Scan all law files and generate metadata index.

    Returns dict keyed by 법령MST with metadata for each law.

    Raises ``RuntimeError`` if two .md files share a single 법령MST: the
    MST-keyed dict would silently overwrite one entry, hiding the duplicate
    from metadata.json so that ``laws.validate`` rejects the survivor as an
    "orphan" file. Failing fast here surfaces the regression at the step
    that introduced it (e.g. ``laws.update`` writing a new canonical path
    without removing the previously qualified file) instead of one CI step
    later.
    """
    metadata = {}
    seen_paths: dict[str, str] = {}

    for md_file in sorted(KR_DIR.rglob("*.md")):
        fm = parse_frontmatter(md_file)
        if fm is None:
            continue

        mst = str(fm.get("법령MST", ""))
        if not mst:
            logger.warning(f"No 법령MST in {md_file}")
            continue

        rel_path = str(md_file.relative_to(LAW_REPO))

        if mst in seen_paths:
            raise RuntimeError(
                f"Duplicate 법령MST={mst} across files: "
                f"{seen_paths[mst]} and {rel_path}. "
                f"One file is an orphan (likely from a path migration that "
                f"failed to remove the prior file). Resolve by deleting the "
                f"stale file before regenerating metadata."
            )
        seen_paths[mst] = rel_path

        metadata[mst] = {
            "path": rel_path,
            "제목": fm.get("제목", ""),
            "법령구분": fm.get("법령구분", ""),
            "법령구분코드": fm.get("법령구분코드", ""),
            "소관부처": fm.get("소관부처", []),
            "공포일자": str(fm.get("공포일자", "")),
            "시행일자": str(fm.get("시행일자", "")),
            "상태": fm.get("상태", ""),
        }

    return metadata


def count_law_commits() -> int:
    """Count total law-related git commits (commits touching kr/ directory)."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--", "kr/"],
            capture_output=True, text=True, cwd=LAW_REPO,
        )
        if result.returncode == 0:
            return len(result.stdout.strip().splitlines())
    except FileNotFoundError:
        logger.warning("git not found, skipping commit count")
    return 0


def _count_recovery_classifications(failed: dict) -> tuple[int, int]:
    """Return (empty_history_accepted, empty_body_accepted) from the failures ledger.

    empty_history_accepted = MSTs marked failed with reason starting with
    'empty_history' that appear in the history allowlist.
    empty_body_accepted = MSTs listed in the known_empty_body allowlist.
    """
    from .empty_body_allowlist import load_allowlist as load_empty_body

    empty_body_allow = load_empty_body()
    empty_body_accepted = sum(1 for mst in empty_body_allow if mst in failed)
    empty_history_accepted = sum(
        1 for v in failed.values() if str(v.get("reason", "")).startswith("empty_history")
    )
    return empty_history_accepted, empty_body_accepted


def _count_missing_parent_with_child(child_only_dirs: list[str]) -> int:
    """Directories with 시행령/시행규칙 but no 법률.md at all."""
    missing = 0
    for rel in child_only_dirs:
        law_dir = LAW_REPO / rel
        if not law_dir.exists():
            continue
        names = {f.name for f in law_dir.iterdir() if f.is_file()}
        if "법률.md" not in names:
            missing += 1
    return missing


def build_stats(metadata: dict) -> dict:
    """Build summary statistics from metadata."""
    from collections import Counter

    from .failures import get_failed_msts, get_search_misses

    type_counts = Counter(m.get("법령구분", "") for m in metadata.values())
    dirs = classify_directories()
    failed = get_failed_msts()
    misses = get_search_misses()
    empty_history_accepted, empty_body_accepted = _count_recovery_classifications(failed)
    missing_parent_with_child = _count_missing_parent_with_child(dirs["child_only_dirs"])

    return {
        "total": len(metadata),
        "amendments": count_law_commits(),
        "types": dict(type_counts),
        "classifications": {
            "child_only_count": len(dirs["child_only_dirs"]),
            "child_only_total": len(dirs["child_only_dirs"]),
            "failed_count": len(failed),
            "search_miss_count": len(misses),
            "quarantined_stale_count": len(dirs["quarantined_stale"]),
            "empty_history_accepted": empty_history_accepted,
            "empty_body_accepted": empty_body_accepted,
            "missing_parent_with_child": missing_parent_with_child,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def save(metadata: dict | None = None) -> int:
    """Generate and save metadata.json, stats.json, and anomalies.json. Returns count of entries."""
    if metadata is None:
        metadata = generate()

    METADATA_FILE.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    stats = build_stats(metadata)
    STATS_FILE.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    from .failures import get_failed_msts, get_search_misses

    dirs = classify_directories()
    anomalies = {
        "schema_version": 1,
        "child_only_dirs": dirs["child_only_dirs"],
        "failed_msts": [{"mst": k, **v} for k, v in get_failed_msts().items()],
        "search_misses": [{"name": k, **v} for k, v in get_search_misses().items()],
        "quarantined_stale": dirs["quarantined_stale"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    ANOMALIES_FILE.write_text(
        json.dumps(anomalies, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info(f"Generated metadata.json with {len(metadata)} entries")
    logger.info(f"Generated stats.json: {stats}")
    logger.info(
        f"Generated anomalies.json: child_only={len(dirs['child_only_dirs'])}, "
        f"failed={len(anomalies['failed_msts'])}, "
        f"search_misses={len(anomalies['search_misses'])}, "
        f"quarantined={len(dirs['quarantined_stale'])}"
    )
    return len(metadata)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = save()
    print(f"Generated metadata.json with {count} entries")
