"""Import cached ordinance XML into an ordinance-kr working tree."""

import argparse
import datetime
import logging
from pathlib import Path

import yaml

from core.atomic_io import atomic_write_text

from . import cache
from .config import ORDINANCE_REPO
from .converter import UnsupportedOrdinanceType, format_date, parse_ordinance_xml, reset_path_registry, source_fields_to_markdown, xml_to_markdown
from .git_engine import commit_ordinance, commit_ordinance_deletion, committed_metadata

logger = logging.getLogger(__name__)


def build_commit_msg(metadata: dict) -> str:
    ordinance_id = metadata.get("자치법규ID", "")
    serial = str(metadata.get("자치법규일련번호", ""))
    source_key = f"MST={serial}" if serial else f"ID={ordinance_id}"
    title = f"{metadata.get('자치법규종류', '')}: {metadata.get('자치법규명', '')}"
    if metadata.get("제개정구분"):
        title += f" ({metadata['제개정구분']})"
    return "\n".join([
        title,
        "",
        f"자치법규: https://www.law.go.kr/DRF/lawService.do?target=ordin&{source_key}",
        f"공포일자: {format_date(metadata.get('공포일자', ''))}",
        f"공포번호: {metadata.get('공포번호', '')}",
        f"지자체기관명: {metadata.get('지자체기관명', '')}",
        f"자치법규ID: {ordinance_id}",
        f"자치법규일련번호: {serial}",
    ])


def cached_entries(limit: int | None = None, serials: list[str] | None = None) -> list[tuple[str, bytes]]:
    ids = list(serials) if serials is not None else cache.list_cached_ids()
    if limit is not None:
        ids = ids[:limit]
    return [
        (cache_key, cache.get_detail(cache_key, historical=serials is not None) or b"")
        for cache_key in ids
    ]


def _revision_date(metadata: dict) -> str:
    try:
        return datetime.date.fromisoformat(format_date(metadata.get("공포일자", ""))).isoformat()
    except ValueError:
        return "1970-01-01"


def _sort_key(entry: dict) -> tuple[str, int, str]:
    metadata = entry["metadata"]
    date = _revision_date(metadata)
    serial = str(metadata.get("자치법규일련번호", ""))
    try:
        serial_key = int(serial)
    except ValueError:
        serial_key = 2**63 - 1
    return date, serial_key, entry["rel_path"]


def _remove_stale_path(repo_dir: Path, rel_path: str) -> bool:
    target = repo_dir / rel_path
    if not target.exists():
        return False
    target.unlink()
    return True


def _is_repeal_revision(metadata: dict) -> bool:
    return "폐지" in str(metadata.get("제개정구분", ""))


