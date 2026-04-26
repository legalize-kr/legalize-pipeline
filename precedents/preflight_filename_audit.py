"""Preflight audit for the composite filename grammar.

Scans every cached precedent XML in `.cache/precedent/*.xml` and produces the
measurements required by `.omc/plans/precedent-composite-filename.md` §2:

  (1)  선고일자 결측/비ISO 카운트
  (2)  법원명 distinct values + raw→normalized mapping
  (3)  법원종류코드 ↔ 법원명 cross-table (code present, name empty)
  (4)  Composite-key collision count `N1`
  (5)  Single-key collision count `N2` (baseline)
  (6)  Cap-firing count (stem > MAX_FILENAME_STEM_BYTES)
  (7)  Separator intrusion count for `__`, `~`, `--`
  (8)  NFC mismatches (raw ≠ NFC) for 법원명/사건번호
  (9)  판례일련번호 null/dup rates
  (10) Unicode DB version (Python only — Rust counterpart in compiler-for-precedent)

Output:
  Human-readable summary on stdout + `N1`/`N2`/`SEP` decision banner.
  Optional `--report PATH` JSON dump for the verification gate.

Usage:
    WORKSPACE_ROOT=/path/to/precedent-kr python -m precedents.preflight_filename_audit
    WORKSPACE_ROOT=... python -m precedents.preflight_filename_audit \
        --report .omc/plans/preflight-report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import unicodedata
from collections import Counter as CCounter
from collections import defaultdict
from pathlib import Path

from . import converter as conv
from .config import PREC_CACHE_DIR

logger = logging.getLogger(__name__)

CANDIDATE_SEPS = ("__", "~", "--")


def _format_sample(items, n=10):
    return list(items)[:n]


def run(cache_dir: Path, limit: int | None = None) -> dict:
    """Scan cache and return an audit report dict."""
    xml_files = sorted(cache_dir.glob("*.xml"))
    # Drop the negative-cache plain-text file (handled by precedents.cache).
    xml_files = [p for p in xml_files if p.suffix == ".xml"]
    if limit is not None:
        xml_files = xml_files[:limit]
    total = len(xml_files)
    logger.info(f"Scanning {total} cached XML files in {cache_dir}")

    # Counters
    parse_errors = 0
    skipped_root = 0
    missing_date = 0
    non_iso_date = 0
    cap_fired = 0
    nfc_mismatch_court = 0
    nfc_mismatch_caseno = 0
    sep_intrusion: dict[str, int] = {sep: 0 for sep in CANDIDATE_SEPS}
    code_present_name_empty = 0

    # Distincts / mappings
    court_raw_to_normalized: dict[str, str] = {}
    code_to_names: dict[str, set[str]] = defaultdict(set)

    # Collisions
    composite_buckets: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    single_buckets: dict[tuple[str, str, str], list[str]] = defaultdict(list)

    # 판례일련번호 health
    serial_seen: CCounter[str] = CCounter()
    serial_null_or_empty = 0

    missing_date_samples: list[str] = []

    for i, xml_file in enumerate(xml_files, 1):
        try:
            raw = xml_file.read_bytes()
            parsed = conv.parse_precedent_xml(raw)
        except Exception:
            parse_errors += 1
            continue
        if parsed is None:
            skipped_root += 1
            continue

        serial = parsed.get("판례정보일련번호", "") or ""
        if not serial:
            serial_null_or_empty += 1
        else:
            serial_seen[serial] += 1

        court_raw = parsed.get("법원명", "") or ""
        court_code = parsed.get("법원종류코드", "") or ""
        case_no_raw = parsed.get("사건번호", "") or ""
        date_raw = parsed.get("선고일자", "") or ""

        # (1) date
        date_iso = conv.format_date(date_raw)
        if not date_raw:
            missing_date += 1
            if len(missing_date_samples) < 10:
                missing_date_samples.append(serial or xml_file.stem)
        elif date_iso is None:
            non_iso_date += 1

        # (2) court mapping
        if court_raw and court_raw not in court_raw_to_normalized:
            court_raw_to_normalized[court_raw] = conv.normalize_court_name(court_raw)
        # (3) code↔name
        if court_code:
            code_to_names[court_code].add(court_raw)
            if not court_raw:
                code_present_name_empty += 1

        # (8) NFC mismatches on raw inputs
        if court_raw and unicodedata.normalize("NFC", court_raw) != court_raw:
            nfc_mismatch_court += 1
        if case_no_raw and unicodedata.normalize("NFC", case_no_raw) != case_no_raw:
            nfc_mismatch_caseno += 1

        # Sanitize once for SEP intrusion + collision keys.
        # The SEP-collision assert in sanitize_case_number must NOT fire here:
        # we are explicitly measuring the population to decide which SEP to use.
        try:
            sanitized = conv._unguarded_sanitize(case_no_raw) if case_no_raw else ""
        except Exception:
            sanitized = ""
        # (7) SEP intrusion
        for sep in CANDIDATE_SEPS:
            if sep and sep in sanitized:
                sep_intrusion[sep] += 1

        court_norm = conv.normalize_court_name(court_raw) if court_raw else ""
        court_norm = unicodedata.normalize("NFC", court_norm)
        sanitized_nfc = unicodedata.normalize("NFC", sanitized)

        # (4) composite key
        if sanitized_nfc:
            composite_buckets[(court_norm, date_iso or "", sanitized_nfc)].append(serial)
        else:
            composite_buckets[(court_norm, date_iso or "", serial)].append(serial)

        # (5) single key (current baseline policy: case_type/court_tier/sanitized)
        case_type = conv.normalize_case_type(parsed.get("사건종류명", ""))
        court_tier = conv.get_court_tier(court_code, court_raw)
        single_caseno = sanitized_nfc or serial
        single_buckets[(case_type, court_tier, single_caseno)].append(serial)

        # (6) cap firing — emulate compose_filename_stem cap branch
        try:
            stem = conv.compose_filename_stem(
                court_name=court_raw,
                judgment_date=date_iso,
                case_no=case_no_raw,
                serial=serial,
            )
            naive_court = (
                conv.MISSING_COURT_SENTINEL
                if not (court_raw or "").strip()
                else conv.normalize_court_name(court_raw.strip())
            )
            naive_court = unicodedata.normalize("NFC", naive_court)
            naive_date = date_iso or conv.MISSING_DATE_SENTINEL
            if (court_raw or "").strip() and (case_no_raw or "").strip():
                naive_caseno = sanitized_nfc or serial
            else:
                naive_caseno = serial
            naive_stem = f"{naive_court}{conv.SEP}{naive_date}{conv.SEP}{naive_caseno}"
            if (
                len(naive_stem.encode("utf-8")) > conv.MAX_FILENAME_STEM_BYTES
                and stem != naive_stem
            ):
                cap_fired += 1
        except AssertionError:
            # SEP collision in the actual data — counted under sep_intrusion already.
            pass

        if i % 10000 == 0:
            logger.info(f"Audit progress: {i}/{total}")

    # Compute collision metrics
    composite_collisions = {k: v for k, v in composite_buckets.items() if len(v) > 1}
    single_collisions = {k: v for k, v in single_buckets.items() if len(v) > 1}

    n1 = sum(len(v) - 1 for v in composite_collisions.values())  # extra files dropped
    n2 = sum(len(v) - 1 for v in single_collisions.values())

    serial_dup = sum(c - 1 for c in serial_seen.values() if c > 1)
    serial_dup_samples = [s for s, c in serial_seen.items() if c > 1][:10]

    # SEP decision (Plan §1.1.1)
    if sep_intrusion["__"] == 0:
        sep_decision = "__"
        sep_rationale = "no `__` intrusion in sanitize output"
    elif sep_intrusion["~"] == 0:
        sep_decision = "~"
        sep_rationale = (
            f"`__` intrusion in {sep_intrusion['__']} records; falling back to `~`"
        )
    elif sep_intrusion["--"] == 0:
        sep_decision = "--"
        sep_rationale = (
            f"`__` and `~` both intrude; falling back to `--`"
        )
    else:
        sep_decision = "FAIL"
        sep_rationale = "all candidate separators intrude — preflight FAIL"

    report = {
        "summary": {
            "scanned_files": total,
            "parse_errors": parse_errors,
            "skipped_non_precservice_root": skipped_root,
        },
        "measurements": {
            "1_missing_date_count": missing_date,
            "1_non_iso_date_count": non_iso_date,
            "1_missing_date_samples": missing_date_samples,
            "2_distinct_courts": len(court_raw_to_normalized),
            "2_court_mapping_sample": dict(list(court_raw_to_normalized.items())[:30]),
            "3_code_present_name_empty": code_present_name_empty,
            "3_codes_with_multiple_names": {
                code: sorted(names)
                for code, names in code_to_names.items()
                if len(names) > 1
            },
            "4_composite_collision_groups": len(composite_collisions),
            "4_composite_collision_extras_N1": n1,
            "4_composite_collision_samples": _format_sample(
                [
                    {"key": list(k), "serials": v}
                    for k, v in composite_collisions.items()
                ],
                n=10,
            ),
            "5_single_collision_groups": len(single_collisions),
            "5_single_collision_extras_N2": n2,
            "5_single_collision_samples": _format_sample(
                [
                    {"key": list(k), "serials": v}
                    for k, v in single_collisions.items()
                ],
                n=10,
            ),
            "6_cap_fired_count": cap_fired,
            "7_sep_intrusion": sep_intrusion,
            "8_nfc_mismatch_court": nfc_mismatch_court,
            "8_nfc_mismatch_caseno": nfc_mismatch_caseno,
            "9_serial_null_or_empty": serial_null_or_empty,
            "9_serial_duplicate_count": serial_dup,
            "9_serial_duplicate_samples": serial_dup_samples,
            "10_python_unicode_db_version": unicodedata.unidata_version,
        },
        "decisions": {
            "SEP": sep_decision,
            "SEP_rationale": sep_rationale,
            "expected_file_count_delta": n2 - n1,
        },
    }

    return report


def _print_summary(report: dict) -> None:
    s = report["summary"]
    m = report["measurements"]
    d = report["decisions"]
    out = sys.stdout
    out.write("\n=== Preflight: composite filename grammar audit ===\n")
    out.write(
        f"Scanned: {s['scanned_files']}  "
        f"parse_errors: {s['parse_errors']}  "
        f"non-PrecService: {s['skipped_non_precservice_root']}\n"
    )
    out.write("\n[ Measurements ]\n")
    out.write(f"  (1) missing 선고일자       : {m['1_missing_date_count']}\n")
    out.write(f"      non-ISO 선고일자       : {m['1_non_iso_date_count']}\n")
    out.write(f"  (2) distinct 법원명         : {m['2_distinct_courts']}\n")
    out.write(f"  (3) 법원종류코드 with empty 법원명: {m['3_code_present_name_empty']}\n")
    out.write(
        f"  (4) composite collisions    : {m['4_composite_collision_groups']} groups, "
        f"N1={m['4_composite_collision_extras_N1']}\n"
    )
    out.write(
        f"  (5) single-key collisions   : {m['5_single_collision_groups']} groups, "
        f"N2={m['5_single_collision_extras_N2']}\n"
    )
    out.write(f"  (6) cap fired               : {m['6_cap_fired_count']}\n")
    out.write(f"  (7) SEP intrusion           : {m['7_sep_intrusion']}\n")
    out.write(
        f"  (8) NFC mismatches          : court={m['8_nfc_mismatch_court']} "
        f"caseno={m['8_nfc_mismatch_caseno']}\n"
    )
    out.write(
        f"  (9) 판례일련번호 null/empty : {m['9_serial_null_or_empty']}  "
        f"dup_count={m['9_serial_duplicate_count']}\n"
    )
    out.write(f"  (10) Python unicode DB     : {m['10_python_unicode_db_version']}\n")
    out.write("\n[ Decisions ]\n")
    out.write(f"  SEP                          : {d['SEP']}  ({d['SEP_rationale']})\n")
    out.write(
        f"  Expected file count delta    : {d['expected_file_count_delta']} "
        f"(= N2 - N1)\n"
    )
    out.write(
        f"\n  N1/N2/SEP : {m['4_composite_collision_extras_N1']} / "
        f"{m['5_single_collision_extras_N2']} / {d['SEP']}\n"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Composite filename preflight audit")
    parser.add_argument("--cache-dir", type=Path, default=PREC_CACHE_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    report = run(args.cache_dir, limit=args.limit)
    _print_summary(report)

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False),
            encoding="utf-8",
        )
        print(f"\nWrote report → {args.report}")

    if report["decisions"]["SEP"] == "FAIL":
        sys.exit(2)
