"""Tests for laws/checkpoint.py."""

import json
from pathlib import Path

import pytest

import laws.checkpoint as chk


@pytest.fixture(autouse=True)
def patch_checkpoint_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(chk, "CHECKPOINT_FILE", tmp_path / ".checkpoint.json")


def test_load_empty():
    result = chk.load()
    assert result == {}


def test_save_and_load():
    data = {"processed_msts": ["111", "222"], "last_update": "2024-01-01"}
    chk.save(data)
    loaded = chk.load()
    assert loaded == data


def test_get_processed_msts():
    chk.save({"processed_msts": ["111", "222", "333"]})
    msts = chk.get_processed_msts()
    assert msts == {"111", "222", "333"}


def test_get_processed_msts_empty():
    msts = chk.get_processed_msts()
    assert msts == set()


def test_mark_processed():
    chk.mark_processed("999")
    msts = chk.get_processed_msts()
    assert "999" in msts


def test_mark_processed_idempotent():
    chk.mark_processed("111")
    chk.mark_processed("111")
    msts = chk.get_processed_msts()
    assert list(msts).count("111") == 1


def test_set_get_last_update():
    chk.set_last_update("2024-03-15")
    assert chk.get_last_update() == "2024-03-15"


def test_get_last_update_missing():
    assert chk.get_last_update() == ""


def test_load_corrupt_json(tmp_path: Path, monkeypatch):
    checkpoint_file = tmp_path / ".checkpoint.json"
    checkpoint_file.write_text("not valid json {{{{", encoding="utf-8")
    monkeypatch.setattr(chk, "CHECKPOINT_FILE", checkpoint_file)
    result = chk.load()
    assert result == {}
