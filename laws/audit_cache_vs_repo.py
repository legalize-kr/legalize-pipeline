"""Audit cached law detail/history entries against the result repository.

The report distinguishes true missing content from path drift where the
current-name path is absent but the same 법령ID exists elsewhere.
"""

from __future__ import annotations

import argparse
import json
import logging
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from . import cache
from .config import LAW_REPO
from .converter import entry_sort_key, get_group_and_filename
from .generate_metadata import parse_frontmatter

logger = logging.getLogger(__name__)
DEFAULT_PATH_DRIFT_ALLOWLIST = Path(__file__).parent / "data" / "known_path_drift.yaml"


@dataclass(frozen=True)
class RepoRecord:
    """One Markdown file found in the result repository."""

    path: str
    filename: str
    title: str
    law_id: str
    law_type: str
    mst: str
    body_text: str
    body_chars: int
    article_heads: int
    contains_repeal: bool


@dataclass(frozen=True)
class CacheEntry:
    """One valid cached detail XML entry."""

    expected_path: str
    mst: str
    law_id: str
    law_type: str
    law_name: str
    promulgation_date: str
    promulgation_number: str


@dataclass(frozen=True)
class PathDrift:
    """A cache entry whose expected path differs from existing same-ID content."""

    expected_path: str
    actual_paths: list[str]
    mst: str
    law_id: str
    law_type: str
    law_name: str


@dataclass(frozen=True)
class MissingContent:
    """A cache entry with no matching repository content."""

    expected_path: str
    mst: str
    law_id: str
    law_type: str
    law_name: str


@dataclass(frozen=True)
class AuditReport:
    """Cache-vs-repository audit result."""

    history_names: int
    historical_msts: int
    detail_msts: int
    entries_parsed_valid_meta: int
    final_paths: int
    empty_history: int
    malformed_history: int
    missing_detail: list[str]
    empty_or_invalid_detail_meta: list[str]
    detail_not_in_history: list[str]
    path_drift: list[PathDrift]
    missing_content: list[MissingContent]


def _sort_mst_key(value: str) -> tuple[int, str]:
    try:
        return (0, f"{int(value):020d}")
    except ValueError:
        return (1, value)