def _frontmatter_from_markdown(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {}
    if not text.startswith("---\n"):
        return {}
    frontmatter, sep, _ = text[4:].partition("\n---")
    if not sep:
        return {}
    data = yaml.safe_load(frontmatter) or {}
    return data if isinstance(data, dict) else {}


def _current_paths_by_identity(repo_dir: Path) -> dict[str, str]:
    paths: dict[str, str] = {}
    if not repo_dir.exists():
        return paths
    for path in repo_dir.rglob("본문.md"):
        metadata = _frontmatter_from_markdown(path)
        identity = str(metadata.get("자치법규ID", ""))
        if identity:
            paths[identity] = path.relative_to(repo_dir).as_posix()
    return paths


def import_from_cache(
    repo_dir: Path = ORDINANCE_REPO,
    *,
    limit: int | None = None,
    commit: bool = False,
    serials: list[str] | None = None,
    skip_dedup: bool = False,
) -> dict[str, int]:
    counters = {"written": 0, "deleted": 0, "committed": 0, "skipped": 0, "errors": 0}
    repo_dir.mkdir(parents=True, exist_ok=True)
    reset_path_registry()
    candidates: dict[str, dict] = {}
    for cache_key, raw in cached_entries(limit, serials):
        if not raw:
            counters["skipped"] += 1
            continue
        try:
            detail = parse_ordinance_xml(raw)
            if serials is not None or cache_key.startswith("history/"):
                expected_serial = cache_key.removeprefix("history/")
                actual_serial = str(detail["metadata"].get("자치법규일련번호", ""))
                if actual_serial != expected_serial:
                    raise ValueError(
                        f"history cache key {expected_serial} returned invalid "
                        f"자치법규일련번호={actual_serial or '<missing>'}"
                    )
            serial = str(detail["metadata"].get("자치법규일련번호") or cache_key)
            ordinance_id = str(detail["metadata"].get("자치법규ID") or cache_key)
            candidate = {
                "cache_key": cache_key,
                "raw": raw,
                "serial": serial,
                "ordinance_id": ordinance_id,
                "identity": ordinance_id,
                "metadata": detail["metadata"],
                "repeal": _is_repeal_revision(detail["metadata"]),
                "repeal_source": source_fields_to_markdown(detail)
                if _is_repeal_revision(detail["metadata"]) and detail["source_errors"] else "",
                "priority": int(cache_key.removeprefix("history/") == serial),
            }
            previous = candidates.get(serial)
            if previous and previous["identity"] != ordinance_id:
                raise ValueError(
                    f"duplicate 자치법규일련번호 {serial}: {previous['identity']} != {ordinance_id}"
                )
            if previous is None or candidate["priority"] >= previous["priority"]:
                candidates[serial] = candidate
        except UnsupportedOrdinanceType:
            counters["skipped"] += 1
        except Exception:
            logger.exception("Failed parsing ordinance cache_key=%s", cache_key)
            counters["errors"] += 1

    latest_paths = _current_paths_by_identity(repo_dir) if commit and candidates else {}
    reset_path_registry({path: identity for identity, path in latest_paths.items()})
    entries = []
    for serial in sorted(candidates):
        candidate = candidates[serial]
        try:
            rel_path, markdown = xml_to_markdown(candidate.pop("raw"), use_registry=True)
            candidate["rel_path"] = rel_path
            candidate["markdown"] = markdown
            entries.append(candidate)
        except UnsupportedOrdinanceType:
            counters["skipped"] += 1
        except Exception:
            logger.exception("Failed rendering ordinance cache_key=%s", candidate["cache_key"])
            counters["errors"] += 1

    if not entries:
        return counters

    committed_serials, published_versions = committed_metadata(repo_dir) if commit else (set(), {})
    for entry in sorted(entries, key=_sort_key):
        try:
            if not skip_dedup and entry["serial"] in committed_serials:
                counters["skipped"] += 1
                continue
            meta = entry["metadata"]
            rel_path = entry["rel_path"]
            previous_path = latest_paths.get(entry["identity"])
            published = published_versions.get(entry["identity"])
            if commit and previous_path:
                current = _frontmatter_from_markdown(repo_dir / previous_path)
                published = _sort_key({"metadata": current, "rel_path": previous_path})[:2]
            if published and published > _sort_key(entry)[:2]:
                raise ValueError(
                    f"Older revision {entry['serial']} would replace a newer ordinance; "
                    "rebuild its history in an isolated repository before publication"
                )
            if entry["repeal"]:
                previous_path = latest_paths.pop(entry["identity"], None)
                deleted_path = previous_path if previous_path and _remove_stale_path(repo_dir, previous_path) else None
                if deleted_path:
                    counters["deleted"] += 1
                if commit:
                    date = _revision_date(meta)
                    if commit_ordinance_deletion(
                        repo_dir,
                        deleted_path,
                        build_commit_msg(meta) + ("\n\n" + entry["repeal_source"] if entry["repeal_source"] else ""),
                        date,
                        entry["serial"],
                        skip_dedup=skip_dedup,
                        preserve_message=bool(entry["repeal_source"]),
                    ):
                        counters["committed"] += 1
                continue

            stale_paths = []
            previous_path = latest_paths.get(entry["identity"])
            if previous_path and previous_path != rel_path and _remove_stale_path(repo_dir, previous_path):
                stale_paths.append(previous_path)
            latest_paths[entry["identity"]] = rel_path
            target = repo_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target, entry["markdown"])
            counters["written"] += 1
            if commit:
                date = _revision_date(meta)
                if commit_ordinance(
                    repo_dir,
                    rel_path,
                    build_commit_msg(meta),
                    date,
                    entry["ordinance_id"],
                    entry["serial"],
                    skip_dedup=skip_dedup,
                    stale_paths=stale_paths,
                ):
                    counters["committed"] += 1
        except Exception:
            logger.exception("Failed importing ordinance ID=%s", entry["ordinance_id"])
            counters["errors"] += 1
    return counters


def main() -> None:
    parser = argparse.ArgumentParser(description="Import cached ordinances into a working tree")
    parser.add_argument("--repo", type=Path, default=ORDINANCE_REPO)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stats = import_from_cache(args.repo, limit=args.limit, commit=args.commit)
    logger.info("ordinance import done: %s", stats)
    if stats["errors"]:
        raise SystemExit(f"Ordinance import failed: errors={stats['errors']}")


if __name__ == "__main__":
    main()
