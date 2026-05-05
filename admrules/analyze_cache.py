"""Analyze administrative-rule cache shape and distribution."""

import argparse
import json
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

from .cache import CACHE_DIR
from .converter import format_date


def _text(root: ElementTree.Element, tag: str) -> str:
    return root.findtext(f".//{tag}", "") or ""


def analyze(cache_dir: Path = CACHE_DIR) -> dict:
    counts_by_type: Counter[str] = Counter()
    counts_by_ministry: Counter[str] = Counter()
    body_sources: Counter[str] = Counter()
    date_errors = 0
    total = 0
    for path in sorted(cache_dir.glob("*.xml")):
        root = ElementTree.fromstring(path.read_bytes())
        total += 1
        counts_by_type[_text(root, "행정규칙종류") or _text(root, "행정규칙종류명") or ""] += 1
        counts_by_ministry[_text(root, "소관부처명") or ""] += 1
        body = "\n".join(
            (node.text or "").strip()
            for tag in ("조문내용", "본문", "내용")
            for node in root.findall(f".//{tag}")
            if (node.text or "").strip()
        )
        body_sources["api-text" if body else "parsing-failed"] += 1
        date = format_date(_text(root, "발령일자"))
        if date and (len(date) != 10 or date[4] != "-" or date[7] != "-"):
            date_errors += 1
    return {
        "total": total,
        "by_type": dict(counts_by_type.most_common()),
        "top_ministries": dict(counts_by_ministry.most_common(30)),
        "body_sources": dict(body_sources),
        "date_errors": date_errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze administrative-rule XML cache")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    args = parser.parse_args()
    print(json.dumps(analyze(args.cache_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
