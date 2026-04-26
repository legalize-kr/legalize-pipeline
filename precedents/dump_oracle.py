"""Cross-language oracle dump for the composite filename grammar.

Emits one JSONL record per cached precedent XML — input fields plus the
Python-computed `expected_stem`. The Rust side (`compiler-for-precedent`)
loads this file in its `cargo test --test oracle` to assert byte-equality
against its own `compose_filename_stem`. See plan §2.5.

Schema (UTF-8, JSON Lines, NFC-normalized strings, LF newlines):
    {
      "serial":       "...",      # 판례정보일련번호
      "court":        "...",      # 법원명 (raw)
      "date":         "...",      # 선고일자 (raw 8-digit, post-Dangi-normalize)
      "caseno":       "...",      # 사건번호 (raw)
      "case_type":    "...",      # 사건종류명 (raw)
      "court_tier":   "...",      # 법원종류코드 → tier label
      "expected_stem":"..."       # compose_filename_stem(...) output
    }

Usage:
    WORKSPACE_ROOT=/path python -m precedents.dump_oracle --output /tmp/oracle.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import converter as conv
from .config import PREC_CACHE_DIR

logger = logging.getLogger(__name__)


def run(cache_dir: Path, output: Path, limit: int | None = None) -> int:
    """Scan cache and emit JSONL. Returns the number of records written."""
    xml_files = sorted(p for p in cache_dir.glob("*.xml") if p.suffix == ".xml")
    if limit is not None:
        xml_files = xml_files[:limit]
    total = len(xml_files)
    logger.info(f"Dumping oracle for {total} cached XML files → {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output.open("w", encoding="utf-8", newline="\n") as fh:
        for i, xml_file in enumerate(xml_files, 1):
            try:
                raw = xml_file.read_bytes()
                parsed = conv.parse_precedent_xml(raw)
            except Exception as e:
                logger.debug(f"Skipping {xml_file.name}: {e}")
                continue
            if parsed is None:
                continue

            serial = parsed.get("판례정보일련번호", "") or ""
            court = parsed.get("법원명", "") or ""
            date_raw = parsed.get("선고일자", "") or ""
            caseno = parsed.get("사건번호", "") or ""
            case_type = parsed.get("사건종류명", "") or ""
            court_code = parsed.get("법원종류코드", "") or ""

            judgment_date = conv.format_date(date_raw)
            expected_stem = conv.compose_filename_stem(
                court_name=court,
                judgment_date=judgment_date,
                case_no=caseno,
                serial=serial,
            )

            record = {
                "serial": serial,
                "court": court,
                "date": date_raw,
                "caseno": caseno,
                "case_type": case_type,
                "court_tier": conv.get_court_tier(court_code, court),
                "expected_stem": expected_stem,
            }
            fh.write(json.dumps(record, ensure_ascii=False))
            fh.write("\n")
            written += 1

            if i % 10000 == 0:
                logger.info(f"Oracle progress: {i}/{total}")

    logger.info(f"Oracle dump complete: {written} records → {output}")
    return written


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Dump cross-language oracle JSONL")
    parser.add_argument("--cache-dir", type=Path, default=PREC_CACHE_DIR)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    n = run(args.cache_dir, args.output, limit=args.limit)
    print(f"wrote {n} records → {args.output}")
    if n == 0:
        sys.exit(1)
