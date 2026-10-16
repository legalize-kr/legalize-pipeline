"""Thin wrapper around law.go.kr OpenAPI."""

import logging
import re
import time
from datetime import date
from html import unescape
from xml.etree import ElementTree

import requests

from . import cache
from .config import (
    BACKOFF_BASE_SECONDS,
    LAW_API_BASE,
    LAW_API_KEY,
    MAX_RETRIES,
    REQUEST_DELAY_SECONDS,
)
from .history_allowlist import load_allowlist as load_empty_history_allowlist
from core.http import make_request
from core.throttle import Throttle

logger = logging.getLogger(__name__)

_throttle = Throttle(REQUEST_DELAY_SECONDS)
_EMPTY_HISTORY_RETRIES = min(MAX_RETRIES, 3)


def _raise_if_api_error(root: ElementTree.Element, context: str) -> None:
    result = root.findtext("result", "")
    if result and "실패" in result:
        message = root.findtext("msg", "")
        raise RuntimeError(f"API error for {context}: {result} - {message}")


def _raise_if_html_api_error(text: str, context: str) -> None:
    result_match = re.search(r"<result>\s*(.*?)\s*</result>", text, re.DOTALL)
    if not result_match:
        return
    result = unescape(re.sub(r"<[^>]+>", "", result_match.group(1)).strip())
    if "실패" not in result:
        return
    message_match = re.search(r"<msg>\s*(.*?)\s*</msg>", text, re.DOTALL)
    message = ""
    if message_match:
        message = unescape(re.sub(r"<[^>]+>", "", message_match.group(1)).strip())
    raise RuntimeError(f"API error for {context}: {result} - {message}")

# Restrict repair to references that contain CDATA and XML whitespace.
_REF_NAME = "조문참고자료"
_REF_CLOSE = "</조문참고자료>".encode("utf-8")
_XML_SPACE = b" \t\r\n"
_XML_TAG = re.compile(rb'''<(/?)([^\s<>/="'!?]+)((?:[^<>"']|"[^"]*"|'[^']*')*)>''')
_XML_ATTRIBUTE = re.compile(rb'''([^\s=]+)\s*=\s*(?:"[^"]*"|'[^']*')''')


def repair_law_xml(raw: bytes) -> bytes:
    """Close supported reference elements without other byte changes."""
    try:
        ElementTree.fromstring(raw)
        return raw
    except ElementTree.ParseError:
        pass
    except (LookupError, ValueError):
        return raw
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw

    # Each frame holds the name, element ordinal, and candidate eligibility.
    stack: list[tuple[str, int, bool]] = []
    insertions: list[int] = []
    repaired_ordinals: list[int] = []
    ordinal = 0
    position = 0
    while position < len(raw):
        if raw[position:position + 1] != b"<":
            end = raw.find(b"<", position)
            if end < 0:
                end = len(raw)
            if stack and raw[position:end].strip(_XML_SPACE):
                name, index, _ = stack[-1]
                stack[-1] = (name, index, False)
            position = end
            continue

        if raw.startswith(b"<![CDATA[", position):
            end = raw.find(b"]]>", position + 9)
            if end < 0:
                return raw
            position = end + 3
            continue
        if raw.startswith((b"<!--", b"<?"), position):
            comment = raw.startswith(b"<!--", position)
            terminator = b"-->" if comment else b"?>"
            end = raw.find(terminator, position + (4 if comment else 2))
            if end < 0:
                return raw
            token = raw[position:end + len(terminator)]
            if token.startswith(b"<?xml"):
                encoding = re.search(rb'''encoding\s*=\s*["']([^"']+)["']''', token)
                if encoding and encoding.group(1).lower() != b"utf-8":
                    return raw
            if stack:
                name, index, _ = stack[-1]
                stack[-1] = (name, index, False)
            position = end + len(terminator)
            continue
        if raw.startswith(b"<!", position):
            return raw

        match = _XML_TAG.match(raw, position)
        if match is None:
            return raw
        closing = bool(match.group(1))
        name = match.group(2).decode("utf-8")
        tail = match.group(3)
        token = match.group()
        self_closing = tail.endswith(b"/")
        if ":" in name:
            return raw
        if closing:
            if tail.strip(_XML_SPACE):
                return raw
        else:
            attributes = _XML_ATTRIBUTE.findall(tail)
            if any(key == b"xmlns" or b":" in key for key in attributes):
                return raw
            try:
                ElementTree.fromstring(token if self_closing else token[:-1] + b"/>")
            except ElementTree.ParseError:
                return raw

        if stack and stack[-1][2]:
            boundary = (
                closing and name == "조문단위"
                or not closing and not attributes and name in ("조문내용", _REF_NAME)
            )
            if boundary:
                _, index, _ = stack.pop()
                insertions.append(position)
                repaired_ordinals.append(index)

        if closing:
            if not stack or stack[-1][0] != name:
                return raw
            stack.pop()
        else:
            eligible = (
                name == _REF_NAME and not attributes
                and bool(stack) and stack[-1][0] == "조문단위"
            )
            if stack:
                parent, index, _ = stack[-1]
                stack[-1] = (parent, index, False)
            if not self_closing:
                stack.append((name, ordinal, eligible))
            ordinal += 1
        position = match.end()

    if stack or not insertions:
        return raw
    pieces: list[bytes] = []
    previous = 0
    for offset in insertions:
        pieces.extend((raw[previous:offset], _REF_CLOSE))
        previous = offset
    pieces.append(raw[previous:])
    repaired = b"".join(pieces)
    try:
        root = ElementTree.fromstring(repaired)
    except ElementTree.ParseError:
        return raw
    elements = list(root.iter())
    if len(elements) != ordinal:
        return raw
    if any(elements[index].tag != _REF_NAME or len(elements[index]) for index in repaired_ordinals):
        return raw
    return repaired