def _body_has_content(record: RepoRecord) -> bool:
    if "본문은 추후 추가 예정" in record.body_text:
        return False
    substantive_text = "\n".join(
        line.strip()
        for line in record.body_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    return (
        record.article_heads > 0
        or (record.contains_repeal and record.body_chars > 0)
        or len(substantive_text) > 40
    )


def _repo_records(repo_dir: Path) -> list[RepoRecord]:
    records: list[RepoRecord] = []
    kr_dir = repo_dir / "kr"
    if not kr_dir.exists():
        return records

    for md_file in sorted(kr_dir.rglob("*.md")):
        fm = parse_frontmatter(md_file)
        if not isinstance(fm, dict):
            continue
        text = md_file.read_text(encoding="utf-8", errors="replace")
        body = text
        if text.startswith("---"):
            try:
                _yaml, body = text.removeprefix("---\n").split("\n---\n", 1)
            except ValueError:
                pass
        records.append(
            RepoRecord(
                path=str(md_file.relative_to(repo_dir)),
                filename=md_file.name,
                title=str(fm.get("제목", "")),
                law_id=str(fm.get("법령ID", "")),
                law_type=str(fm.get("법령구분", "")),
                mst=str(fm.get("법령MST", "")),
                body_text=body,
                body_chars=len(body.strip()),
                article_heads=body.count("##### 제"),
                contains_repeal="폐지한다" in body,
            )
        )
    return records


def _load_history(cache_dir: Path) -> tuple[dict[str, str], int, int, int]:
    history_dir = cache_dir / "history"
    if not history_dir.exists():
        return {}, 0, 0, 0

    mst_to_amendment: dict[str, str] = {}
    empty_history = 0
    malformed_history = 0
    history_names = 0
    for path in sorted(history_dir.glob("*.json")):
        history_names += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            malformed_history += 1
            continue
        if not data:
            empty_history += 1
            continue
        if not isinstance(data, list):
            malformed_history += 1
            continue
        for entry in data:
            if not isinstance(entry, dict):
                malformed_history += 1
                continue
            mst = str(entry.get("법령일련번호", "")).strip()
            if mst:
                mst_to_amendment[mst] = str(entry.get("제개정구분명", ""))
    return mst_to_amendment, history_names, empty_history, malformed_history


def _metadata_from_xml(path: Path, mst: str, amendment: str) -> dict[str, str] | None:
    root = ET.parse(path).getroot()
    meta = {
        "법령명한글": root.findtext(".//법령명_한글", ""),
        "법령MST": mst,
        "법령ID": root.findtext(".//법령ID", ""),
        "법령구분": root.findtext(".//법종구분", ""),
        "공포일자": root.findtext(".//공포일자", ""),
        "공포번호": root.findtext(".//공포번호", ""),
        "시행일자": root.findtext(".//시행일자", ""),
        "제개정구분": amendment or root.findtext(".//제개정구분명", ""),
    }
    if not meta["법령명한글"] or not meta["법령ID"] or not meta["법령구분"]:
        return None
    return meta


def _current_name_path(
    law_name: str,
    law_type: str,
    law_id: str,
    assigned_paths: dict[str, str],
) -> str:
    """Return the final-path expectation based on the current law name."""

    group, filename = get_group_and_filename(law_name, law_type)
    path = f"kr/{group}/{filename}.md"
    existing_id = assigned_paths.get(path)
    if existing_id is None or existing_id == law_id:
        assigned_paths[path] = law_id
        return path

    qualified = f"kr/{group}/{filename}({law_type}).md"
    assigned_paths[qualified] = law_id
    return qualified


def audit(cache_dir: Path | None = None, repo_dir: Path | None = None) -> AuditReport:
    """Audit cache entries against repository files."""

    cache_dir = Path(cache_dir or cache.CACHE_DIR)
    repo_dir = Path(repo_dir or LAW_REPO)
    detail_dir = cache_dir / "detail"

    mst_to_amendment, history_names, empty_history, malformed_history = _load_history(cache_dir)
    detail_msts = {path.stem for path in detail_dir.glob("*.xml")} if detail_dir.exists() else set()

    entries: list[tuple[str, dict[str, str]]] = []
    missing_detail: list[str] = []
    empty_or_invalid_detail_meta: list[str] = []
    for mst, amendment in mst_to_amendment.items():
        detail_path = detail_dir / f"{mst}.xml"
        if not detail_path.exists():
            missing_detail.append(mst)
            continue
        try:
            meta = _metadata_from_xml(detail_path, mst, amendment)
        except ET.ParseError:
            empty_or_invalid_detail_meta.append(mst)
            continue
        if meta is None:
            empty_or_invalid_detail_meta.append(mst)
            continue
        entries.append((mst, meta))

    # A detail XML can remain valid even when the history cache is split across
    # pre/post-rename law names and one side is missing. Include those details
    # when choosing each lineage's latest path, while continuing to report them
    # separately as detail_not_in_history for cache diagnostics.
    detail_not_in_history = detail_msts - set(mst_to_amendment)
    for mst in detail_not_in_history:
        try:
            meta = _metadata_from_xml(detail_dir / f"{mst}.xml", mst, "")
        except ET.ParseError:
            continue
        if meta is not None:
            entries.append((mst, meta))

    entries.sort(
        key=lambda item: entry_sort_key(
            item[1].get("공포일자", ""),
            item[1].get("법령명한글", ""),
            item[1].get("공포번호", ""),
            item[0],
        )
    )

    final_by_path: dict[str, CacheEntry] = {}
    latest_by_id: dict[str, tuple[str, dict[str, str]]] = {}
    lineage_order: list[str] = []
    for mst, meta in entries:
        law_id = meta["법령ID"]
        if law_id not in latest_by_id:
            lineage_order.append(law_id)
        latest_by_id[law_id] = (mst, meta)

    assigned_paths: dict[str, str] = {}
    for law_id in lineage_order:
        mst, meta = latest_by_id[law_id]
        rel = _current_name_path(meta["법령명한글"], meta["법령구분"], meta["법령ID"], assigned_paths)
        final_by_path[rel] = CacheEntry(
            expected_path=rel,
            mst=mst,
            law_id=meta["법령ID"],
            law_type=meta["법령구분"],
            law_name=meta["법령명한글"],
            promulgation_date=meta.get("공포일자", ""),
            promulgation_number=meta.get("공포번호", ""),
        )

    repo_records = _repo_records(repo_dir)
    by_path: dict[str, list[RepoRecord]] = defaultdict(list)
    by_id: dict[str, list[RepoRecord]] = defaultdict(list)
    for record in repo_records:
        by_path[record.path].append(record)
        by_id[record.law_id].append(record)

    path_drift: list[PathDrift] = []
    missing_content: list[MissingContent] = []
    for rel, entry in sorted(final_by_path.items()):
        expected_records = by_path.get(rel, [])
        if any(_body_has_content(record) for record in expected_records):
            continue
        same_id = [
            record
            for record in by_id.get(entry.law_id, [])
            if _body_has_content(record)
        ]
        if same_id:
            path_drift.append(
                PathDrift(
                    expected_path=entry.expected_path,
                    actual_paths=[record.path for record in same_id],
                    mst=entry.mst,
                    law_id=entry.law_id,
                    law_type=entry.law_type,
                    law_name=entry.law_name,
                )
            )
        else:
            missing_content.append(
                MissingContent(
                    expected_path=entry.expected_path,
                    mst=entry.mst,
                    law_id=entry.law_id,
                    law_type=entry.law_type,
                    law_name=entry.law_name,
                )
            )

    return AuditReport(
        history_names=history_names,
        historical_msts=len(mst_to_amendment),
        detail_msts=len(detail_msts),
        entries_parsed_valid_meta=len(entries),
        final_paths=len(final_by_path),
        empty_history=empty_history,
        malformed_history=malformed_history,
        missing_detail=sorted(missing_detail, key=_sort_mst_key),
        empty_or_invalid_detail_meta=sorted(empty_or_invalid_detail_meta, key=_sort_mst_key),
        detail_not_in_history=sorted(detail_not_in_history, key=_sort_mst_key),
        path_drift=path_drift,
        missing_content=missing_content,
    )


def _report_to_jsonable(report: AuditReport) -> dict[str, Any]:
    return asdict(report)


def failure_reasons(
    report: AuditReport,
    *,
    fail_on_missing_content: bool = False,
    fail_on_path_drift: bool = False,
    allowed_path_drift: set[str] | None = None,
) -> list[str]:
    """Return audit failure reasons for CLI/CI gates."""

    reasons: list[str] = []
    if fail_on_missing_content and report.missing_content:
        reasons.append(f"missing_content={len(report.missing_content)}")
    if fail_on_path_drift and report.path_drift:
        if allowed_path_drift is None:
            reasons.append(f"path_drift={len(report.path_drift)}")
        else:
            new_path_drift = [
                drift for drift in report.path_drift
                if drift.expected_path not in allowed_path_drift
            ]
            if new_path_drift:
                reasons.append(f"new_path_drift={len(new_path_drift)}")
    return reasons


def load_path_drift_allowlist(path: Path) -> set[str]:
    """Load known path-drift expected paths."""

    if not path.exists():
        return set()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict):
        values = data.get("expected_paths", [])
    else:
        values = data
    if not isinstance(values, list):
        raise ValueError(f"Invalid path drift allowlist: {path}")
    return {str(value) for value in values}


