"""Regression tests for lsHistory pagination continuation.

Before the fix, `get_law_history` aborted pagination when a page had zero
exact-name matches, silently losing all matches on later pages. These tests
ensure pagination continues until the page is under-full (len(rows) < 10).
"""

from pathlib import Path

import pytest
import responses as responses_lib

import laws.api_client as api_client
import laws.cache as law_cache

LAW_API_BASE = "http://www.law.go.kr/DRF"


@pytest.fixture(autouse=True)
def patch_cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(law_cache, "CACHE_DIR", tmp_path / ".cache")


@pytest.fixture(autouse=True)
def patch_api_key(monkeypatch):
    monkeypatch.setattr(api_client, "LAW_API_KEY", "testkey")
    from core.throttle import Throttle
    monkeypatch.setattr(api_client, "_throttle", Throttle(delay_seconds=0))


def _row(mst: str, name: str, prom_date: str = "2020.1.1", enf_date: str = "2020.1.1") -> str:
    return (
        f"<tr>"
        f"<td>1</td>"
        f'<td><a href="/lsInfoP.do?MST={mst}">{name}</a></td>'
        f"<td>법무부</td>"
        f"<td>일부개정</td>"
        f"<td>법률</td>"
        f"<td>제 1호</td>"
        f"<td>{prom_date}</td>"
        f"<td>{enf_date}</td>"
        f"<td></td>"
        f"</tr>"
    )


def _page(rows: list[str]) -> str:
    return (
        "<html><body><table>"
        + "".join(rows)
        + "</table></body></html>"
    )


@responses_lib.activate
def test_search_returns_only_non_matching_rows_on_page_1_matching_rows_on_page_2_returns_all_exact_name_matches():
    # Page 1: 10 variant rows, zero exact matches for "주택법"
    page1_variants = [
        "공영주택법", "민간임대주택법", "장기공공임대주택특별법",
        "주택임대차보호법", "주택저당채권유동화회사법", "주택도시기금법",
        "주택건설촉진법", "공공주택특별법", "임대주택법", "국민임대주택법",
    ]
    page1 = _page([_row(str(1000 + i), name) for i, name in enumerate(page1_variants)])

    # Page 2: 10 rows, 3 exact matches for "주택법", 7 variants
    page2_names = [
        "주택법", "주택법", "주택법",
        "도시형주택법", "준주택법", "미니주택법", "신주택법",
        "복합주택법", "임시주택법", "특수주택법",
    ]
    page2 = _page([_row(str(2000 + i), name) for i, name in enumerate(page2_names)])

    # Page 3: 3 rows -> signals exhaustion via len(rows) < 10
    page3 = _page([_row(str(3000 + i), "주택법임대법") for i in range(3)])

    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body=page1, status=200, content_type="text/html; charset=utf-8",
    )
    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body=page2, status=200, content_type="text/html; charset=utf-8",
    )
    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body=page3, status=200, content_type="text/html; charset=utf-8",
    )

    result = api_client.get_law_history("주택법")

    # Should return the 3 exact matches from page 2
    assert len(result) == 3
    assert all(entry["법령명한글"] == "주택법" for entry in result)
    msts = sorted(entry["법령일련번호"] for entry in result)
    assert msts == ["2000", "2001", "2002"]


@responses_lib.activate
def test_pagination_stops_when_page_underfull():
    """A page with fewer than 10 rows signals the final page — loop exits."""
    # Single page with 2 exact matches and under-full row count
    rows = [_row("500", "주택법"), _row("501", "주택법")]
    html = _page(rows)
    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body=html, status=200, content_type="text/html; charset=utf-8",
    )

    result = api_client.get_law_history("주택법")

    assert len(result) == 2
    assert len(responses_lib.calls) == 1
