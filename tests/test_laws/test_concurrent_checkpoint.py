"""Concurrency tests for checkpoint.py and failures.py."""

import threading
from pathlib import Path

import pytest

import laws.checkpoint as chk
import laws.failures as failures


@pytest.fixture(autouse=True)
def patch_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(chk, "CHECKPOINT_FILE", tmp_path / ".checkpoint.json")
    monkeypatch.setattr(failures, "FAILED_FILE", tmp_path / ".failed_msts.json")


def test_threading_lock_guards_rmw_across_20_threads():
    threads = [
        threading.Thread(target=chk.mark_processed, args=(str(i),))
        for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    processed = chk.get_processed_msts()
    assert len(processed) == 20
    for i in range(20):
        assert str(i) in processed


def test_concurrent_mark_failed_and_mark_processed_interleaving():
    def do_checkpoint(i: int) -> None:
        chk.mark_processed(f"mst_{i}")

    def do_failure(i: int) -> None:
        failures.mark_failed(f"fail_{i}", "api_error")

    threads = []
    for i in range(10):
        threads.append(threading.Thread(target=do_checkpoint, args=(i,)))
        threads.append(threading.Thread(target=do_failure, args=(i,)))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    processed = chk.get_processed_msts()
    failed = failures.get_failed_msts()

    assert len(processed) == 10
    assert len(failed) == 10
    for i in range(10):
        assert f"mst_{i}" in processed
        assert f"fail_{i}" in failed
