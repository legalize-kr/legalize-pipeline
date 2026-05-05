"""Tests for admrules/checkpoint.py."""

import importlib


def test_checkpoint_page_and_detail_round_trip(tmp_path, monkeypatch):
    import admrules.checkpoint as checkpoint

    monkeypatch.setattr(checkpoint, "CHECKPOINT_FILE", tmp_path / "checkpoint.json")
    checkpoint = importlib.reload(checkpoint)
    monkeypatch.setattr(checkpoint, "CHECKPOINT_FILE", tmp_path / "checkpoint.json")

    checkpoint.mark_page_processed("3", 2, "1741000")
    checkpoint.mark_detail_processed("123")

    assert checkpoint.is_page_processed("3", 2, "1741000")
    assert checkpoint.get_processed_serials() == {"123"}
