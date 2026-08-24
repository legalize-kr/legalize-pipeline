"""Tests for laws/api_client.py."""

from pathlib import Path
from unittest.mock import patch

import pytest
import requests
import responses as responses_lib

import laws.cache as law_cache
import laws.api_client as api_client
from laws.converter import law_to_markdown

LAW_API_BASE = "https://www.law.go.kr/DRF"
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
def test_search_laws_raises_on_api_error_response():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <result>사용자 정보 검증에 실패하였습니다.</result>
  <msg>등록된 서버에서 호출해 주세요.</msg>
</Response>""".encode()
    responses_lib.add(responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do", body=xml, status=200)

    with pytest.raises(RuntimeError, match="사용자 정보 검증"):
        api_client.search_laws(query="민법")


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
def test_get_law_detail_can_disable_http_retries():
    responses_lib.add(
        responses_lib.GET,
        f"{LAW_API_BASE}/lawService.do",
        status=500,
    )

    with pytest.raises(requests.HTTPError, match="500 Server Error"):
        api_client.get_law_detail("37612", max_retries=0)

    assert len(responses_lib.calls) == 1


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


def _history_row(
    mst: str,
    name: str,
    *,
    amendment: str = "제정",
    law_type: str = "대통령령",
    prom_date: str = "2004.7.24",
) -> str:
    return (
        "<tr>"
        "<td>1</td>"
        f'<td><a href="/lsInfoP.do?MST={mst}">{name}</a></td>'
        "<td>교육부</td>"
        f"<td>{amendment}</td>"
        f"<td>{law_type}</td>"
        "<td>제 18455호</td>"
        f"<td>{prom_date}</td>"
        f"<td>{prom_date}</td>"
        "<td></td>"
        "</tr>"
    )


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
def test_get_law_history_matches_full_name_ignoring_whitespace_only():
    current_name = "국립사범대학 졸업자 중 교원미임용자 임용 등에 관한 특별법 시행령"
    old_name = "국립사범대학졸업자중교원미임용자임용등에관한특별법시행령"
    other_name = "국립사범대학졸업자중교원미임용자임용등에관한특별법시행규칙"
    html = (
        "<html><body><table>"
        + _history_row("62094", old_name)
        + _history_row("62095", other_name)
        + "</table></body></html>"
    )
    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body=html, status=200,
        content_type="text/html; charset=utf-8",
    )

    history = api_client.get_law_history(current_name)

    assert [entry["법령일련번호"] for entry in history] == ["62094"]
    assert history[0]["법령명한글"] == old_name


@responses_lib.activate
def test_get_law_history_matches_equivalent_middle_dots():
    current_name = "수용ㆍ사용에 관한 법률"
    old_name = "수용·사용에 관한 법률"
    responses_lib.add(
        responses_lib.GET,
        f"{LAW_API_BASE}/lawSearch.do",
        body="<html><body><table>" + _history_row("62096", old_name) + "</table></body></html>",
        status=200,
        content_type="text/html; charset=utf-8",
    )

    history = api_client.get_law_history(current_name, refresh=True)

    assert [entry["법령일련번호"] for entry in history] == ["62096"]


@responses_lib.activate
def test_get_law_history_falls_back_to_canonical_middle_dot_query():
    law_name = "인지 첩부·첨부 및 공탁 제공에 관한 특례법"
    responses_lib.add(
        responses_lib.GET,
        f"{LAW_API_BASE}/lawSearch.do",
        body="<html><body></body></html>",
        status=200,
        content_type="text/html; charset=utf-8",
    )
    responses_lib.add(
        responses_lib.GET,
        f"{LAW_API_BASE}/lawSearch.do",
        body="<html><body><table>" + _history_row("130810", law_name) + "</table></body></html>",
        status=200,
        content_type="text/html; charset=utf-8",
    )

    history = api_client.get_law_history(law_name, refresh=True)

    assert [entry["법령일련번호"] for entry in history] == ["130810"]
    assert responses_lib.calls[1].request.params["query"] == (
        "인지 첩부ㆍ첨부 및 공탁 제공에 관한 특례법"
    )


@responses_lib.activate
def test_get_law_history_falls_back_to_longest_token_for_long_name():
    law_name = (
        "대한민국과 아메리카합중국 간의 상호방위조약 제4조에 의한 시설과 구역 및 "
        "대한민국에서의 합중국 군대의 지위에 관한 협정의 시행에 관한 형사특별법"
    )
    responses_lib.add(
        responses_lib.GET,
        f"{LAW_API_BASE}/lawSearch.do",
        body="<html><body></body></html>",
        status=200,
        content_type="text/html; charset=utf-8",
    )
    responses_lib.add(
        responses_lib.GET,
        f"{LAW_API_BASE}/lawSearch.do",
        body="<html><body><table>" + _history_row("112382", law_name) + "</table></body></html>",
        status=200,
        content_type="text/html; charset=utf-8",
    )

    history = api_client.get_law_history(law_name, refresh=True)

    assert [entry["법령일련번호"] for entry in history] == ["112382"]
    assert responses_lib.calls[1].request.params["query"] == "아메리카합중국"


@responses_lib.activate
def test_get_law_history_falls_back_to_suffix_for_long_name_without_spaces():
    law_name = (
        "대한민국과아메리카합중국간의상호방위조약제4조에의한시설과구역및대한민국에서의"
        "합중국군대의지위에관한협정의시행에관한민사특별법시행령"
    )
    responses_lib.add(
        responses_lib.GET,
        f"{LAW_API_BASE}/lawSearch.do",
        body="<html><body></body></html>",
        status=200,
        content_type="text/html; charset=utf-8",
    )
    responses_lib.add(
        responses_lib.GET,
        f"{LAW_API_BASE}/lawSearch.do",
        body="<html><body><table>" + _history_row("192768", law_name) + "</table></body></html>",
        status=200,
        content_type="text/html; charset=utf-8",
    )

    history = api_client.get_law_history(law_name, refresh=True)

    assert [entry["법령일련번호"] for entry in history] == ["192768"]
    assert responses_lib.calls[1].request.params["query"] == law_name[-20:]


@responses_lib.activate
def test_get_law_history_refresh_preserves_cached_msts_missing_from_response():
    law_name = "국군방첩사령부령"
    cached_amendment = {
        "법령일련번호": "249921",
        "법령명한글": law_name,
        "제개정구분명": "제정",
        "법령구분": "대통령령",
        "공포번호": "33409",
        "공포일자": "20230418",
        "시행일자": "20230418",
    }
    cached_repeal = {
        "법령일련번호": "288331",
        "법령명한글": law_name,
        "제개정구분명": "폐지",
        "법령구분": "대통령령",
        "공포번호": "36526",
        "공포일자": "20260728",
        "시행일자": "20260728",
    }
    law_cache.put_history(law_name, [cached_amendment, cached_repeal])
    responses_lib.add(
        responses_lib.GET,
        f"{LAW_API_BASE}/lawSearch.do",
        body=(
            "<html><body><table>"
            + _history_row(
                "249921",
                law_name,
                amendment="일부개정",
                prom_date="2023.4.18",
            )
            + "</table></body></html>"
        ),
        status=200,
        content_type="text/html; charset=utf-8",
    )

    history = api_client.get_law_history(law_name, refresh=True)

    assert [entry["법령일련번호"] for entry in history] == ["249921", "288331"]
    assert history[0]["제개정구분명"] == "일부개정"
    assert law_cache.get_history(law_name) == history


@responses_lib.activate
def test_get_law_history_does_not_retry_name_mismatch(monkeypatch):
    monkeypatch.setattr(api_client, "_EMPTY_HISTORY_RETRIES", 3)
    responses_lib.add(
        responses_lib.GET,
        f"{LAW_API_BASE}/lawSearch.do",
        body="<html><body><table>" + _history_row("62097", "다른 법령") + "</table></body></html>",
        status=200,
        content_type="text/html; charset=utf-8",
    )

    history = api_client.get_law_history("대상 법령", refresh=True)

    assert history == []
    assert len(responses_lib.calls) == 1


@responses_lib.activate
def test_get_law_history_raises_on_api_error_response():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <result>사용자 정보 검증에 실패하였습니다.</result>
  <msg>등록된 서버에서 호출해 주세요.</msg>
</Response>"""
    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body=xml, status=200,
        content_type="text/html; charset=utf-8",
    )

    with pytest.raises(RuntimeError, match="사용자 정보 검증"):
        api_client.get_law_history("민법", refresh=True)


