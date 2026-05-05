"""Tests for admrules/api_client.py."""

from admrules import api_client


class Response:
    def __init__(self, content: bytes):
        self.content = content


def test_search_admrules_parses_list(monkeypatch):
    xml = """
    <LawSearch>
      <totalCnt>1</totalCnt>
      <page>1</page>
      <admrul>
        <행정규칙일련번호>123</행정규칙일련번호>
        <행정규칙명>공공데이터 관리지침</행정규칙명>
        <행정규칙종류>고시</행정규칙종류>
        <발령일자>20240504</발령일자>
        <소관부처명>행정안전부</소관부처명>
      </admrul>
    </LawSearch>
    """

    def fake_request(url, params):
        assert url.endswith("/lawSearch.do")
        assert params["target"] == "admrul"
        assert params["nw"] == "1"
        return Response(xml.encode("utf-8"))

    monkeypatch.setattr(api_client, "_request", fake_request)
    result = api_client.search_admrules(knd="3")
    assert result["totalCnt"] == 1
    assert result["admrules"][0]["행정규칙명"] == "공공데이터 관리지침"


def test_search_admrules_sends_date_range(monkeypatch):
    def fake_request(url, params):
        assert params["prmlYd"] == "20260501~20260511"
        return Response(b"<LawSearch><totalCnt>0</totalCnt><page>1</page></LawSearch>")

    monkeypatch.setattr(api_client, "_request", fake_request)
    api_client.search_admrules(date_range="20260501~20260511")


def test_get_admrule_detail_uses_cache(monkeypatch):
    monkeypatch.setattr(api_client.cache, "get_detail", lambda serial: b"<cached />")
    assert api_client.get_admrule_detail("123") == b"<cached />"


def test_get_admrule_detail_fetches_and_caches(monkeypatch):
    calls = []

    def fake_request(url, params):
        assert url.endswith("/lawService.do")
        assert params["target"] == "admrul"
        return Response(b"<AdmRulService />")

    monkeypatch.setattr(api_client, "_request", fake_request)
    monkeypatch.setattr(api_client.cache, "get_detail", lambda serial: None)
    monkeypatch.setattr(api_client.cache, "put_detail", lambda serial, raw: calls.append((serial, raw)))

    assert api_client.get_admrule_detail("123") == b"<AdmRulService />"
    assert calls == [("123", b"<AdmRulService />")]


def test_search_admrules_raises_api_error(monkeypatch):
    def fake_request(url, params):
        return Response("<LawSearch><result>사용자 정보 검증에 실패</result><msg>bad key</msg></LawSearch>".encode())

    monkeypatch.setattr(api_client, "_request", fake_request)
    try:
        api_client.search_admrules()
    except RuntimeError as e:
        assert "API error" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
