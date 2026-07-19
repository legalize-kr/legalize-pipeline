"""Tests for ordinances/api_client.py."""

import pytest

from ordinances import api_client


class Response:
    def __init__(self, content: bytes):
        self.content = content


def test_request_retries_404_by_default(monkeypatch):
    options = {}

    def fake_make_request(url, params, **kwargs):
        options.update(kwargs)
        return Response(b"<ok />")

    monkeypatch.setattr(api_client, "make_request", fake_make_request)

    api_client._request("https://example.test/lawSearch.do", {})

    assert options["non_retry_statuses"] == ()


def test_search_ordinances_parses_list(monkeypatch):
    xml = """
    <LawSearch>
      <totalCnt>1</totalCnt>
      <page>1</page>
      <ordin>
        <자치법규ID>2000111</자치법규ID>
        <자치법규명>서울특별시 테스트 조례</자치법규명>
        <자치법규종류>조례</자치법규종류>
      </ordin>
    </LawSearch>
    """

    def fake_request(url, params, *, on_attempt=None):
        assert on_attempt is None
        assert url.endswith("/lawSearch.do")
        assert params["target"] == "ordin"
        assert params["query"] == "서울특별시 테스트 조례"
        assert params["knd"] == "C0001"
        assert params["nw"] == "2"
        return Response(xml.encode("utf-8"))

    monkeypatch.setattr(api_client, "_request", fake_request)
    result = api_client.search_ordinances(query="서울특별시 테스트 조례", ordinance_type="조례", nw="2")
    assert result["totalCnt"] == 1
    assert result["ordinances"][0]["자치법규ID"] == "2000111"


def test_search_ordinances_sends_date_range(monkeypatch):
    def fake_request(url, params, *, on_attempt=None):
        assert on_attempt is None
        assert params["prmlYd"] == "20260501~20260511"
        return Response(b"<LawSearch><totalCnt>0</totalCnt><page>1</page></LawSearch>")

    monkeypatch.setattr(api_client, "_request", fake_request)
    api_client.search_ordinances(date_range="20260501~20260511")


def test_search_ordinances_retries_malformed_xml(monkeypatch):
    responses = iter(
        [
            Response(b"<LawSearch><![CDATA["),
            Response(b"<LawSearch><totalCnt>0</totalCnt><page>3</page></LawSearch>"),
        ]
    )
    calls = []

    def fake_request(url, params):
        calls.append((url, params.copy()))
        return next(responses)

    monkeypatch.setattr(api_client, "_request", fake_request)

    result = api_client.search_ordinances(page=3)

    assert result["page"] == 3
    assert len(calls) == 2


def test_search_ordinances_stops_after_malformed_xml_retries(monkeypatch):
    calls = []

    def fake_request(url, params):
        calls.append((url, params.copy()))
        return Response(b"<LawSearch><![CDATA[")

    monkeypatch.setattr(api_client, "_request", fake_request)

    with pytest.raises(api_client.ElementTree.ParseError):
        api_client.search_ordinances()

    assert len(calls) == api_client.MAX_RETRIES + 1


def test_get_ordinance_detail_fetches_and_caches(monkeypatch):
    calls = []

    def fake_request(url, params, *, on_attempt=None, timeout=30, non_retry_statuses=()):
        assert on_attempt is None
        assert timeout == 120
        assert non_retry_statuses == {404}
        assert url.endswith("/lawService.do")
        assert params["target"] == "ordin"
        assert params["ID"] == "2000111"
        return Response(
            "<OrdinanceService><자치법규ID>2000111</자치법규ID></OrdinanceService>".encode()
        )

    monkeypatch.setattr(api_client, "_request", fake_request)
    monkeypatch.setattr(api_client.cache, "get_detail", lambda ordinance_id, **kwargs: None)
    monkeypatch.setattr(
        api_client.cache,
        "put_detail",
        lambda ordinance_id, raw, **kwargs: calls.append((ordinance_id, raw, kwargs)),
    )

    raw = api_client.get_ordinance_detail("2000111")
    assert b"2000111" in raw
    assert calls == [("2000111", raw, {"historical": False})]


def test_get_ordinance_detail_prefers_mst_when_available(monkeypatch):
    calls = []

    def fake_request(url, params, *, on_attempt=None, timeout=30, non_retry_statuses=()):
        assert on_attempt is None
        assert timeout == 120
        assert non_retry_statuses == {404}
        assert url.endswith("/lawService.do")
        assert params["target"] == "ordin"
        assert params["MST"] == "1805167"
        assert "ID" not in params
        return Response(
            "<OrdinanceService><자치법규ID>2148386</자치법규ID><자치법규일련번호>1805167</자치법규일련번호></OrdinanceService>".encode()
        )

    monkeypatch.setattr(api_client, "_request", fake_request)
    monkeypatch.setattr(api_client.cache, "get_detail", lambda ordinance_id, **kwargs: None)
    monkeypatch.setattr(
        api_client.cache,
        "put_detail",
        lambda ordinance_id, raw, **kwargs: calls.append((ordinance_id, raw, kwargs)),
    )

    raw = api_client.get_ordinance_detail("2148386", mst="1805167")
    assert b"1805167" in raw
    assert calls == [("1805167", raw, {"historical": True})]


def test_get_ordinance_detail_rejects_xhtml_error_page(monkeypatch):
    monkeypatch.setattr(api_client.cache, "get_detail", lambda ordinance_id, **kwargs: None)
    monkeypatch.setattr(
        api_client,
        "_request",
        lambda url, params, **kwargs: Response(b"<html><head /></html>"),
    )

    try:
        api_client.get_ordinance_detail("2148386", mst="1164395")
    except RuntimeError as exc:
        assert "invalid 자치법규일련번호=<missing>" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_get_ordinance_detail_raises_no_result_for_law_message(monkeypatch):
    monkeypatch.setattr(api_client.cache, "get_detail", lambda ordinance_id, **kwargs: None)
    monkeypatch.setattr(
        api_client,
        "_request",
        lambda url, params, **kwargs: Response(
            "<?xml version='1.0'?><Law>일치하는 자치법규가 없습니다. 자치법규명을 확인하여 주십시오.</Law>".encode()
        ),
    )

    with pytest.raises(api_client.NoResultError):
        api_client.get_ordinance_detail("2201906", mst="1536019")


def test_search_ordinances_raises_api_error(monkeypatch):
    def fake_request(url, params):
        return Response("<LawSearch><result>사용자 정보 검증에 실패</result><msg>bad key</msg></LawSearch>".encode())

    monkeypatch.setattr(api_client, "_request", fake_request)
    try:
        api_client.search_ordinances()
    except RuntimeError as e:
        assert "API error" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
