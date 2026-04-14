"""Tests for laws/failures.py."""

import logging
from pathlib import Path

import pytest

import laws.failures as failures


@pytest.fixture(autouse=True)
def patch_failed_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(failures, "FAILED_FILE", tmp_path / ".failed_msts.json")


def test_absent_file_returns_empty_sections():
    assert failures.get_failed_msts() == {}
    assert failures.get_search_misses() == {}


def test_classify_by_isinstance():
    assert failures.classify(ValueError("x")) == "empty_body"
    assert failures.classify(RuntimeError("x")) == "api_error"
    assert failures.classify(OSError("x")) == "io_error"
    assert failures.classify(KeyError("x")) == "metadata_missing"
    assert failures.classify(Exception("x")) == "unknown"


def test_mark_failed_persists_mst_section():
    failures.mark_failed("111", "empty_body", detail="bad", step="parse")
    assert "111" in failures.get_failed_msts()
    assert "111" not in failures.get_search_misses()


def test_mark_search_miss_goes_to_search_misses_only():
    failures.mark_search_miss("민법")
    assert "민법" in failures.get_search_misses()
    assert "민법" not in failures.get_failed_msts()


def test_mark_failed_and_quarantine_renames_stale_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(failures, "FAILED_FILE", tmp_path / ".failed_msts.json")
    law_dir = tmp_path / "kr" / "foo"
    law_dir.mkdir(parents=True)
    law_file = law_dir / "법률.md"
    law_file.write_text("content", encoding="utf-8")

    failures.mark_failed_and_quarantine(
        "999", "empty_body", "bad body", law_file, step="parse", law_name="foo"
    )

    stale = law_dir / ".법률.md.stale"
    assert stale.exists()
    assert not law_file.exists()
    assert "999" in failures.get_failed_msts()
    assert failures.get_failed_msts()["999"]["reason"] == "empty_body"


def test_mark_failed_and_quarantine_no_rename_when_absent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(failures, "FAILED_FILE", tmp_path / ".failed_msts.json")
    missing_path = tmp_path / "kr" / "nonexistent" / "법률.md"

    failures.mark_failed_and_quarantine(
        "888", "api_error", "no file", missing_path, step="fetch"
    )

    assert "888" in failures.get_failed_msts()
    assert not missing_path.exists()


def test_detail_truncated_to_500_chars():
    long_detail = "x" * 600
    failures.mark_failed("777", "api_error", detail=long_detail)
    record = failures.get_failed_msts()["777"]
    assert len(record["detail"]) == 500


def test_log_failure_emits_stable_keys(caplog):
    with caplog.at_level(logging.ERROR, logger="laws.failures"):
        failures.log_failure("parse", "123", "민법", ValueError("bad data"))

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.step == "parse"
    assert record.mst == "123"
    assert record.exc_type == "ValueError"
    assert record.exc_msg == "bad data"
