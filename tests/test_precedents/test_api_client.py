"""Tests for precedents/api_client.py."""

from pathlib import Path

import pytest
import responses as responses_lib

import precedents.cache as prec_cache
import precedents.api_client as prec_api

LAW_API_BASE = "http://www.law.go.kr/DRF"
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(autouse=True)
def patch_prec_cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(prec_cache, "PREC_CACHE_DIR", tmp_path / "precedent")


@pytest.fixture(autouse=True)
def patch_api_key(monkeypatch):
    monkeypatch.setattr(prec_api, "LAW_API_KEY", "testkey")
    from core.throttle import Throttle
    monkeypatch.setattr(prec_api, "_throttle", Throttle(delay_seconds=0))


@responses_lib.activate
def test_search_precedents_parses_xml():
    xml = (FIXTURES_DIR / "prec_search_response.xml").read_bytes()
    responses_lib.add(responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do", body=xml, status=200)
    result = prec_api.search_precedents()
    assert result["totalCnt"] == 2
    assert len(result["precedents"]) == 2
    assert result["precedents"][0]["판례일련번호"] == "123456"
    assert result["precedents"][0]["법원명"] == "대법원"


@responses_lib.activate
def test_search_precedents_error():
    xml = (FIXTURES_DIR / "prec_error_response.xml").read_bytes()
    responses_lib.add(responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do", body=xml, status=200)
    with pytest.raises(RuntimeError, match="실패"):
        prec_api.search_precedents()


@responses_lib.activate
def test_get_precedent_detail_from_api(tmp_path: Path):
    xml = (FIXTURES_DIR / "prec_detail_response.xml").read_bytes()
    responses_lib.add(responses_lib.GET, f"{LAW_API_BASE}/lawService.do", body=xml, status=200)
    result = prec_api.get_precedent_detail("123456")
    assert result == xml
    # Should now be cached
    cached = prec_cache.get_detail("123456")
    assert cached == xml


@responses_lib.activate
def test_get_precedent_detail_from_cache(tmp_path: Path):
    xml = (FIXTURES_DIR / "prec_detail_response.xml").read_bytes()
    prec_cache.put_detail("123456", xml)
    result = prec_api.get_precedent_detail("123456")
    assert result == xml
    assert len(responses_lib.calls) == 0