def _absolute_law_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("/"):
        return f"https://www.law.go.kr{value}"
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"https://www.law.go.kr/{value}"


def _attachments_from_xml(root: ElementTree.Element) -> list[dict]:
    attachments = []
    for node in root.findall(".//별표단위"):
        file_link = _absolute_law_url(
            node.findtext("별표서식파일링크", "") or node.findtext("별표파일링크", "")
        )
        pdf_link = _absolute_law_url(
            node.findtext("별표서식PDF파일링크", "") or node.findtext("별표PDF파일링크", "")
        )
        if not file_link and not pdf_link:
            continue
        attachment = {
            "별표번호": (node.findtext("별표번호", "") or "").strip(),
            "별표가지번호": (node.findtext("별표가지번호", "") or "").strip(),
            "별표구분": (node.findtext("별표구분", "") or "").strip() or "별표",
            "제목": (node.findtext("별표제목", "") or "").strip(),
        }
        if file_link:
            attachment["파일링크"] = file_link
        if pdf_link:
            attachment["PDF링크"] = pdf_link
        attachments.append(attachment)
    return attachments


def _request(
    url: str,
    params: dict,
    *,
    max_retries: int = MAX_RETRIES,
) -> requests.Response:
    """Make a throttled request with retry and exponential backoff."""
    return make_request(
        url, params,
        throttle=_throttle,
        api_key=LAW_API_KEY,
        max_retries=max_retries,
        backoff_base=BACKOFF_BASE_SECONDS,
    )


