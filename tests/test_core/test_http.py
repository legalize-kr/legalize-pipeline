"""Tests for core/http.py."""

import hashlib
import importlib
from unittest.mock import MagicMock

import pytest
import responses as responses_lib
from requests.exceptions import ConnectionError
from requests.exceptions import HTTPError
from requests.exceptions import RequestException

from core.http import make_request
from core.throttle import Throttle

LAW_API_BASE = "https://www.law.go.kr/DRF"
TEST_URL = f"{LAW_API_BASE}/lawSearch.do"
MAINTENANCE_HTML = """<!DOCTYPE HTML>
<html><head><title>시스템 점검</title></head><body>시스템 점검<br></body></html>""".encode()


def _throttle() -> Throttle:
    t = Throttle(delay_seconds=0)
    return t


@responses_lib.activate
def test_make_request_success():
    responses_lib.add(responses_lib.GET, TEST_URL, body=b"<ok/>", status=200)
    resp = make_request(TEST_URL, {"target": "law"}, throttle=_throttle(), api_key="testkey")
    assert resp.status_code == 200
    assert resp.content == b"<ok/>"


def test_make_request_uses_configured_timeout(monkeypatch):
    response = MagicMock(status_code=200)
    response.raise_for_status.return_value = None
    get = MagicMock(return_value=response)
    monkeypatch.setattr("core.http.requests.get", get)

    make_request(
        TEST_URL,
        {"target": "law"},
        throttle=_throttle(),
        api_key="testkey",
        timeout=120,
    )

    get.assert_called_once_with(
        TEST_URL,
        params={"target": "law", "OC": "testkey"},
        timeout=120,
    )


@responses_lib.activate
def test_make_request_adds_api_key():
    """OC parameter is injected automatically."""
    responses_lib.add(responses_lib.GET, TEST_URL, body=b"<ok/>", status=200)
    make_request(TEST_URL, {"target": "law"}, throttle=_throttle(), api_key="mykey")
    assert responses_lib.calls[0].request.url.count("OC=mykey") == 1


@responses_lib.activate
def test_make_request_retry_on_error():
    """On ConnectionError, retries up to max_retries."""
    responses_lib.add(responses_lib.GET, TEST_URL, body=ConnectionError("network down"))
    responses_lib.add(responses_lib.GET, TEST_URL, body=b"<ok/>", status=200)
    resp = make_request(
        TEST_URL, {}, throttle=_throttle(), api_key="k",
        max_retries=2, backoff_base=0.0
    )
    assert resp.status_code == 200
    assert len(responses_lib.calls) == 2


@responses_lib.activate
def test_make_request_adds_jitter_to_backoff(monkeypatch):
    sleep = MagicMock()
    monkeypatch.setattr("core.http.random.uniform", lambda _start, _end: 0.5)
    monkeypatch.setattr("core.http.time.sleep", sleep)
    responses_lib.add(responses_lib.GET, TEST_URL, body=ConnectionError("network down"))
    responses_lib.add(responses_lib.GET, TEST_URL, body=b"<ok/>", status=200)

    make_request(
        TEST_URL, {}, throttle=_throttle(), api_key="k",
        max_retries=1, backoff_base=2.0,
    )

    sleep.assert_called_once_with(2.5)


@responses_lib.activate
def test_make_request_retry_on_429():
    """On 429, retries and eventually succeeds."""
    responses_lib.add(responses_lib.GET, TEST_URL, status=429)
    responses_lib.add(responses_lib.GET, TEST_URL, body=b"<ok/>", status=200)
    resp = make_request(
        TEST_URL, {}, throttle=_throttle(), api_key="k",
        max_retries=2, backoff_base=0.0
    )
    assert resp.status_code == 200
    assert len(responses_lib.calls) == 2


@responses_lib.activate
def test_make_request_exceeds_retries():
    """After exhausting retries, raises RuntimeError."""
    for _ in range(4):
        responses_lib.add(responses_lib.GET, TEST_URL, body=ConnectionError("fail"))
    with pytest.raises((RuntimeError, ConnectionError)):
        make_request(
            TEST_URL, {}, throttle=_throttle(), api_key="k",
            max_retries=2, backoff_base=0.0
        )


@responses_lib.activate
def test_make_request_does_not_retry_selected_status():
    responses_lib.add(responses_lib.GET, TEST_URL, status=404)

    with pytest.raises(HTTPError):
        make_request(
            TEST_URL,
            {},
            throttle=_throttle(),
            api_key="k",
            max_retries=3,
            backoff_base=0.0,
            non_retry_statuses={404},
        )

    assert len(responses_lib.calls) == 1


@responses_lib.activate
def test_make_request_reports_each_attempt():
    attempts = []
    responses_lib.add(responses_lib.GET, TEST_URL, body=ConnectionError("network down"))
    responses_lib.add(responses_lib.GET, TEST_URL, body=b"<ok/>", status=200)

    make_request(
        TEST_URL,
        {},
        throttle=_throttle(),
        api_key="k",
        max_retries=2,
        backoff_base=0.0,
        on_attempt=lambda: attempts.append(True),
    )

    assert len(attempts) == 2


