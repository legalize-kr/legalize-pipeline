"""Audit cached law history MSTs against legalize-kr Git commit messages."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import cache
from .config import LAW_REPO

DEFAULT_RECENT_DAYS = 365
MST_RE = re.compile(r"법령MST:\s*(\d+)")


@dataclass(frozen=True)
class HistoryRecord:
    """One unique MST found in .cache/history."""

    mst: str
    law_name: str
    amendment: str
    law_type: str
    promulgation_date: str
    promulgation_number: str
    history_file: str


@dataclass(frozen=True)
class GitRecord:
    """One Git commit containing a 법령MST marker."""

    mst: str
    commit_hash: str
    commit_date: str
    subject: str
    law_name: str
    amendment: str
    law_type: str
    promulgation_date: str
    promulgation_number: str


@dataclass(frozen=True)
class DetailMetadata:
    """Small metadata slice parsed from cached detail XML."""

    law_name: str
    law_id: str
    law_type: str
    promulgation_date: str
    promulgation_number: str
    amendment: str


@dataclass(frozen=True)
class MissingHistoryMst:
    """A history MST that has no matching 법령MST commit."""

    mst: str
    law_name: str
    amendment: str
    law_type: str
    promulgation_date: str
    history_file: str
    detail_status: str


@dataclass(frozen=True)
class CommitMetadataMismatch:
    """A history/cache field that is not reflected in the matching Git commit."""

    mst: str
    field: str
    expected: str
    actual: str
    commit_hash: str
    history_file: str


@dataclass(frozen=True)
class AuditReport:
    """History-vs-Git audit result."""

    history_names: int
    historical_msts: int
    git_msts: int
    missing_in_git_with_valid_detail: list[MissingHistoryMst]
    missing_in_git_without_valid_detail: list[MissingHistoryMst]
    commit_metadata_mismatches: list[CommitMetadataMismatch]
    commit_metadata_checked: bool
    recent_cache_ahead: list[MissingHistoryMst]
    long_term_missing: list[MissingHistoryMst]
    recent_days: int
    cutoff_date: str


def _sort_mst_key(value: str) -> tuple[int, str]:
    try:
        return (0, f"{int(value):020d}")
    except ValueError:
        return (1, value)


def _sort_missing_key(record: MissingHistoryMst) -> tuple[str, tuple[int, str]]:
    return (record.promulgation_date or "99999999", _sort_mst_key(record.mst))


def _load_history_records(cache_dir: Path) -> tuple[dict[str, HistoryRecord], int]:
    history_dir = cache_dir / "history"
    if not history_dir.exists():
        return {}, 0

    records: dict[str, HistoryRecord] = {}
    history_names = 0
    for path in sorted(history_dir.glob("*.json")):
        history_names += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, list):
            continue
        for entry in data:
            if not isinstance(entry, dict):
                continue
            mst = str(entry.get("법령일련번호", "")).strip()
            if not mst:
                continue
            record = HistoryRecord(
                mst=mst,
                law_name=str(entry.get("법령명한글", "")),
                amendment=str(entry.get("제개정구분명", "")),
                law_type=str(entry.get("법령구분", "")),
                promulgation_date=str(entry.get("공포일자", "")),
                promulgation_number=str(entry.get("공포번호", "")),
                history_file=path.name,
            )
            current = records.get(mst)
            if current is None or (
                not current.promulgation_date and record.promulgation_date
            ):
                records[mst] = record
    return records, history_names


def _parse_subject(subject: str) -> tuple[str, str, str]:
    law_type = ""
    law_name = ""
    amendment = ""
    if ": " in subject:
        law_type, rest = subject.split(": ", 1)
    else:
        rest = subject
    match = re.fullmatch(r"(.+) \(([^()]*)\)", rest)
    if match:
        law_name = match.group(1)
        amendment = match.group(2)
    else:
        law_name = rest
    return law_type, law_name, amendment


def _message_field(body: str, field: str) -> str:
    match = re.search(rf"^{re.escape(field)}:\s*(.*?)\s*$", body, re.MULTILINE)
    return match.group(1) if match else ""


def _git_commit_records(repo_dir: Path) -> dict[str, GitRecord]:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "log", "--all", "--format=%H%x00%cI%x00%B%x1e"],
        check=True,
        capture_output=True,
        text=True,
    )
    records: dict[str, GitRecord] = {}
    for raw_record in result.stdout.split("\x1e"):
        raw_record = raw_record.strip("\n")
        if not raw_record:
            continue
        parts = raw_record.split("\x00", 2)
        if len(parts) != 3:
            continue
        commit_hash, commit_date, body = parts
        msts = MST_RE.findall(body)
        if not msts:
            continue
        subject = body.splitlines()[0] if body.splitlines() else ""
        law_type, law_name, amendment = _parse_subject(subject)
        for mst in msts:
            records.setdefault(
                mst,
                GitRecord(
                    mst=mst,
                    commit_hash=commit_hash,
                    commit_date=commit_date[:10],
                    subject=subject,
                    law_name=law_name,
                    amendment=amendment,
                    law_type=law_type,
                    promulgation_date=_message_field(body, "공포일자"),
                    promulgation_number=_message_field(body, "공포번호"),
                ),
            )
    return records


def _compact_date_to_iso(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    return ""


def _expected_git_date(promulgation_date: str) -> str:
    iso_date = _compact_date_to_iso(promulgation_date)
    return max(iso_date, "1970-01-01") if iso_date else ""


def _normalize_law_name(value: str) -> str:
    return re.sub(r"\s+", "", value.strip())


def _normalize_promulgation_number(value: str) -> str:
    return value.replace("제", "").replace("호", "").replace(" ", "").strip()


def _append_mismatch(
    mismatches: list[CommitMetadataMismatch],
    history: HistoryRecord,
    git_record: GitRecord,
    field: str,
    expected: str,
    actual: str,
) -> None:
    if expected == actual:
        return
    mismatches.append(
        CommitMetadataMismatch(
            mst=history.mst,
            field=field,
            expected=expected,
            actual=actual,
            commit_hash=git_record.commit_hash,
            history_file=history.history_file,
        )
    )


def _commit_metadata_mismatches(
    history_records: dict[str, HistoryRecord],
    git_records: dict[str, GitRecord],
    detail_dir: Path,
) -> list[CommitMetadataMismatch]:
    mismatches: list[CommitMetadataMismatch] = []
    for mst, history in sorted(
        history_records.items(),
        key=lambda item: _sort_mst_key(item[0]),
    ):
        git_record = git_records.get(mst)
        if git_record is None:
            continue
        detail_status, detail = _detail_metadata(detail_dir, mst)
        if detail_status != "valid_detail" or detail is None:
            continue

        expected_commit_date = _expected_git_date(detail.promulgation_date)
        if expected_commit_date:
            _append_mismatch(
                mismatches,
                history,
                git_record,
                "commit_date",
                expected_commit_date,
                git_record.commit_date,
            )

        expected_promulgation_date = _compact_date_to_iso(detail.promulgation_date)
        if expected_promulgation_date:
            _append_mismatch(
                mismatches,
                history,
                git_record,
                "공포일자",
                expected_promulgation_date,
                git_record.promulgation_date,
            )

        expected_number = _normalize_promulgation_number(detail.promulgation_number)
        actual_number = _normalize_promulgation_number(git_record.promulgation_number)
        if expected_number:
            _append_mismatch(
                mismatches,
                history,
                git_record,
                "공포번호",
                expected_number,
                actual_number,
            )

        expected_amendment = history.amendment or detail.amendment
        if expected_amendment:
            _append_mismatch(
                mismatches,
                history,
                git_record,
                "제개정구분",
                expected_amendment,
                git_record.amendment,
            )

        if detail.law_type:
            _append_mismatch(
                mismatches,
                history,
                git_record,
                "법령구분",
                detail.law_type,
                git_record.law_type,
            )

        expected_name = _normalize_law_name(detail.law_name)
        actual_name = _normalize_law_name(git_record.law_name)
        if expected_name:
            _append_mismatch(
                mismatches,
                history,
                git_record,
                "법령명",
                expected_name,
                actual_name,
            )
    return mismatches


def _detail_metadata(detail_dir: Path, mst: str) -> tuple[str, DetailMetadata | None]:
    path = detail_dir / f"{mst}.xml"
    if not path.exists():
        return "missing_detail", None
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return "invalid_detail_xml", None

    metadata = DetailMetadata(
        law_name=root.findtext(".//법령명_한글", "") or "",
        law_id=root.findtext(".//법령ID", "") or "",
        law_type=root.findtext(".//법종구분", "") or "",
        promulgation_date=root.findtext(".//공포일자", "") or "",
        promulgation_number=root.findtext(".//공포번호", "") or "",
        amendment=root.findtext(".//제개정구분명", "") or "",
    )
    if not metadata.law_name or not metadata.law_id or not metadata.law_type:
        return "invalid_detail_meta", None
    return "valid_detail", metadata


def _missing_record(
    history: HistoryRecord,
    detail_status: str,
    detail: DetailMetadata | None,
) -> MissingHistoryMst:
    return MissingHistoryMst(
        mst=history.mst,
        law_name=history.law_name or (detail.law_name if detail else ""),
        amendment=history.amendment,
        law_type=history.law_type or (detail.law_type if detail else ""),
        promulgation_date=history.promulgation_date
        or (detail.promulgation_date if detail else ""),
        history_file=history.history_file,
        detail_status=detail_status,
    )


def _is_recent(record: MissingHistoryMst, cutoff: date) -> bool:
    raw = record.promulgation_date
    if not re.fullmatch(r"\d{8}", raw):
        return False
    try:
        prom_date = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        return False
    return prom_date >= cutoff


def audit(
    cache_dir: Path | None = None,
    repo_dir: Path | None = None,
    *,
    recent_days: int = DEFAULT_RECENT_DAYS,
    check_commit_metadata: bool = False,
    today: date | None = None,
) -> AuditReport:
    """Compare cached history MSTs with 법령MST entries in Git log messages."""

    cache_dir = Path(cache_dir or cache.CACHE_DIR)
    repo_dir = Path(repo_dir or LAW_REPO)
    detail_dir = cache_dir / "detail"
    cutoff = (today or date.today()) - timedelta(days=recent_days)

    history_records, history_names = _load_history_records(cache_dir)
    git_records = _git_commit_records(repo_dir)
    git_msts = set(git_records)

    missing_with_detail: list[MissingHistoryMst] = []
    missing_without_detail: list[MissingHistoryMst] = []
    for mst in sorted(set(history_records) - git_msts, key=_sort_mst_key):
        history = history_records[mst]
        detail_status, detail = _detail_metadata(detail_dir, mst)
        record = _missing_record(history, detail_status, detail)
        if detail_status == "valid_detail":
            missing_with_detail.append(record)
        else:
            missing_without_detail.append(record)

    recent_cache_ahead = [
        record for record in missing_with_detail
        if _is_recent(record, cutoff)
    ]
    long_term_missing = [
        record for record in missing_with_detail
        if not _is_recent(record, cutoff)
    ]

    missing_with_detail.sort(key=_sort_missing_key)
    missing_without_detail.sort(key=_sort_missing_key)
    recent_cache_ahead.sort(key=_sort_missing_key)
    long_term_missing.sort(key=_sort_missing_key)

    return AuditReport(
        history_names=history_names,
        historical_msts=len(history_records),
        git_msts=len(git_msts),
        missing_in_git_with_valid_detail=missing_with_detail,
        missing_in_git_without_valid_detail=missing_without_detail,
        commit_metadata_mismatches=(
            _commit_metadata_mismatches(history_records, git_records, detail_dir)
            if check_commit_metadata
            else []
        ),
        commit_metadata_checked=check_commit_metadata,
        recent_cache_ahead=recent_cache_ahead,
        long_term_missing=long_term_missing,
        recent_days=recent_days,
        cutoff_date=cutoff.strftime("%Y%m%d"),
    )


def _report_to_jsonable(report: AuditReport) -> dict[str, Any]:
    return asdict(report)


def failure_reasons(
    report: AuditReport,
    *,
    fail_on_long_term_missing: bool = False,
    fail_on_commit_metadata_mismatch: bool = False,
) -> list[str]:
    """Return audit failure reasons for CLI/CI gates."""

    reasons: list[str] = []
    if fail_on_long_term_missing and report.long_term_missing:
        reasons.append(f"long_term_missing={len(report.long_term_missing)}")
    if fail_on_commit_metadata_mismatch and report.commit_metadata_mismatches:
        reasons.append(
            f"commit_metadata_mismatches={len(report.commit_metadata_mismatches)}"
        )
    return reasons


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit cached law history MSTs against legalize-kr Git history"
    )
    parser.add_argument("--cache-dir", type=Path, default=cache.CACHE_DIR)
    parser.add_argument("--repo-dir", type=Path, default=LAW_REPO)
    parser.add_argument("--json", action="store_true", help="Emit full JSON report")
    parser.add_argument(
        "--recent-days",
        type=int,
        default=DEFAULT_RECENT_DAYS,
        help=(
            "Classify valid missing MSTs with 공포일자 within this many days "
            f"as recent cache-ahead candidates (default: {DEFAULT_RECENT_DAYS})"
        ),
    )
    parser.add_argument(
        "--check-commit-metadata",
        action="store_true",
        help="Compare matching Git commits against detail/history cache metadata",
    )
    parser.add_argument(
        "--fail-on-long-term-missing",
        action="store_true",
        help="Exit non-zero when history has old valid-detail MSTs absent from Git",
    )
    parser.add_argument(
        "--fail-on-commit-metadata-mismatch",
        action="store_true",
        help="Exit non-zero when matching Git commits disagree with history metadata",
    )
    args = parser.parse_args()

    report = audit(
        args.cache_dir,
        args.repo_dir,
        recent_days=args.recent_days,
        check_commit_metadata=(
            args.check_commit_metadata or args.fail_on_commit_metadata_mismatch
        ),
    )
    reasons = failure_reasons(
        report,
        fail_on_long_term_missing=args.fail_on_long_term_missing,
        fail_on_commit_metadata_mismatch=args.fail_on_commit_metadata_mismatch,
    )

    if args.json:
        print(json.dumps(_report_to_jsonable(report), ensure_ascii=False, indent=2))
        if reasons:
            raise SystemExit("audit failed: " + ", ".join(reasons))
        return

    print(f"history_names={report.history_names}")
    print(f"historical_msts={report.historical_msts}")
    print(f"git_msts={report.git_msts}")
    print(f"missing_in_git_with_valid_detail={len(report.missing_in_git_with_valid_detail)}")
    print(f"missing_in_git_without_valid_detail={len(report.missing_in_git_without_valid_detail)}")
    print(f"commit_metadata_checked={report.commit_metadata_checked}")
    print(f"commit_metadata_mismatches={len(report.commit_metadata_mismatches)}")
    print(f"recent_cache_ahead={len(report.recent_cache_ahead)}")
    print(f"long_term_missing={len(report.long_term_missing)}")
    if reasons:
        raise SystemExit("audit failed: " + ", ".join(reasons))


if __name__ == "__main__":
    main()