def search_laws(
    query: str = "",
    page: int = 1,
    display: int = 20,
    sort: str = "lasc",
    law_type: str = "",
    date_from: str = "",
    date_to: str = "",
) -> dict:
    """Search laws via the search API.

    Returns dict with keys: totalCnt, page, laws (list of law metadata dicts).
    """
    params = {
        "target": "law",
        "type": "XML",
        "query": query,
        "page": str(page),
        "display": str(display),
        "sort": sort,
    }
    if law_type:
        params["knd"] = law_type
    if date_from and date_to:
        params["ancYd"] = f"{date_from}~{date_to}"

    resp = _request(f"{LAW_API_BASE}/lawSearch.do", params)
    root = ElementTree.fromstring(resp.content)
    _raise_if_api_error(root, f"law search query={query!r}")

    total = root.findtext("totalCnt", "0")
    page_num = root.findtext("page", "1")

    laws = []
    for item in root.findall(".//law"):
        laws.append({
            "법령일련번호": item.findtext("법령일련번호", ""),
            "현행연혁코드": item.findtext("현행연혁코드", ""),
            "법령명한글": item.findtext("법령명한글", ""),
            "법령약칭명": item.findtext("법령약칭명", ""),
            "법령ID": item.findtext("법령ID", ""),
            "공포일자": item.findtext("공포일자", ""),
            "공포번호": item.findtext("공포번호", ""),
            "제개정구분명": item.findtext("제개정구분명", ""),
            "소관부처명": item.findtext("소관부처명", ""),
            "시행일자": item.findtext("시행일자", ""),
            "법령상세링크": item.findtext("법령상세링크", ""),
        })

    return {"totalCnt": int(total), "page": int(page_num), "laws": laws}


def _item_from_xml(node: ElementTree.Element) -> dict:
    return {
        "목번호": node.findtext("목번호", ""),
        "목가지번호": node.findtext("목가지번호", ""),
        "목내용": node.findtext("목내용", ""),
    }


def _subparagraphs_from_xml(paragraph: ElementTree.Element) -> list[dict]:
    """Parse both nested and sibling item layouts in document order."""
    subparagraphs = []
    current_subparagraph = None
    for node in paragraph.iter():
        if node.tag == "호":
            current_subparagraph = {
                "호번호": node.findtext("호번호", ""),
                "호가지번호": node.findtext("호가지번호", ""),
                "호내용": node.findtext("호내용", ""),
                "목": [],
            }
            subparagraphs.append(current_subparagraph)
        elif node.tag == "목" and current_subparagraph is not None:
            current_subparagraph["목"].append(_item_from_xml(node))
    return subparagraphs


def get_law_detail(
    mst_id: str | int,
    *,
    max_retries: int = MAX_RETRIES,
) -> dict:
    """Fetch full law text and metadata by MST ID.

    Return metadata, articles, addenda, attachments, and validated XML bytes.
    The raw_xml field may contain supported repairs. Cache files use these bytes.
    """
    params = {
        "target": "law",
        "MST": str(mst_id),
        "type": "XML",
    }

    cached = cache.get_detail(str(mst_id))
    if cached:
        logger.debug(f"Cache hit: detail MST={mst_id}")
        raw = cached
    else:
        resp = _request(
            f"{LAW_API_BASE}/lawService.do",
            params,
            max_retries=max_retries,
        )
        raw = resp.content

    reference_repaired = False
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as original_error:
        repaired = repair_law_xml(raw)
        if repaired == raw:
            raise
        try:
            root = ElementTree.fromstring(repaired)
        except ElementTree.ParseError:
            raise original_error from None
        raw = repaired
        reference_repaired = True

    _raise_if_api_error(root, f"MST {mst_id}")

    # Parse metadata
    metadata = {
        "법령명한글": root.findtext(".//법령명_한글", ""),
        "법령MST": str(mst_id),
        "법령ID": root.findtext(".//법령ID", ""),
        "법령구분": root.findtext(".//법종구분", ""),
        "법령구분코드": root.findtext(".//법종구분코드", ""),
        "소관부처명": root.findtext(".//소관부처명", ""),
        "소관부처코드": root.findtext(".//소관부처코드", ""),
        "공포일자": root.findtext(".//공포일자", ""),
        "공포번호": root.findtext(".//공포번호", ""),
        "시행일자": root.findtext(".//시행일자", ""),
        "제개정구분": root.findtext(".//제개정구분명", ""),
        "법령분야": root.findtext(".//법령분류명", ""),
    }

    # Parse articles (조문)
    articles = []
    for jo in root.findall(".//조문단위"):
        article = {
            "조문번호": jo.findtext("조문번호", ""),
            "조문가지번호": jo.findtext("조문가지번호", ""),
            "조문여부": jo.findtext("조문여부", ""),
            "조문제목": jo.findtext("조문제목", ""),
            "조문내용": jo.findtext("조문내용", ""),
        }
        # Parse 항 (paragraphs)
        paragraphs = []
        for hang in jo.findall(".//항"):
            para = {
                "항번호": hang.findtext("항번호", ""),
                "항가지번호": hang.findtext("항가지번호", ""),
                "항내용": hang.findtext("항내용", ""),
            }
            para["호"] = _subparagraphs_from_xml(hang)
            paragraphs.append(para)
        article["항"] = paragraphs
        articles.append(article)

    # Parse 부칙 (supplementary provisions)
    addenda = []
    for buchik in root.findall(".//부칙단위"):
        addenda.append({
            "부칙공포일자": buchik.findtext("부칙공포일자", ""),
            "부칙공포번호": buchik.findtext("부칙공포번호", ""),
            "부칙내용": buchik.findtext("부칙내용", ""),
        })

    attachments = _attachments_from_xml(root)
    # Publish validated parser input only after all extraction succeeds.
    if cached != raw:
        cache.put_detail(str(mst_id), raw)
    if reference_repaired:
        logger.warning("Repaired malformed XML for MST %s (unclosed 조문참고자료)", mst_id)

    return {
        "metadata": metadata,
        "articles": articles,
        "addenda": addenda,
        "attachments": attachments,
        "raw_xml": raw,
    }


