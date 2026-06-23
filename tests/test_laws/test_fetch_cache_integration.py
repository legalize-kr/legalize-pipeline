"""Integration test: fetch_cache rewrites poisoned empty history cache.

Simulates the scenario where a poisoned `[]` cache entry exists on disk, the
lsHistory response places exact-name matches on page 2 (what the original
pagination bug silently dropped), and verifies the end-to-end history-fetch
stage rewrites the cache and passes the post-fetch invariant.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
import responses as responses_lib

import laws.api_client as api_client
import laws.cache as law_cache
import laws.fetch_cache as fetch_cache

LAW_API_BASE = "http://www.law.go.kr/DRF"


@pytest.fixture(autouse=True)
def patch_cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(law_cache, "CACHE_DIR", tmp_path / ".cache")


@pytest.fixture(autouse=True)
def patch_api_key(monkeypatch):
    monkeypatch.setattr(api_client, "LAW_API_KEY", "testkey")
    from core.throttle import Throttle
    monkeypatch.setattr(api_client, "_throttle", Throttle(delay_seconds=0))


def _row(mst: str, name: str) -> str:
    return (
        f"<tr>"
        f"<td>1</td>"
        f'<td><a href="/lsInfoP.do?MST={mst}">{name}</a></td>'
        f"<td>법무부</td>"
        f"<td>일부개정</td>"
        f"<td>법률</td>"
        f"<td>제 1호</td>"
        f"<td>2020.1.1</td>"
        f"<td>2020.1.1</td>"
        f"<td></td>"
        f"</tr>"
    )


def _page(rows: list[str]) -> str:
    return "<html><body><table>" + "".join(rows) + "</table></body></html>"


def test_history_name_file_adds_seed_not_in_current_search_list(tmp_path: Path):
    seed_file = tmp_path / "history_seed_names.txt"
    seed_file.write_text(
        "# 폐지 법령 seed\n"
        "\n"
        "국립사범대학 졸업자 중 교원미임용자 임용 등에 관한 특별법\n"
        "주택법\n",
        encoding="utf-8",
    )

    seed_names = fetch_cache._load_history_seed_names(seed_file)
    unique_names = fetch_cache._extend_unique_names(["주택법"], seed_names)

    assert unique_names == [
        "주택법",
        "국립사범대학 졸업자 중 교원미임용자 임용 등에 관한 특별법",
    ]


@responses_lib.activate
def test_fetch_cache_history_phase_rewrites_poisoned_cache():
    # Seed poisoned empty cache for 주택법
    law_cache.put_history("주택법", [])

    # Page 1: 10 variant rows (zero exact matches) — previous bug path
    page1 = _page([
        _row(str(1000 + i), f"변형주택법{i}") for i in range(10)
    ])
    # Page 2: 2 exact matches + 1 variant = 3 rows (under-full -> stop)
    page2 = _page([
        _row("2000", "주택법"),
        _row("2001", "주택법"),
        _row("2002", "기타주택법"),
    ])

    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body=page1, status=200, content_type="text/html; charset=utf-8",
    )
    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body=page2, status=200, content_type="text/html; charset=utf-8",
    )

    # Drive the history-fetch task directly (matches main()'s inner loop)
    import threading
    from core.counter import Counter

    counter = Counter()
    all_msts: list[str] = []
    lock = threading.Lock()
    fetch_cache._fetch_history_task("주택법", counter, all_msts, lock)

    # Cache now non-empty and contains an exact match
    fresh = law_cache.get_history("주택법")
    assert fresh, "Cache must be non-empty after re-fetch"
    assert any(e["법령명한글"] == "주택법" for e in fresh)

    # Raw JSON on disk is non-empty
    cache_path = law_cache._history_path("주택법")
    raw = cache_path.read_text(encoding="utf-8")
    assert raw.strip() != "[]"

    # Invariant helper does not raise
    fetch_cache._assert_no_empty_history_cache()
