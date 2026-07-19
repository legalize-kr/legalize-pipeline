"""Thin wrapper around law.go.kr target=ordin endpoints."""

import logging
from collections.abc import Callable, Collection
from xml.etree import ElementTree

import requests

from core.http import make_request
from core.throttle import Throttle

from . import cache
from .config import (
    BACKOFF_BASE_SECONDS,
    DETAIL_REQUEST_TIMEOUT_SECONDS,
    LAW_API_BASE,
    LAW_API_KEY,
    MAX_RETRIES,
    REQUEST_DELAY_SECONDS,
    TYPE_CODES,
)

logger = logging.getLogger(__name__)

_throttle = Throttle(REQUEST_DELAY_SECONDS)


class NoResultError(RuntimeError):
    """Raised when the detail endpoint returns a deterministic no-result XML."""


def _request(
    url: str,
    params: dict,
    *,
    on_attempt: Callable[[], None] | None = None,
    timeout: float = 30,
    non_retry_statuses: Collection[int] = (),
) -> requests.Response:
    return make_request(
        url,
        params,
        throttle=_throttle,
        api_key=LAW_API_KEY,
        max_retries=MAX_RETRIES,
        backoff_base=BACKOFF_BASE_SECONDS,
        non_retry_statuses=non_retry_statuses,
        on_attempt=on_attempt,
        timeout=timeout,
    )


def _require_no_api_error(root: ElementTree.Element, context: str) -> None:
    result = root.findtext("result")
    if result and "실패" in result:
        raise RuntimeError(f"API error ({context}): {result} - {root.findtext('msg', '')}")


def _list_items(root: ElementTree.Element) -> list[ElementTree.Element]:
    items = root.findall(".//ordin")
    if items:
        return items
    return [item for item in root.iter() if item.findtext("자치법규ID") is not None]


def search_ordinances(
    *,
    query: str = "",
    page: int = 1,
    display: int = 100,
    org: str = "",
    sborg: str = "",
    ordinance_type: str = "",
    date_range: str = "",
    nw: str = "1",
) -> dict:
    """Search ordinance metadata via lawSearch.do target=ordin."""
    params = {
        "target": "ordin",
        "type": "XML",
        "page": str(page),
        "display": str(display),
        "nw": nw,
    }
    if query:
        params["query"] = query
    if org:
        params["org"] = org
    if sborg:
        params["sborg"] = sborg
    if ordinance_type:
        params["knd"] = TYPE_CODES.get(ordinance_type, ordinance_type)
    if date_range:
        params["prmlYd"] = date_range

    for attempt in range(MAX_RETRIES + 1):
        resp = _request(f"{LAW_API_BASE}/lawSearch.do", params)
        try:
            root = ElementTree.fromstring(resp.content)
            break
        except ElementTree.ParseError:
            if attempt == MAX_RETRIES:
                raise
            logger.warning(
                "Malformed ordinance search XML for page %s; retrying (%s/%s)",
                page,
                attempt + 1,
                MAX_RETRIES,
            )
    _require_no_api_error(root, f"ordin search page {page}")
    total = int(root.findtext("totalCnt", "0") or 0)
    page_num = int(root.findtext("page", str(page)) or page)
    items = []
    for item in _list_items(root):
        items.append({child.tag: child.text or "" for child in item})
    return {"totalCnt": total, "page": page_num, "ordinances": items, "raw_xml": resp.content}


def get_ordinance_detail(
    ordinance_id: str,
    *,
    mst: str = "",
    refresh: bool = False,
    on_request_attempt: Callable[[], None] | None = None,
) -> bytes:
    """Fetch and cache raw ordinance detail XML."""
    cache_key = str(mst or ordinance_id)
    historical = bool(mst)
    if not refresh:
        cached = cache.get_detail(cache_key, historical=historical)
        if cached:
            logger.debug("Cache hit: ordinance detail cache_key=%s", cache_key)
            return cached
    params = {"target": "ordin", "type": "XML"}
    if mst:
        params["MST"] = str(mst)
    else:
        params["ID"] = str(ordinance_id)
    resp = _request(
        f"{LAW_API_BASE}/lawService.do",
        params,
        on_attempt=on_request_attempt,
        timeout=DETAIL_REQUEST_TIMEOUT_SECONDS,
        non_retry_statuses={404},
    )
    root = ElementTree.fromstring(resp.content)
    _require_no_api_error(root, f"ordin detail ID={ordinance_id}")
    root_text = "".join(root.itertext())
    if root.tag == "Law" and "일치하는 자치법규가 없습니다" in root_text:
        raise NoResultError(f"no ordinance detail for ID={ordinance_id} MST={mst}")
    actual_id = (root.findtext(".//자치법규ID") or "").strip()
    actual_serial = (root.findtext(".//자치법규일련번호") or "").strip()
    if mst and actual_serial != str(mst):
        raise RuntimeError(
            f"ordin detail MST={mst} returned invalid 자치법규일련번호={actual_serial or '<missing>'}"
        )
    if not mst and actual_id != str(ordinance_id):
        raise RuntimeError(
            f"ordin detail ID={ordinance_id} returned invalid 자치법규ID={actual_id or '<missing>'}"
        )
    cache.put_detail(cache_key, resp.content, historical=historical)
    return resp.content