@responses_lib.activate
def test_get_law_history_retries_empty_history_response(monkeypatch):
    monkeypatch.setattr(api_client, "_EMPTY_HISTORY_RETRIES", 2)
    monkeypatch.setattr(api_client.time, "sleep", lambda _: None)
    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body="<html><body></body></html>", status=200,
        content_type="text/html; charset=utf-8",
    )
    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body="<html><body><table>" + _history_row("100001", "민법") + "</table></body></html>",
        status=200,
        content_type="text/html; charset=utf-8",
    )

    history = api_client.get_law_history("민법", refresh=True)

    assert [entry["법령일련번호"] for entry in history] == ["100001"]
    assert len(responses_lib.calls) == 2


@responses_lib.activate
def test_get_law_history_does_not_retry_active_known_empty(monkeypatch):
    monkeypatch.setattr(
        api_client,
        "_active_known_empty_history",
        lambda _name: {"reason": "upstream_empty", "expires_on": "2099-01-01"},
    )
    responses_lib.add(
        responses_lib.GET,
        f"{LAW_API_BASE}/lawSearch.do",
        body="<html><body></body></html>",
        status=200,
        content_type="text/html; charset=utf-8",
    )

    history = api_client.get_law_history("알려진 빈 법령", refresh=True)

    assert history == []
    assert len(responses_lib.calls) == 1


