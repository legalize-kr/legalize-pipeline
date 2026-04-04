"""Tests for laws/api_client.py."""

from pathlib import Path
from unittest.mock import patch

import pytest
import responses as responses_lib

import laws.cache as law_cache
import laws.api_client as api_client

LAW_API_BASE = "http://www.law.go.kr/DRF"
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(autouse=True)
def patch_cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(law_cache, "CACHE_DIR", tmp_path / ".cache")


@pytest.fixture(autouse=True)
def patch_api_key(monkeypatch):
    monkeypatch.setattr(api_client, "LAW_API_KEY", "testkey")
    # Also patch the throttle so tests run fast
    from core.throttle import Throttle
    monkeypatch.setattr(api_client, "_throttle", Throttle(delay_seconds=0))


@responses_lib.activate
def test_search_laws_parses_xml():
    xml = (FIXTURES_DIR / "search_response.xml").read_bytes()
    responses_lib.add(responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do", body=xml, status=200)
    result = api_client.search_laws(query="민법", page=1)
    assert result["totalCnt"] == 2
    assert result["page"] == 1
    assert len(result["laws"]) == 2
    assert result["laws"][0]["법령명한글"] == "민법"


@responses_lib.activate
def test_search_laws_empty():
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<LawSearch><totalCnt>0</totalCnt><page>1</page></LawSearch>"""
    responses_lib.add(responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do", body=xml, status=200)
    result = api_client.search_laws()
    assert result["totalCnt"] == 0
    assert result["laws"] == []


@responses_lib.activate
def test_get_law_detail_from_api():
    xml = (FIXTURES_DIR / "detail_response.xml").read_bytes()
    responses_lib.add(responses_lib.GET, f"{LAW_API_BASE}/lawService.do", body=xml, status=200)
    detail = api_client.get_law_detail("253527")
    assert detail["metadata"]["법령명한글"] == "민법"
    assert detail["metadata"]["법령구분"] == "법률"
    assert len(detail["articles"]) >= 1
    assert len(detail["addenda"]) >= 1


@responses_lib.activate
def test_get_law_detail_from_cache(tmp_path: Path):
    xml = (FIXTURES_DIR / "detail_response.xml").read_bytes()
    # Pre-populate cache
    law_cache.put_detail("253527", xml)
    # No HTTP mock — if it hits the network, responses will raise
    detail = api_client.get_law_detail("253527")
    assert detail["metadata"]["법령명한글"] == "민법"
    # responses_lib would have 0 calls since cache was hit
    assert len(responses_lib.calls) == 0


@responses_lib.activate
def test_get_law_detail_api_error():
    xml = (FIXTURES_DIR / "error_response.xml").read_bytes()
    responses_lib.add(responses_lib.GET, f"{LAW_API_BASE}/lawService.do", body=xml, status=200)
    with pytest.raises(RuntimeError, match="실패"):
        api_client.get_law_detail("000000")


def test_parse_dot_date():
    assert api_client._parse_dot_date("1958.2.22") == "19580222"
    assert api_client._parse_dot_date("2024.1.1") == "20240101"
    assert api_client._parse_dot_date("") == ""


@responses_lib.activate
def test_get_law_history_pagination():
    html = (FIXTURES_DIR / "history_response.html").read_bytes()
    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body=html, status=200,
        content_type="text/html; charset=utf-8",
    )
    history = api_client.get_law_history("민법")
    assert len(history) >= 2
    # Sorted oldest first
    dates = [h["공포일자"] for h in history]
    assert dates == sorted(dates)
    # First entry is the 1958 제정
    assert history[0]["공포일자"] == "19580222"
    assert history[0]["법령일련번호"] == "100001"


@responses_lib.activate
def test_get_law_history_from_cache(tmp_path: Path):
    entries = [{"법령일련번호": "100001", "법령명한글": "민법", "공포일자": "19580222"}]
    law_cache.put_history("민법", entries)
    history = api_client.get_law_history("민법")
    assert history == entries
    assert len(responses_lib.calls) == 0
