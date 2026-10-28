"""Current API selection, separate from publication-ordered revision history."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.atomic_io import atomic_write_text

from . import cache
from .converter import has_current_content, admrule_identity, get_admrule_path, is_repeal_revision, reset_path_registry, xml_to_markdown

SNAPSHOT_NAME = "current_snapshot.json"
logger = logging.getLogger(__name__)


def write_current_snapshot(entries: list[dict], history_entries: list[dict] | None = None, *, repo: Path | None = None, workers: int = 1) -> dict:
    """Publish a complete source selection only after all selected XML is available."""
    from .api_client import NoResultError, get_admrule_detail
    from .import_admrules import metadata_from_raw

    previous = load_current_snapshot()
    rules = {}
    seen = set()
    excluded = []
    conflicts = []
    grouped = {}
    for entry in entries:
        if entry.get("현행연혁구분") != "현행":
            continue
        identity, serial = entry.get("행정규칙ID", ""), entry.get("행정규칙일련번호", "")
        if not identity or not serial or not serial.isascii() or not serial.isdecimal():
            raise RuntimeError(f"Invalid or duplicate current rule identity: {identity}")
        candidates = grouped.setdefault(identity, {})
        if serial in candidates:
            raise RuntimeError(f"Invalid or duplicate current rule identity: {identity}")
        candidates[serial] = entry

    for identity, candidates in grouped.items():
        seen.add(identity)
        if len(candidates) > 1:
            current = []
            for serial in candidates:
                raw = get_admrule_detail(serial, refresh=True)
                metadata = metadata_from_raw(raw)
                if admrule_identity(metadata) != identity or metadata["행정규칙일련번호"] != serial:
                    raise RuntimeError(f"Current admrule identity mismatch: {identity}/{serial}")
                status = metadata.get("현행여부")
                if status not in {"Y", "N"}:
                    raise RuntimeError(f"Unknown current admrule status: {identity}/{serial}")
                if status == "Y":
                    current.append(serial)
            if len(current) != 1:
                raise RuntimeError(f"Ambiguous current admrule identity: {identity}: current={current}")
            serial = current[0]
            conflicts.append({"id": identity, "serial": serial, "reason": "duplicate_current_list_identity",
                              "candidate_serials": sorted(candidates)})
            logger.warning("Current list repeats admrule %s across %s revisions; live detail selects %s",
                           identity, len(candidates), serial)
        else:
            serial = next(iter(candidates))
        entry = candidates[serial]
        if is_repeal_revision({"제개정구분": entry.get("제개정구분명", ""),
                               "제개정구분코드": entry.get("제개정구분코드", "")}):
            excluded.append({"id": identity, "serial": serial, "reason": "repeal"})
            continue
        raw = cache.get_detail(serial)
        if not raw:
            raise RuntimeError(f"Missing current admrule detail: {identity}/{serial}")
        metadata = metadata_from_raw(raw)
        if admrule_identity(metadata) != identity or metadata["행정규칙일련번호"] != serial:
            raw = get_admrule_detail(serial, refresh=True)
            metadata = metadata_from_raw(raw)
            if admrule_identity(metadata) != identity or metadata["행정규칙일련번호"] != serial:
                raise RuntimeError(f"Current admrule identity mismatch: {identity}/{serial}")
        rules[identity] = serial
        if metadata.get("현행여부") == "N":
            conflicts.append({"id": identity, "serial": serial, "reason": "current_list_detail_disagreement"})
    if not rules:
        raise RuntimeError("Empty current admrule selection")

    # A missing search row is not proof of repeal. Recheck candidate details.
    latest = {}
    if history_entries is None:
        candidates = (metadata_from_raw(cache.get_detail(serial)) for serial in cache.list_cached_serials())
    else:
        candidates = history_entries
        if previous:
            recheck_serials = set(previous["rules"].values())
            recheck_serials.update(entry["serial"] for entry in previous.get("excluded", [])
                                   if entry.get("reason") == "live_detail_no_result")
            candidates = candidates + [metadata_from_raw(cache.get_detail(serial))
                                       for serial in recheck_serials if cache.get_detail(serial)]
        else:
            listed = {entry.get("행정규칙일련번호") for entry in history_entries}
            candidates = candidates + [metadata_from_raw(cache.get_detail(serial))
                                       for serial in cache.list_cached_serials() if serial not in listed]
    for entry in candidates:
        identity = admrule_identity(entry)
        serial = entry.get("행정규칙일련번호", "")
        if not identity or identity in seen or not serial:
            continue
        key = (str(entry.get("발령일자", "")).replace("-", "").replace(".", ""), int(serial))
        if identity not in latest or key > latest[identity][0]:
            latest[identity] = (key, serial)
    supplemental = []
    for identity, (_, serial) in sorted(latest.items()):
        raw = cache.get_detail(serial)
        if not raw:
            continue
        metadata = metadata_from_raw(raw)
        if metadata.get("현행여부") != "Y" or is_repeal_revision(metadata):
            continue
        try:
            raw = get_admrule_detail(serial, refresh=True)
        except NoResultError:
            excluded.append({"id": identity, "serial": serial, "reason": "live_detail_no_result"})
            logger.warning("Current list omits admrule %s/%s and live detail has no result. The pipeline preserves cached history.", identity, serial)
            continue
        metadata = metadata_from_raw(raw)
        if admrule_identity(metadata) != identity or metadata["행정규칙일련번호"] != serial:
            raise RuntimeError(f"Supplemental admrule identity mismatch: {identity}/{serial}")
        if metadata.get("현행여부") == "Y" and not is_repeal_revision(metadata):
            rules[identity] = serial
            supplemental.append({"id": identity, "serial": serial, "reason": "live_detail_current_but_absent_from_current_list"})
        else:
            excluded.append({"id": identity, "serial": serial, "reason": "live_detail_non_current"})
    required = set(previous.get("required_body_ids", [])) & rules.keys() if previous else set()
    refreshed = 0
    if repo is not None:
        refreshed = _refresh_changed_details(rules, repo, required, workers)
    for identity, serial in rules.items():
        raw, _ = _selected_detail(identity, serial)
        if has_current_content(raw):
            required.add(identity)
        elif identity in required:
            raise RuntimeError(f"Current admrule body regression: {identity}/{serial}")
    snapshot = {"schema_version": 1, "observed_on": datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat(),
                "rules": rules, "excluded": excluded, "supplemental": supplemental, "conflicts": conflicts,
                "required_body_ids": sorted(required), "refreshed_details": refreshed}
    cache.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(cache.CACHE_DIR / SNAPSHOT_NAME, json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    return snapshot


def _refresh_changed_details(rules: dict, repo: Path, required: set[str], workers: int) -> int:
    from .api_client import get_admrule_detail
    from .import_admrules import _current_paths_by_identity
    from .validate import _frontmatter_and_body

    paths = _current_paths_by_identity(repo)
    changed = []
    for identity, serial in rules.items():
        raw, _ = _selected_detail(identity, serial)
        previous = (repo / paths[identity]).read_text(encoding="utf-8") if identity in paths else ""
        if previous:
            metadata, _, errors = _frontmatter_and_body(previous)
            if errors:
                raise RuntimeError(f"Invalid published admrule: {identity}")
            if metadata.get("본문출처") in {"api-text", "parsed-from-hwp", "attachment-only"}:
                required.add(identity)
        if previous != xml_to_markdown(raw):
            changed.append((identity, serial))

    def refresh(item):
        identity, serial = item
        get_admrule_detail(serial, refresh=True)
        raw, _ = _selected_detail(identity, serial)
        if identity in required and not has_current_content(raw):
            raise RuntimeError(f"Current admrule body regression: {identity}/{serial}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(refresh, changed))
    return len(changed)


def load_current_snapshot() -> dict | None:
    path = cache.CACHE_DIR / SNAPSHOT_NAME
    if not path.exists():
        return None
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int
            or snapshot["schema_version"] != 1 or not isinstance(snapshot.get("rules"), dict)
            or not snapshot["rules"]):
        raise RuntimeError("Invalid current admrule snapshot")
    observed_on = snapshot.get("observed_on", "")
    if not isinstance(observed_on, str) or datetime.strptime(observed_on, "%Y-%m-%d").date().isoformat() != observed_on:
        raise RuntimeError("Invalid snapshot date")
    if any(not isinstance(serial, str) or not serial.isascii() or not serial.isdecimal() for serial in snapshot["rules"].values()):
        raise RuntimeError("Invalid current admrule serial")
    required = snapshot.get("required_body_ids", [])
    if not isinstance(required, list) or any(not isinstance(identity, str) or identity not in snapshot["rules"] for identity in required):
        raise RuntimeError("Invalid required admrule body identities")
    return snapshot


def _selected_detail(identity: str, serial: str, *, body_required: bool = False) -> tuple[bytes, dict]:
    from .import_admrules import metadata_from_raw

    raw = cache.get_detail(serial)
    if not raw:
        raise RuntimeError(f"Missing snapshot detail: {identity}/{serial}")
    metadata = metadata_from_raw(raw)
    if admrule_identity(metadata) != identity or metadata["행정규칙일련번호"] != serial:
        raise RuntimeError(f"Snapshot identity mismatch: {identity}/{serial}")
    if body_required and not has_current_content(raw):
        raise RuntimeError(f"Current admrule body regression: {identity}/{serial}")
    return raw, metadata


def validate_snapshot_inputs() -> None:
    snapshot = load_current_snapshot()
    if snapshot:
        required = set(snapshot.get("required_body_ids", []))
        for identity, serial in snapshot["rules"].items():
            _selected_detail(identity, serial, body_required=identity in required)


def reconcile_current_snapshot(repo: Path, *, commit: bool = False) -> dict[str, int]:
    """Restore the API-selected revision after importing publication history."""
    from .git_engine import commit_admrule, commit_admrule_deletion
    from .import_admrules import _current_paths_by_identity

    snapshot = load_current_snapshot()
    stats = {"snapshot_written": 0, "snapshot_deleted": 0, "snapshot_committed": 0}
    if snapshot is None:
        return stats
    reset_path_registry()
    desired = {}
    required = set(snapshot.get("required_body_ids", []))
    for identity, serial in sorted(snapshot["rules"].items(), key=lambda item: item[1]):
        raw, metadata = _selected_detail(identity, serial, body_required=identity in required)
        desired[identity] = (get_admrule_path(metadata), xml_to_markdown(raw), metadata)
    paths = _current_paths_by_identity(repo)
    date = snapshot["observed_on"]
    removals = {identity for identity, path in paths.items()
                if identity not in desired or path != desired[identity][0]}
    for identity in sorted(removals):
        path = paths.pop(identity)
        (repo / path).unlink()
        stats["snapshot_deleted"] += 1
        if commit and commit_admrule_deletion(repo, path, f"현행 스냅샷 제외: {identity}\n\n행정규칙ID: {identity}", date, "", skip_dedup=True):
            stats["snapshot_committed"] += 1
    for identity in sorted(desired):
        path, markdown, metadata = desired[identity]
        target = repo / path
        if target.exists() and target.read_text(encoding="utf-8") == markdown:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, markdown)
        stats["snapshot_written"] += 1
        serial = metadata["행정규칙일련번호"]
        message = f"현행 스냅샷: {metadata['행정규칙명']}\n\n행정규칙일련번호: {serial}\n행정규칙ID: {identity}"
        if commit and commit_admrule(repo, path, message, date, serial, skip_dedup=True):
            stats["snapshot_committed"] += 1
    return stats