def _parse_dot_date(raw: str) -> str:
    """Parse dot-separated date like '1958.2.22' into 'YYYYMMDD' format."""
    raw = raw.strip()
    if not raw:
        return ""
    parts = raw.split(".")
    if len(parts) == 3:
        return f"{parts[0]}{int(parts[1]):02d}{int(parts[2]):02d}"
    # Already compact or unexpected format
    return raw.replace(".", "")


def normalize_history_law_name(value: str) -> str:
    """Normalize equivalent law-name typography for matching and deduplication."""

    normalized = (value or "").translate(
        str.maketrans({"·": "ㆍ", "・": "ㆍ", "･": "ㆍ"})
    )
    return re.sub(r"\s+", "", normalized)


def _active_known_empty_history(law_name: str) -> dict | None:
    """Return an active known-empty allowlist entry for a law name, if any."""

    allowlist = load_empty_history_allowlist()
    stem = cache.history_path_for(law_name).stem
    entry = allowlist.get(stem) or allowlist.get(law_name)
    if entry is None or date.fromisoformat(entry["expires_on"]) <= date.today():
        return None
    return entry


def _merge_history_entries(cached: list[dict], fetched: list[dict]) -> list[dict]:
    """Merge append-only history by MST, preferring refreshed metadata."""
    by_mst = {
        entry["법령일련번호"]: entry
        for entry in cached
        if entry.get("법령일련번호")
    }
    for entry in fetched:
        mst = entry.get("법령일련번호")
        if mst:
            by_mst[mst] = entry
    return sorted(
        by_mst.values(),
        key=lambda entry: (entry.get("공포일자", ""), entry["법령일련번호"]),
    )


