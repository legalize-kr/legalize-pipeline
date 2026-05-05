"""Generate lightweight ordinance stats by scanning Markdown frontmatter."""

import argparse
import json
from collections import Counter
from pathlib import Path

import yaml

from .config import ORDINANCE_REPO


def scan_stats(repo_dir: Path = ORDINANCE_REPO) -> dict:
    by_region: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    total = 0
    for path in repo_dir.rglob("본문.md"):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        try:
            yaml_text, _ = text[4:].split("\n---\n", 1)
        except ValueError:
            continue
        fm = yaml.safe_load(yaml_text) or {}
        split = fm.get("지자체구분") or fm.get("jurisdiction_split") or {}
        by_region[split.get("광역", "미상")] += 1
        by_type[fm.get("자치법규종류", fm.get("ordinance_type", "미상"))] += 1
        total += 1
    return {"total": total, "by_region": dict(sorted(by_region.items())), "by_type": dict(sorted(by_type.items()))}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ordinance stats from a working tree")
    parser.add_argument("--repo", type=Path, default=ORDINANCE_REPO)
    args = parser.parse_args()
    print(json.dumps(scan_stats(args.repo), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