def main() -> None:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description="Audit laws cache against result repository")
    parser.add_argument("--cache-dir", type=Path, default=cache.CACHE_DIR)
    parser.add_argument("--repo-dir", type=Path, default=LAW_REPO)
    parser.add_argument("--json", action="store_true", help="Emit full JSON report")
    parser.add_argument(
        "--fail-on-missing-content",
        action="store_true",
        help="Exit non-zero when cache/history has entries with no repository body",
    )
    parser.add_argument(
        "--fail-on-path-drift",
        action="store_true",
        help="Exit non-zero when same-law content exists only at a stale path",
    )
    parser.add_argument(
        "--fail-on-new-path-drift",
        action="store_true",
        help="Exit non-zero when path drift is not present in the allowlist",
    )
    parser.add_argument(
        "--path-drift-allowlist",
        type=Path,
        default=DEFAULT_PATH_DRIFT_ALLOWLIST,
        help="YAML allowlist for --fail-on-new-path-drift",
    )
    args = parser.parse_args()

    report = audit(args.cache_dir, args.repo_dir)
    allowed_path_drift = (
        load_path_drift_allowlist(args.path_drift_allowlist)
        if args.fail_on_new_path_drift
        else None
    )
    reasons = failure_reasons(
        report,
        fail_on_missing_content=args.fail_on_missing_content,
        fail_on_path_drift=args.fail_on_path_drift or args.fail_on_new_path_drift,
        allowed_path_drift=allowed_path_drift,
    )
    if reasons and report.path_drift:
        for drift in report.path_drift:
            if allowed_path_drift is not None and drift.expected_path in allowed_path_drift:
                continue
            print(
                "path_drift_detail "
                f"expected={drift.expected_path} "
                f"actual={','.join(drift.actual_paths)} "
                f"mst={drift.mst} law_id={drift.law_id}"
            )
    if args.json:
        print(json.dumps(_report_to_jsonable(report), ensure_ascii=False, indent=2))
        if reasons:
            raise SystemExit("audit failed: " + ", ".join(reasons))
        return

    print(f"history_names={report.history_names}")
    print(f"historical_msts={report.historical_msts}")
    print(f"detail_msts={report.detail_msts}")
    print(f"entries_parsed_valid_meta={report.entries_parsed_valid_meta}")
    print(f"final_paths={report.final_paths}")
    print(f"path_drift={len(report.path_drift)}")
    print(f"missing_content={len(report.missing_content)}")
    print(f"detail_not_in_history={len(report.detail_not_in_history)}")
    if reasons:
        raise SystemExit("audit failed: " + ", ".join(reasons))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
