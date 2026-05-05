"""Tests for ordinances/api_client.py."""

from ordinances import api_client


class Response:
    def __init__(self, content: bytes):
        self.content = content


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

    def fake_request(url, params):
        assert url.endswith("/lawSearch.do")
        assert params["target"] == "ordin"
        assert params["knd"] == "C0001"
        return Response(xml.encode("utf-8"))

    monkeypatch.setattr(api_client, "_request", fake_request)
    result = api_client.search_ordinances(ordinance_type="조례")
    assert result["totalCnt"] == 1
    assert result["ordinances"][0]["자치법규ID"] == "2000111"


def test_search_ordinances_sends_date_range(monkeypatch):
    def fake_request(url, params):
        assert params["prmlYd"] == "20260501~20260511"
        return Response(b"<LawSearch><totalCnt>0</totalCnt><page>1</page></LawSearch>")

    monkeypatch.setattr(api_client, "_request", fake_request)
    api_client.search_ordinances(date_range="20260501~20260511")


def test_get_ordinance_detail_fetches_and_caches(monkeypatch):
    calls = []

    def fake_request(url, params):
        assert url.endswith("/lawService.do")
        assert params["target"] == "ordin"
        return Response(b"<OrdinanceService />")

    monkeypatch.setattr(api_client, "_request", fake_request)
    monkeypatch.setattr(api_client.cache, "get_detail", lambda ordinance_id: None)
    monkeypatch.setattr(api_client.cache, "put_detail", lambda ordinance_id, raw: calls.append((ordinance_id, raw)))

    assert api_client.get_ordinance_detail("2000111") == b"<OrdinanceService />"
    assert calls == [("2000111", b"<OrdinanceService />")]


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
