"""Tests for admrules/cache.py."""

import importlib


def test_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("LEGALIZE_ADMRULE_CACHE_DIR", str(tmp_path))
    import admrules.cache as cache

    cache = importlib.reload(cache)
    cache.put_detail("123", b"<xml />")

    assert cache.get_detail("123") == b"<xml />"
    assert cache.list_cached_serials() == ["123"]
