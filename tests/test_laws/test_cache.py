"""Tests for laws/cache.py."""

import json
from pathlib import Path

import pytest

import laws.cache as law_cache


@pytest.fixture(autouse=True)
def patch_cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(law_cache, "CACHE_DIR", tmp_path / ".cache")


def test_put_get_detail(tmp_path: Path):
    content = b"<law><mst>123</mst></law>"
    law_cache.put_detail("123", content)
    result = law_cache.get_detail("123")
    assert result == content


def test_get_detail_miss():
    result = law_cache.get_detail("nonexistent_mst_99999")
    assert result is None


def test_list_cached_msts(tmp_path: Path):
    law_cache.put_detail("111", b"<a/>")
    law_cache.put_detail("222", b"<b/>")
    msts = law_cache.list_cached_msts()
    assert set(msts) == {"111", "222"}


def test_list_cached_msts_empty():
    result = law_cache.list_cached_msts()
    assert result == []


def test_put_get_history(tmp_path: Path):
    entries = [{"법령일련번호": "111", "법령명한글": "민법", "공포일자": "19580222"}]
    law_cache.put_history("민법", entries)
    result = law_cache.get_history("민법")
    assert result == entries


def test_get_history_miss():
    result = law_cache.get_history("존재하지않는법령")
    assert result is None


def test_safe_filename_short():
    """Names under 200 bytes are returned as-is."""
    name = "민법"
    result = law_cache._safe_filename(name, ".json")
    assert result == "민법.json"


def test_safe_filename_long():
    """Names over 200 bytes get a SHA256 hash suffix."""
    # Create a name that exceeds 200 bytes in UTF-8
    long_name = "가" * 100  # 100 * 3 = 300 bytes in UTF-8
    result = law_cache._safe_filename(long_name, ".json")
    assert result.endswith(".json")
    assert len(result.encode("utf-8")) <= 200
    # Should contain underscore + hex hash portion
    assert "_" in result