def _history_query_candidates(law_name: str) -> list[str]:
    """Return bounded fallback queries for upstream full-name search failures."""

    candidates = [law_name]
    canonical_dots = law_name.translate(str.maketrans({"·": "ㆍ", "・": "ㆍ", "･": "ㆍ"}))
    if canonical_dots != law_name:
        candidates.append(canonical_dots)

    if len(law_name) >= 40:
        tokens = re.split(r"[\s·ㆍ・･]+", law_name)
        longest = max((token for token in tokens if len(token) >= 4), key=len, default="")
        if longest:
            candidates.append(longest)
        candidates.append(law_name[-20:])

    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def _fetch_history_query(query: str, normalized_law_name: str) -> tuple[list[dict], set[str]]:
    """Fetch one lsHistory query and retain rows matching the target full name."""

    entries: list[dict] = []
    candidate_names: set[str] = set()
    page = 1
    while True:
        resp = _request(f"{LAW_API_BASE}/lawSearch.do", {
            "target": "lsHistory",
            "query": query,
            "type": "HTML",
            "display": "100",
            "page": str(page),
        })
        _raise_if_html_api_error(resp.text, f"law history query={query!r}")

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", resp.text, re.DOTALL)
        for row in rows:
            mst_match = re.search(r"MST=(\d+)", row)
            if not mst_match:
                continue
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if len(tds) < 8:
                continue
            clean = [unescape(re.sub(r"<[^>]+>", "", td)).strip() for td in tds]
            name = clean[1]
            candidate_names.add(name)
            if normalize_history_law_name(name) != normalized_law_name:
                continue
            entries.append({
                "법령일련번호": mst_match.group(1),
                "법령명한글": name,
                "제개정구분명": clean[3],
                "법령구분": clean[4],
                "공포번호": clean[5].replace("제 ", "").replace("호", "").strip(),
                "공포일자": _parse_dot_date(clean[6]),
                "시행일자": _parse_dot_date(clean[7]),
            })

        if len(rows) < 10:
            break
        page += 1

    return entries, candidate_names


def get_law_history(law_name: str, refresh: bool = False) -> list[dict]:
    """Fetch amendment history for a law via lsHistory HTML endpoint.

    Args:
        law_name: Law name (e.g., "민법"). History rows must match the full name
            after whitespace normalization.
        refresh: If True, bypass the local history cache and refetch from the API.
            Refreshed entries replace cached metadata for the same MST, while
            cached MSTs missing from a transient upstream response are retained.

    Returns list of dicts sorted oldest-first, each with:
    법령일련번호, 법령명한글, 제개정구분명, 법령구분, 공포번호, 공포일자, 시행일자
    """
    cached = cache.get_history(law_name)
    if not refresh:
        if cached:
            logger.debug(f"Cache hit: history law_name={law_name}")
            return cached
        if cached == []:
            logging.info("rewriting poisoned empty cache for %s", law_name)

    normalized_law_name = normalize_history_law_name(law_name)

    for attempt in range(1, _EMPTY_HISTORY_RETRIES + 1):
        all_entries: list[dict] = []
        candidate_names: set[str] = set()
        for query in _history_query_candidates(law_name):
            entries, names = _fetch_history_query(query, normalized_law_name)
            candidate_names.update(names)
            if entries:
                all_entries = entries
                if query != law_name:
                    logger.info("History fallback query recovered %s via %s", law_name, query)
                break

        if all_entries or attempt == _EMPTY_HISTORY_RETRIES:
            break

        known_empty = _active_known_empty_history(law_name)
        if known_empty is not None:
            logger.warning(
                "Known empty history response for %s; reason=%s expires_on=%s; not retrying",
                law_name,
                known_empty["reason"],
                known_empty["expires_on"],
            )
            break

        if candidate_names:
            candidates = sorted(candidate_names)
            logger.warning(
                "History response for %s had no exact name match; "
                "candidate_count=%s candidate_sample=%s; not retrying",
                law_name,
                len(candidates),
                candidates[:5],
            )
            break

        delay = BACKOFF_BASE_SECONDS * attempt
        logger.warning(
            "Empty history response for %s; attempt %s/%s completed; retrying in %.1fs",
            law_name,
            attempt,
            _EMPTY_HISTORY_RETRIES,
            delay,
        )
        time.sleep(delay)

    cached_entries = cached or []
    fetched_msts = {entry["법령일련번호"] for entry in all_entries}
    preserved_msts = {
        entry["법령일련번호"]
        for entry in cached_entries
        if entry.get("법령일련번호")
        and entry["법령일련번호"] not in fetched_msts
    }
    all_entries = _merge_history_entries(cached_entries, all_entries)
    if refresh and preserved_msts:
        logger.warning(
            "History refresh for %s omitted %s cached MSTs; preserving sample=%s",
            law_name,
            len(preserved_msts),
            sorted(preserved_msts)[:5],
        )
    cache.put_history(law_name, all_entries)
    return all_entries
