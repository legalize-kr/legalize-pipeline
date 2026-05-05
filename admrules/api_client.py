"""Thin wrapper around law.go.kr OpenAPI for administrative rules."""

import logging
from xml.etree import ElementTree

import requests

from core.http import make_request
from core.throttle import Throttle

from . import cache
from .config import (
    BACKOFF_BASE_SECONDS,
    LAW_API_BASE,
    LAW_API_KEY,
    MAX_RETRIES,
    REQUEST_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)

_throttle = Throttle(REQUEST_DELAY_SECONDS)


def _request(url: str, params: dict) -> requests.Response:
    return make_request(
        url,
        params,
        throttle=_throttle,
        api_key=LAW_API_KEY,
        max_retries=MAX_RETRIES,
        backoff_base=BACKOFF_BASE_SECONDS,
    )


def _require_no_api_error(root: ElementTree.Element, context: str) -> None:
    result = root.findtext("result")
    if result and "실패" in result:
        raise RuntimeError(f"API error ({context}): {result} - {root.findtext('msg', '')}")


def search_admrules(
    query: str = "",
    page: int = 1,
    display: int = 100,
    sort: str = "lasc",
    knd: str = "",
    org: str = "",
    date_range: str = "",
    history: bool = False,
) -> dict:
    """Search administrative rules via ``target=admrul``.

    Returns ``{"totalCnt": int, "page": int, "admrules": list[dict]}``.
    """
    params = {
        "target": "admrul",
        "type": "XML",
        "query": query,
        "page": str(page),
        "display": str(display),
        "sort": sort,
        "nw": "2" if history else "1",
    }
    if knd:
        params["knd"] = str(knd)
    if org:
        params["org"] = str(org)
    if date_range:
        params["prmlYd"] = date_range

    resp = _request(f"{LAW_API_BASE}/lawSearch.do", params)
    root = ElementTree.fromstring(resp.content)
    _require_no_api_error(root, f"admrul search page {page}")

    admrules = []
    for item in root.findall(".//admrul"):
        admrules.append({
            "행정규칙일련번호": item.findtext("행정규칙일련번호", ""),
            "행정규칙명": item.findtext("행정규칙명", ""),
            "행정규칙종류": item.findtext("행정규칙종류", ""),
            "발령일자": item.findtext("발령일자", ""),
            "발령번호": item.findtext("발령번호", ""),
            "소관부처명": item.findtext("소관부처명", ""),
            "현행연혁구분": item.findtext("현행연혁구분", ""),
            "제개정구분코드": item.findtext("제개정구분코드", ""),
            "제개정구분명": item.findtext("제개정구분명", ""),
            "행정규칙ID": item.findtext("행정규칙ID", ""),
            "행정규칙상세링크": item.findtext("행정규칙상세링크", ""),
            "시행일자": item.findtext("시행일자", ""),
            "생성일자": item.findtext("생성일자", ""),
        })

    return {
        "totalCnt": int(root.findtext("totalCnt", "0")),
        "page": int(root.findtext("page", "1")),
        "admrules": admrules,
    }


def get_admrule_detail(serial_no: str | int) -> bytes:
    """Fetch raw administrative rule detail XML by 행정규칙일련번호."""
    serial_no = str(serial_no)
    cached = cache.get_detail(serial_no)
    if cached:
        logger.debug("Cache hit: admrule detail serial_no=%s", serial_no)
        return cached

    resp = _request(f"{LAW_API_BASE}/lawService.do", {
        "target": "admrul",
        "ID": serial_no,
        "type": "XML",
    })
    raw = resp.content
    root = ElementTree.fromstring(raw)
    _require_no_api_error(root, f"admrul detail ID={serial_no}")
    cache.put_detail(serial_no, raw)
    return raw


def search_old_and_new(
    query: str = "",
    page: int = 1,
    display: int = 100,
    knd: str = "",
) -> dict:
    """Search the admrulOldAndNew supplementary endpoint."""
    params = {
        "target": "admrulOldAndNew",
        "type": "XML",
        "query": query,
        "page": str(page),
        "display": str(display),
    }
    if knd:
        params["knd"] = str(knd)

    resp = _request(f"{LAW_API_BASE}/lawSearch.do", params)
    root = ElementTree.fromstring(resp.content)
    _require_no_api_error(root, f"admrulOldAndNew search page {page}")
    return {
        "totalCnt": int(root.findtext("totalCnt", "0")),
        "page": int(root.findtext("page", "1")),
        "items": [
            {child.tag: (child.text or "") for child in item}
            for item in root.findall(".//admrulOldAndNew")
        ],
    }
