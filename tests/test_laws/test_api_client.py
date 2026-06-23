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


@responses_lib.activate
def test_get_law_detail_preserves_article_kind():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<법령>
  <기본정보>
    <법령명_한글><![CDATA[테스트법]]></법령명_한글>
    <법종구분>법률</법종구분>
  </기본정보>
  <조문>
    <조문단위>
      <조문번호>898</조문번호>
      <조문여부>전문</조문여부>
      <조문내용><![CDATA[제1항 협의상 파양]]></조문내용>
    </조문단위>
    <조문단위>
      <조문번호>898</조문번호>
      <조문여부>조문</조문여부>
      <조문제목><![CDATA[협의상 파양]]></조문제목>
      <조문내용><![CDATA[제898조(협의상 파양) 본문]]></조문내용>
    </조문단위>
  </조문>
</법령>""".encode()
    responses_lib.add(responses_lib.GET, f"{LAW_API_BASE}/lawService.do", body=xml, status=200)
    detail = api_client.get_law_detail("32")
    assert [article["조문여부"] for article in detail["articles"]] == ["전문", "조문"]


@responses_lib.activate
def test_get_law_detail_extracts_attachment_links():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<법령>
  <기본정보>
    <법령명_한글><![CDATA[테스트법]]></법령명_한글>
    <법종구분>법률</법종구분>
  </기본정보>
  <별표>
    <별표단위>
      <별표번호>0001</별표번호>
      <별표가지번호>00</별표가지번호>
      <별표구분>별표</별표구분>
      <별표제목><![CDATA[수수료]]></별표제목>
      <별표서식파일링크>/LSW/flDownload.do?flSeq=1</별표서식파일링크>
      <별표서식PDF파일링크>/LSW/flDownload.do?flSeq=2</별표서식PDF파일링크>
    </별표단위>
  </별표>
</법령>""".encode()
    responses_lib.add(responses_lib.GET, f"{LAW_API_BASE}/lawService.do", body=xml, status=200)

    detail = api_client.get_law_detail("33")

    assert detail["attachments"] == [{
        "별표번호": "0001",
        "별표가지번호": "00",
        "별표구분": "별표",
        "제목": "수수료",
        "파일링크": "https://www.law.go.kr/LSW/flDownload.do?flSeq=1",
        "PDF링크": "https://www.law.go.kr/LSW/flDownload.do?flSeq=2",
    }]


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
def test_get_law_history_matches_full_name_after_removing_spaces():
    target = "국립사범대학 졸업자 중 교원미임용자 임용 등에 관한 특별법 시행령"
    old_spelling = "국립사범대학졸업자중교원미임용자임용등에관한특별법시행령"
    other_name = "국립사범대학졸업자중교원미임용자임용등에관한특별법"
    html = f"""<html><body><table>
<tr>
  <td>1</td>
  <td><a href="/lsInfoP.do?MST=62094">{old_spelling}</a></td>
  <td>교육부</td>
  <td>제정</td>
  <td>대통령령</td>
  <td>제 18473호</td>
  <td>2004.7.24</td>
  <td>2004.7.25</td>
  <td></td>
</tr>
<tr>
  <td>2</td>
  <td><a href="/lsInfoP.do?MST=59660">{other_name}</a></td>
  <td>교육부</td>
  <td>제정</td>
  <td>법률</td>
  <td>제 7068호</td>
  <td>2004.1.20</td>
  <td>2004.1.20</td>
  <td></td>
</tr>
</table></body></html>"""
    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body=html, status=200,
        content_type="text/html; charset=utf-8",
    )

    history = api_client.get_law_history(target)

    assert [entry["법령일련번호"] for entry in history] == ["62094"]
    assert history[0]["법령명한글"] == old_spelling


@responses_lib.activate
def test_get_law_history_from_cache(tmp_path: Path):
    entries = [{"법령일련번호": "100001", "법령명한글": "민법", "공포일자": "19580222"}]
    law_cache.put_history("민법", entries)
    history = api_client.get_law_history("민법")
    assert history == entries
    assert len(responses_lib.calls) == 0
