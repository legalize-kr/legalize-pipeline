"""Tests for the failure ledger's clearing and cross-process safety."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from laws import failures


@pytest.fixture(autouse=True)
def _ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(failures, "FAILED_FILE", tmp_path / "failed.json")
    monkeypatch.setattr(failures, "LOCK_FILE", tmp_path / "failed.lock")
    monkeypatch.setattr(failures, "_FAILED_KEYS", None)
    monkeypatch.setattr(failures, "_FAILED_STAMP", None)
    return tmp_path


def test_clear_failed_removes_a_recorded_entry():
    failures.mark_failed("100", "empty_body")

    assert failures.clear_failed("100") is True
    assert failures.get_failed_msts() == {}


def test_clear_failed_is_false_for_unknown_mst():
    failures.mark_failed("100", "empty_body")

    assert failures.clear_failed("999") is False
    assert set(failures.get_failed_msts()) == {"100"}


def test_clear_failed_normalises_the_key_type():
    failures.mark_failed("100", "empty_body")

    assert failures.clear_failed(100) is True


def test_clear_failed_sees_entries_written_by_another_process(_ledger):
    """The key cache must revalidate, or a parallel worker's entry is missed."""
    failures.mark_failed("100", "empty_body")  # seeds the cache

    # Simulate a sibling worker appending to the same ledger on disk.
    data = json.loads((_ledger / "failed.json").read_text(encoding="utf-8"))
    data["failed_msts"]["200"] = {"reason": "api_error"}
    (_ledger / "failed.json").write_text(json.dumps(data), encoding="utf-8")

    assert failures.clear_failed("200") is True


def _worker_source(ledger: Path, base: int, repo: Path) -> str:
    return (
        f"import os, sys\n"
        f"os.environ['LEGALIZE_CACHE_DIR'] = {str(ledger)!r}\n"
        f"sys.path.insert(0, {str(repo)!r})\n"
        f"from laws.failures import mark_failed\n"
        f"for i in range({base}, {base} + 50):\n"
        f"    mark_failed(str(i), 'test')\n"
    )


def test_concurrent_writers_do_not_lose_entries(tmp_path):
    """Workers run in parallel, so the ledger needs cross-process locking."""
    ledger = tmp_path / "cache"
    ledger.mkdir()
    repo = Path(__file__).resolve().parents[2]

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _worker_source(ledger, base, repo)],
            env={**os.environ, "LEGALIZE_CACHE_DIR": str(ledger)},
        )
        for base in (1000, 2000, 3000, 4000)
    ]
    for proc in procs:
        assert proc.wait() == 0

    data = json.loads((ledger / ".failed_msts.json").read_text(encoding="utf-8"))
    assert len(data["failed_msts"]) == 200
