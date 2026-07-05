"""Import cached administrative rule XML into an admrule-kr working tree."""

import argparse
import logging
from pathlib import Path
from xml.etree import ElementTree

import yaml

from core.atomic_io import atomic_write_text

from . import cache
from .config import ADMRULE_REPO
from .converter import (
    admrule_identity,
    format_date,
    get_admrule_path,
    is_repeal_revision,
    reset_path_registry,
    xml_to_markdown,
)
from .git_engine import commit_admrule, commit_admrule_deletion

logger = logging.getLogger(__name__)


def _text(root: ElementTree.Element, tag: str) -> str:
    return root.findtext(f".//{tag}", "") or ""


def metadata_from_raw(raw_xml: bytes | str) -> dict:
    root = ElementTree.fromstring(raw_xml)
    return {
        "행정규칙ID": _text(root, "행정규칙ID"),
        "행정규칙일련번호": _text(root, "행정규칙일련번호") or _text(root, "ID"),
        "행정규칙명": _text(root, "행정규칙명"),
        "행정규칙종류": _text(root, "행정규칙종류") or _text(root, "행정규칙종류명"),
        "상위부처명": _text(root, "상위부처명"),
        "소관부처명": _text(root, "소관부처명"),
        "담당부서기관명": _text(root, "담당부서기관명"),
        "발령번호": _text(root, "발령번호"),
        "발령일자": _text(root, "발령일자"),
        "제개정구분": _text(root, "제개정구분명"),
        "제개정구분코드": _text(root, "제개정구분코드"),
        "현행연혁구분": _text(root, "현행연혁구분"),
    }


def build_commit_msg(metadata: dict) -> str:
    serial = str(metadata.get("행정규칙일련번호", ""))
    rule_type = metadata.get("행정규칙종류") or "행정규칙"
    return "\n".join([
        f"{rule_type}: {metadata.get('행정규칙명', '')} ({metadata.get('발령번호', '')})",
        "",
        f"행정규칙일련번호: {serial}",
        f"행정규칙ID: {metadata.get('행정규칙ID', '')}",
    ])


def cached_entries(limit: int | None = None, serials: list[str] | None = None) -> list[tuple[str, bytes]]:
    serials = list(serials) if serials is not None else cache.list_cached_serials()
    if limit is not None:
        serials = serials[:limit]
    return [(serial, cache.get_detail(serial) or b"") for serial in serials]


def _sort_key(entry: dict) -> tuple[str, int, str]:
    metadata = entry["metadata"]
    date = format_date(metadata.get("발령일자", "")) or "1970-01-01"
    serial = str(metadata.get("행정규칙일련번호", ""))
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
        identity = admrule_identity(metadata)
        if identity:
            paths[identity] = path.relative_to(repo_dir).as_posix()
    return paths


def import_from_cache(
    repo_dir: Path = ADMRULE_REPO,
    *,
    limit: int | None = None,
    commit: bool = False,
    serials: list[str] | None = None,
    skip_dedup: bool = False,
) -> dict[str, int]:
    counters = {"written": 0, "deleted": 0, "committed": 0, "skipped": 0, "errors": 0}
    repo_dir.mkdir(parents=True, exist_ok=True)
    reset_path_registry()
    entries = []
    for serial, raw in cached_entries(limit, serials):
        if not raw:
            counters["skipped"] += 1
            continue
        try:
            metadata = metadata_from_raw(raw)
            rel_path = get_admrule_path(metadata)
            entries.append({
                "serial": serial,
                "identity": admrule_identity(metadata) or serial,
                "metadata": metadata,
                "rel_path": rel_path,
                "repeal": is_repeal_revision(metadata),
                "markdown": xml_to_markdown(raw),
            })
        except Exception:
            logger.exception("Failed parsing admrule serial=%s", serial)
            counters["errors"] += 1

    latest_paths: dict[str, str] = _current_paths_by_identity(repo_dir) if commit else {}
    for entry in sorted(entries, key=_sort_key):
        try:
            metadata = entry["metadata"]
            rel_path = entry["rel_path"]
            if entry["repeal"]:
                previous_path = latest_paths.pop(entry["identity"], None)
                if previous_path and _remove_stale_path(repo_dir, previous_path):
                    counters["deleted"] += 1
                    if commit:
                        date = format_date(metadata.get("발령일자", "")) or "2000-01-01"
                        if commit_admrule_deletion(
                            repo_dir,
                            previous_path,
                            build_commit_msg(metadata),
                            date,
                            entry["serial"],
                            skip_dedup=skip_dedup,
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
                date = format_date(metadata.get("발령일자", "")) or "2000-01-01"
                if commit_admrule(
                    repo_dir,
                    rel_path,
                    build_commit_msg(metadata),
                    date,
                    entry["serial"],
                    skip_dedup=skip_dedup,
                    stale_paths=stale_paths,
                ):
                    counters["committed"] += 1
        except Exception:
            logger.exception("Failed importing admrule serial=%s", entry["serial"])
            counters["errors"] += 1
    return counters


def main() -> None:
    parser = argparse.ArgumentParser(description="Import cached administrative rules into a working tree")
    parser.add_argument("--repo", type=Path, default=ADMRULE_REPO)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("admrule import done: %s", import_from_cache(args.repo, limit=args.limit, commit=args.commit))


if __name__ == "__main__":
    main()
