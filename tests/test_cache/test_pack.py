"""Tests for cache/pack.py."""

from pathlib import Path

from cache.pack import collect_files


def test_collect_files_reports_all_top_level_cache_subdirs(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    for rel in [
        "detail/1.xml",
        "history/민법.json",
        "precedent/1.xml",
        "images/a.png",
        "admrule/1.xml",
        "ordinance/1.xml",
    ]:
        path = cache_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    files, subdirs = collect_files(cache_root)

    assert {entry["path"] for entry in files} == {
        "detail/1.xml",
        "history/민법.json",
        "precedent/1.xml",
        "images/a.png",
        "admrule/1.xml",
        "ordinance/1.xml",
    }
    assert {name: stats["file_count"] for name, stats in subdirs.items()} == {
        "detail": 1,
        "history": 1,
        "precedent": 1,
        "images": 1,
        "admrule": 1,
        "ordinance": 1,
    }
