"""Import cached ordinance XML into an ordinance-kr working tree."""

import argparse
import logging
from pathlib import Path

from core.atomic_io import atomic_write_text

from . import cache
from .config import ORDINANCE_REPO
from .converter import UnsupportedOrdinanceType, format_date, parse_ordinance_xml, reset_path_registry, xml_to_markdown
from .git_engine import commit_ordinance

logger = logging.getLogger(__name__)


def build_commit_msg(metadata: dict) -> str:
    ordinance_id = metadata.get("자치법규ID", "")
    title = f"{metadata.get('자치법규종류', '')}: {metadata.get('자치법규명', '')}"
    if metadata.get("제개정구분"):
        title += f" ({metadata['제개정구분']})"
    return "\n".join([
        title,
        "",
        f"자치법규: https://www.law.go.kr/DRF/lawService.do?target=ordin&ID={ordinance_id}",
        f"공포일자: {format_date(metadata.get('공포일자', ''))}",
        f"공포번호: {metadata.get('공포번호', '')}",
        f"지자체기관명: {metadata.get('지자체기관명', '')}",
        f"자치법규ID: {ordinance_id}",
    ])


def cached_entries(limit: int | None = None, ids: list[str] | None = None) -> list[tuple[str, bytes]]:
    ids = list(ids) if ids is not None else cache.list_cached_ids()
    if limit is not None:
        ids = ids[:limit]
    return [(ordinance_id, cache.get_detail(ordinance_id) or b"") for ordinance_id in ids]


def _sort_key(entry: dict) -> tuple[str, int, str]:
    metadata = entry["metadata"]
    date = format_date(metadata.get("공포일자", "")) or "1970-01-01"
    ordinance_id = str(metadata.get("자치법규ID", ""))
    try:
        id_key = int(ordinance_id)
    except ValueError:
        id_key = 2**63 - 1
    return date, id_key, entry["rel_path"]


def import_from_cache(
    repo_dir: Path = ORDINANCE_REPO,
    *,
    limit: int | None = None,
    commit: bool = False,
    ids: list[str] | None = None,
    skip_dedup: bool = False,
) -> dict[str, int]:
    counters = {"written": 0, "committed": 0, "skipped": 0, "errors": 0}
    repo_dir.mkdir(parents=True, exist_ok=True)
    reset_path_registry()
    entries = []
    for ordinance_id, raw in cached_entries(limit, ids):
        if not raw:
            counters["skipped"] += 1
            continue
        try:
            detail = parse_ordinance_xml(raw)
            rel_path, markdown = xml_to_markdown(raw, use_registry=True)
            entries.append({
                "ordinance_id": ordinance_id,
                "metadata": detail["metadata"],
                "rel_path": rel_path,
                "markdown": markdown,
            })
        except UnsupportedOrdinanceType:
            counters["skipped"] += 1
        except Exception:
            logger.exception("Failed parsing ordinance ID=%s", ordinance_id)
            counters["errors"] += 1

    for entry in sorted(entries, key=_sort_key):
        try:
            meta = entry["metadata"]
            rel_path = entry["rel_path"]
            target = repo_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target, entry["markdown"])
            counters["written"] += 1
            if commit:
                date = format_date(meta.get("공포일자", "")) or "2000-01-01"
                if commit_ordinance(
                    repo_dir,
                    rel_path,
                    build_commit_msg(meta),
                    date,
                    entry["ordinance_id"],
                    skip_dedup=skip_dedup,
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
    logger.info("ordinance import done: %s", import_from_cache(args.repo, limit=args.limit, commit=args.commit))


if __name__ == "__main__":
    main()
