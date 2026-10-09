"""Tests for admrules/cache.py."""

import importlib


def test_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("LEGALIZE_ADMRULE_CACHE_DIR", str(tmp_path))
    import admrules.cache as cache

    cache = importlib.reload(cache)
    cache.put_detail("123", b"<xml />")

    assert cache.get_detail("123") == b"<xml />"
    assert cache.list_cached_serials() == ["123"]


def test_withdrawn_xml_remains_readable_for_history(tmp_path, monkeypatch):
    from admrules import cache
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache.put_detail("1", b"old")
    cache.put_detail("2", b"current")
    assert cache.prune_details({"2"}) == ["1"]
    assert not (tmp_path / "1.xml").exists()
    assert cache.get_detail("1") == b"old"
    assert cache.list_cached_serials() == ["1", "2"]
    assert cache.prune_details({"2"}) == []
    cache.put_detail("1", b"returned")
    assert cache.get_detail("1") == b"returned"
    assert cache.list_cached_serials() == ["1", "2"]