@pytest.mark.parametrize("body", [
    MAINTENANCE_HTML,
    b"\xef\xbb\xbf \r\n<HTML lang='ko'><body>Maintenance</body></HTML>",
    b'<?xml version="1.0"?><html><body>Maintenance</body></html>',
])
@responses_lib.activate
def test_make_request_retries_html_for_xml(body, monkeypatch):
    sleep = MagicMock()
    monkeypatch.setattr("core.http.time.sleep", sleep)
    monkeypatch.setattr("core.http.random.uniform", lambda *_: 0)
    responses_lib.add(responses_lib.GET, TEST_URL, body=body, status=200)
    responses_lib.add(responses_lib.GET, TEST_URL, body=b"<ok/>", status=200)

    response = make_request(
        TEST_URL, {"type": "XML"}, throttle=_throttle(), api_key="k",
        max_retries=1, backoff_base=3,
    )

    assert response.content == b"<ok/>"
    assert len(responses_lib.calls) == 2
    sleep.assert_called_once_with(3)


@responses_lib.activate
def test_make_request_maintenance_exhausts_retries_without_leaking_key(monkeypatch, caplog):
    attempts = []
    monkeypatch.setattr("core.http.time.sleep", lambda _: None)
    responses_lib.add(responses_lib.GET, TEST_URL, body=MAINTENANCE_HTML, status=200)

    with pytest.raises(RequestException, match="HTML instead of XML.*maintenance") as error:
        make_request(
            TEST_URL, {"type": "XML"}, throttle=_throttle(), api_key="private-test-key",
            max_retries=2, backoff_base=0,
            on_attempt=lambda: attempts.append(True),
        )

    assert len(responses_lib.calls) == len(attempts) == 3
    assert error.value.response.status_code == 200
    assert f"sha256={hashlib.sha256(MAINTENANCE_HTML).hexdigest()}" in str(error.value)
    assert "private-test-key" not in str(error.value) + caplog.text


@responses_lib.activate
def test_make_request_allows_html_when_requested():
    responses_lib.add(responses_lib.GET, TEST_URL, body=MAINTENANCE_HTML, status=200)
    response = make_request(
        TEST_URL, {"type": "HTML"}, throttle=_throttle(), api_key="k",
    )
    assert response.content == MAINTENANCE_HTML
    assert len(responses_lib.calls) == 1


@responses_lib.activate
def test_make_request_accepts_xml_with_html_content_type():
    responses_lib.add(
        responses_lib.GET, TEST_URL, body=b"<Law>no result</Law>", status=200,
        content_type="text/html",
    )
    response = make_request(
        TEST_URL, {"type": "XML"}, throttle=_throttle(), api_key="k",
    )
    assert response.content == b"<Law>no result</Law>"
    assert len(responses_lib.calls) == 1


@pytest.mark.parametrize("package,search_name,root_tag", [
    ("laws", "search_laws", "LawSearch"),
    ("precedents", "search_precedents", "PrecSearch"),
    ("admrules", "search_admrules", "AdmRulSearch"),
    ("ordinances", "search_ordinances", "OrdinSearch"),
])
@responses_lib.activate
def test_search_recovers_after_maintenance(package, search_name, root_tag, monkeypatch):
    api = importlib.import_module(f"{package}.api_client")
    monkeypatch.setattr(api, "_throttle", _throttle())
    monkeypatch.setattr("core.http.time.sleep", lambda _: None)
    responses_lib.add(responses_lib.GET, TEST_URL, body=MAINTENANCE_HTML, status=200)
    xml = f"<{root_tag}><totalCnt>0</totalCnt><page>1</page></{root_tag}>".encode()
    responses_lib.add(responses_lib.GET, TEST_URL, body=xml, status=200)

    assert getattr(api, search_name)()["totalCnt"] == 0
    assert len(responses_lib.calls) == 2


@pytest.mark.parametrize("package,detail_name", [
    ("laws", "get_law_detail"),
    ("precedents", "get_precedent_detail"),
    ("admrules", "get_admrule_detail"),
    ("ordinances", "get_ordinance_detail"),
])
@responses_lib.activate
def test_detail_maintenance_does_not_write_cache(package, detail_name, monkeypatch):
    api = importlib.import_module(f"{package}.api_client")
    monkeypatch.setattr(api, "_throttle", _throttle())
    monkeypatch.setattr("core.http.time.sleep", lambda _: None)
    monkeypatch.setattr(api.cache, "get_detail", lambda *args, **kwargs: None)
    put_detail = MagicMock()
    monkeypatch.setattr(api.cache, "put_detail", put_detail)
    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawService.do", body=MAINTENANCE_HTML, status=200,
    )

    with pytest.raises(RequestException, match="HTML instead of XML"):
        getattr(api, detail_name)("123456")

    assert len(responses_lib.calls) == api.MAX_RETRIES + 1
    put_detail.assert_not_called()
