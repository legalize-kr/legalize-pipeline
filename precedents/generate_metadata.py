"""Generate metadata.json and stats.json for the precedent-kr repository.

Usage:
    python -m precedents.generate_metadata
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .config import PRECEDENT_KR_DIR

logger = logging.getLogger(__name__)

METADATA_FILE = PRECEDENT_KR_DIR / "metadata.json"
STATS_FILE = PRECEDENT_KR_DIR / "stats.json"


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
        end = text.index("---", 3)
    except ValueError:
        return None

    try:
        return yaml.safe_load(text[3:end])
    except yaml.YAMLError as e:
        logger.warning(f"Invalid YAML in {file_path}: {e}")
        return None


def generate(output_dir: Path = PRECEDENT_KR_DIR) -> tuple[dict, int]:
    """Scan precedent Markdown files and build metadata index.

    Returns (metadata dict keyed by 판례일련번호, skipped_errors count).
    Path stored as relative to output_dir so first component is court tier.
    """
    metadata: dict = {}
    skipped_errors = 0

    for md_file in sorted(output_dir.rglob("*.md")):
        # Skip the metadata/stats files themselves
        if md_file.name in ("metadata.json", "stats.json"):
            continue

        fm = parse_frontmatter(md_file)
        if fm is None:
            skipped_errors += 1
            continue

        serial = str(fm.get("판례일련번호", ""))
        if not serial:
            logger.warning(f"No 판례일련번호 in {md_file}")
            skipped_errors += 1
            continue

        # Path relative to output_dir: "{court_tier}/{case_type}/{filename}.md"
        rel_path = str(md_file.relative_to(output_dir))

        metadata[serial] = {
            "path": rel_path,
            "사건명": str(fm.get("사건명", "")),
            "사건번호": str(fm.get("사건번호", "")),
            "선고일자": str(fm.get("선고일자", "") or ""),
            "법원명": str(fm.get("법원명", "")),
            "사건종류명": str(fm.get("사건종류", "")),
            "판결유형": str(fm.get("판결유형", "") or ""),
        }

    return metadata, skipped_errors


def build_stats(metadata: dict, skipped_errors: int) -> dict:
    """Build summary statistics from metadata index.

    Court counts use court tier (first path component: 대법원/하급심/미분류).
    """
    courts: dict[str, int] = {}
    case_types: dict[str, int] = {}

    for entry in metadata.values():
        parts = entry["path"].split("/")
        tier = parts[0] if parts else "미분류"
        courts[tier] = courts.get(tier, 0) + 1

        ct = entry.get("사건종류명", "") or "기타"
        case_types[ct] = case_types.get(ct, 0) + 1

    return {
        "total": len(metadata),
        "courts": courts,
        "case_types": case_types,
        "skipped_errors": skipped_errors,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def save(output_dir: Path = PRECEDENT_KR_DIR) -> int:
    """Generate and save metadata.json and stats.json. Returns count of entries."""
    metadata, skipped_errors = generate(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    METADATA_FILE.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    stats = build_stats(metadata, skipped_errors)
    STATS_FILE.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info(f"Generated metadata.json with {len(metadata)} entries")
    logger.info(f"Generated stats.json: total={stats['total']}, courts={stats['courts']}")
    return len(metadata)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    count = save()
    print(f"Generated metadata.json with {count} entries")
