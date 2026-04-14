"""Tests for --only-orphans filtering and _run_search_api_recovery."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import laws.failures as failures
from laws.import_laws import _run_search_api_recovery, import_from_cache


@pytest.fixture(autouse=True)
def patch_failed_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(failures, "FAILED_FILE", tmp_path / ".failed_msts.json")


# ---------------------------------------------------------------------------
# only_orphans filtering
# ---------------------------------------------------------------------------

def _make_metadata(mst_keys: list[str]) -> dict:
    return {mst: {"path": f"kr/법{mst}/법률.md"} for mst in mst_keys}


def test_orphans_excludes_on_disk(monkeypatch):
    monkeypatch.setattr("laws.cache.list_cached_msts", lambda: ["1", "2", "3"])
    monkeypatch.setattr("laws.import_laws.cache.list_cached_msts", lambda: ["1", "2", "3"])
    monkeypatch.setattr("laws.generate_metadata.generate", lambda: _make_metadata(["1"]))
    monkeypatch.setattr("laws.import_laws.get_processed_msts", lambda: set())

    detail_mock = MagicMock(side_effect=Exception("no detail"))
    with patch("laws.import_laws.get_law_detail", detail_mock):
        import_from_cache(only_orphans=True, dry_run=True)

    called_msts = {call.args[0] for call in detail_mock.call_args_list}
    assert "1" not in called_msts
    assert {"2", "3"}.issubset(called_msts | set())  # parse loop will attempt 2 and 3


def test_orphans_excludes_processed(monkeypatch):
    monkeypatch.setattr("laws.import_laws.cache.list_cached_msts", lambda: ["1", "2"])
    monkeypatch.setattr("laws.generate_metadata.generate", lambda: _make_metadata([]))
    monkeypatch.setattr("laws.import_laws.get_processed_msts", lambda: {"1"})

    detail_mock = MagicMock(side_effect=Exception("no detail"))
    with patch("laws.import_laws.get_law_detail", detail_mock):
        import_from_cache(only_orphans=True, dry_run=True)

    called_msts = {call.args[0] for call in detail_mock.call_args_list}
    assert "1" not in called_msts
    assert "2" in called_msts


def test_orphans_excludes_failed_msts(monkeypatch, tmp_path):
    monkeypatch.setattr("laws.import_laws.cache.list_cached_msts", lambda: ["1", "2"])
    monkeypatch.setattr("laws.generate_metadata.generate", lambda: _make_metadata([]))
    monkeypatch.setattr("laws.checkpoint.get_processed_msts", lambda: set())
    failures.mark_failed("2", reason="empty_body", detail="", step="test")

    detail_mock = MagicMock(side_effect=Exception("no detail"))
    with patch("laws.import_laws.get_law_detail", detail_mock):
        import_from_cache(only_orphans=True, dry_run=True)

    called_msts = {call.args[0] for call in detail_mock.call_args_list}
    assert "2" not in called_msts
    assert "1" in called_msts


def test_orphans_excludes_all_three_sets(monkeypatch, tmp_path):
    monkeypatch.setattr("laws.import_laws.cache.list_cached_msts", lambda: ["1", "2", "3", "4"])
    monkeypatch.setattr("laws.generate_metadata.generate", lambda: _make_metadata(["1"]))
    monkeypatch.setattr("laws.import_laws.get_processed_msts", lambda: {"2"})
    failures.mark_failed("3", reason="api_error", detail="", step="test")

    detail_mock = MagicMock(side_effect=Exception("no detail"))
    with patch("laws.import_laws.get_law_detail", detail_mock):
        import_from_cache(only_orphans=True, dry_run=True)

    called_msts = {call.args[0] for call in detail_mock.call_args_list}
    assert called_msts == {"4"}


# ---------------------------------------------------------------------------
# _run_search_api_recovery
# ---------------------------------------------------------------------------

def test_search_api_noop_without_list(monkeypatch):
    search_mock = MagicMock()
    with patch("laws.import_laws.search_laws", search_mock):
        _run_search_api_recovery(None)
    search_mock.assert_not_called()


def test_search_api_writes_search_miss_on_empty_hits(tmp_path, monkeypatch):
    list_file = tmp_path / "names.txt"
    list_file.write_text("민법\n", encoding="utf-8")

    search_mock = MagicMock(return_value={"laws": []})
    with patch("laws.import_laws.search_laws", search_mock):
        _run_search_api_recovery(list_file)

    misses = failures.get_search_misses()
    assert "민법" in misses
    assert misses["민법"]["reason"] == "no_hits"
    assert failures.get_failed_msts() == {}


def test_search_api_calls_get_detail_on_resolved_mst(tmp_path, monkeypatch):
    list_file = tmp_path / "names.txt"
    list_file.write_text("민법\n", encoding="utf-8")

    candidate = {
        "법령명한글": "민법",
        "법령구분": "법률",
        "공포일자": "20230101",
        "법령일련번호": "999",
    }
    search_mock = MagicMock(return_value={"laws": [candidate]})
    detail_mock = MagicMock(return_value={"metadata": {}, "articles": []})
    with patch("laws.import_laws.search_laws", search_mock), \
         patch("laws.import_laws.get_law_detail", detail_mock):
        _run_search_api_recovery(list_file)

    detail_mock.assert_called_once_with("999")


def test_search_miss_never_lands_in_failed_msts_section(tmp_path, monkeypatch):
    list_file = tmp_path / "names.txt"
    list_file.write_text("민법\n", encoding="utf-8")

    search_mock = MagicMock(return_value={"laws": []})
    with patch("laws.import_laws.search_laws", search_mock):
        _run_search_api_recovery(list_file)

    assert failures.get_failed_msts() == {}
    assert "민법" in failures.get_search_misses()