@responses_lib.activate
def test_get_law_history_from_cache(tmp_path: Path):
    entries = [{"법령일련번호": "100001", "법령명한글": "민법", "공포일자": "19580222"}]
    law_cache.put_history("민법", entries)
    history = api_client.get_law_history("민법")
    assert history == entries
    assert len(responses_lib.calls) == 0


def _items_xml(nested: bool) -> bytes:
    items = (
        "<목><목번호><![CDATA[가.]]></목번호><목내용><![CDATA[가. 첫째 요건]]></목내용></목>"
        "<목><목번호><![CDATA[나.]]></목번호><목내용><![CDATA[나. 둘째 요건]]></목내용></목>"
    )
    second = (
        "<호><호번호><![CDATA[2.]]></호번호>"
        "<호내용><![CDATA[2. 다음 각 목의 요건을 갖춘 경우]]></호내용>"
    )
    second += items + "</호>" if nested else "</호>" + items
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<법령>
  <기본정보>
    <법령명_한글><![CDATA[테스트법]]></법령명_한글>
    <법종구분>법률</법종구분>
  </기본정보>
  <조문>
    <조문단위>
      <조문번호>3</조문번호>
      <조문여부>조문</조문여부>
      <조문제목><![CDATA[적용 대상]]></조문제목>
      <조문내용><![CDATA[제3조(적용 대상) 본문]]></조문내용>
      <항>
        <항번호><![CDATA[①]]></항번호>
        <항내용><![CDATA[① 다음 각 호의 어느 하나에 해당하는 경우를 말한다.]]></항내용>
        <호><호번호><![CDATA[1.]]></호번호><호내용><![CDATA[1. 첫째 경우]]></호내용></호>
        {second}
      </항>
    </조문단위>
  </조문>
</법령>""".encode()


@pytest.mark.parametrize("nested", [True, False], ids=["nested", "sibling"])
@responses_lib.activate
def test_get_law_detail_preserves_items_in_both_upstream_layouts(nested: bool):
    responses_lib.add(
        responses_lib.GET,
        f"{LAW_API_BASE}/lawService.do",
        body=_items_xml(nested),
        status=200,
    )

    detail = api_client.get_law_detail("37612")
    subparagraphs = detail["articles"][0]["항"][0]["호"]

    assert [len(subparagraph["목"]) for subparagraph in subparagraphs] == [0, 2]
    assert subparagraphs[1]["목"][0]["목번호"] == "가."
    assert subparagraphs[1]["목"][1]["목내용"] == "나. 둘째 요건"
    markdown = law_to_markdown(detail)
    assert "    가\\. 첫째 요건" in markdown
    assert "    나\\. 둘째 요건" in markdown
