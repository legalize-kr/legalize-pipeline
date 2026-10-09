"""Current API selection, separate from publication-ordered revision history."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.atomic_io import atomic_write_text

from . import cache
from .converter import admrule_identity, get_admrule_path, is_repeal_revision, reset_path_registry, xml_to_markdown

SNAPSHOT_NAME = "current_snapshot.json"


def write_current_snapshot(entries: list[dict], history_entries: list[dict] | None = None) -> dict:
    """Publish a complete source selection only after all selected XML is available."""
    from .api_client import get_admrule_detail
    from .import_admrules import metadata_from_raw

    rules = {}
    seen = set()
    excluded = []
    conflicts = []
    for entry in entries:
        if entry.get("현행연혁구분") != "현행":
            continue
        identity, serial = entry.get("행정규칙ID", ""), entry.get("행정규칙일련번호", "")
        if not identity or not serial or not serial.isascii() or not serial.isdecimal() or identity in seen:
            raise RuntimeError(f"Invalid or duplicate current rule identity: {identity}")
        seen.add(identity)
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
        previous = load_current_snapshot()
        if previous:
            candidates = candidates + [metadata_from_raw(cache.get_detail(serial))
                                       for serial in previous["rules"].values() if cache.get_detail(serial)]
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
        raw = get_admrule_detail(serial, refresh=True)
        metadata = metadata_from_raw(raw)
        if admrule_identity(metadata) != identity or metadata["행정규칙일련번호"] != serial:
            raise RuntimeError(f"Supplemental admrule identity mismatch: {identity}/{serial}")
        if metadata.get("현행여부") == "Y" and not is_repeal_revision(metadata):
            rules[identity] = serial
            supplemental.append({"id": identity, "serial": serial, "reason": "live_detail_current_but_absent_from_current_list"})
        else:
            excluded.append({"id": identity, "serial": serial, "reason": "live_detail_non_current"})
    snapshot = {"schema_version": 1, "observed_on": datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat(),
                "rules": rules, "excluded": excluded, "supplemental": supplemental, "conflicts": conflicts}
    cache.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(cache.CACHE_DIR / SNAPSHOT_NAME, json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    return snapshot


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
    return snapshot


def _selected_detail(identity: str, serial: str) -> tuple[bytes, dict]:
    from .import_admrules import metadata_from_raw

    raw = cache.get_detail(serial)
    if not raw:
        raise RuntimeError(f"Missing snapshot detail: {identity}/{serial}")
    metadata = metadata_from_raw(raw)
    if admrule_identity(metadata) != identity or metadata["행정규칙일련번호"] != serial:
        raise RuntimeError(f"Snapshot identity mismatch: {identity}/{serial}")
    return raw, metadata


def validate_snapshot_inputs() -> None:
    snapshot = load_current_snapshot()
    if snapshot:
        for identity, serial in snapshot["rules"].items():
            _selected_detail(identity, serial)


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
    for identity, serial in sorted(snapshot["rules"].items(), key=lambda item: item[1]):
        raw, metadata = _selected_detail(identity, serial)
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
