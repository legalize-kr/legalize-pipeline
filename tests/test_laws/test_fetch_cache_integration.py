"""Integration test: fetch_cache rewrites poisoned empty history cache.

Simulates the scenario where a poisoned `[]` cache entry exists on disk, the
lsHistory response places exact-name matches on page 2 (what the original
pagination bug silently dropped), and verifies the end-to-end history-fetch
stage rewrites the cache and passes the post-fetch invariant.
"""

import sys
from pathlib import Path
from unittest.mock import call, patch

import pytest
import responses as responses_lib

import laws.api_client as api_client
import laws.cache as law_cache
import laws.detail_failure_allowlist as detail_failure_allowlist
import laws.fetch_cache as fetch_cache

LAW_API_BASE = "https://www.law.go.kr/DRF"


@pytest.fixture(autouse=True)
def patch_cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(law_cache, "CACHE_DIR", tmp_path / ".cache")


@pytest.fixture(autouse=True)
def patch_api_key(monkeypatch):
    monkeypatch.setattr(api_client, "LAW_API_KEY", "testkey")
    from core.throttle import Throttle
    monkeypatch.setattr(api_client, "_throttle", Throttle(delay_seconds=0))


@pytest.fixture(autouse=True)
def clear_detail_failure_allowlist_cache():
    detail_failure_allowlist.load_allowlist.cache_clear()
    yield
    detail_failure_allowlist.load_allowlist.cache_clear()


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


def test_history_name_file_adds_explicit_seed_after_limited_search(tmp_path: Path):
    seed_file = tmp_path / "history_seed_names.txt"
    seed_file.write_text(
        "\n".join([
            "# issue-specific backfill seeds",
            "",
            "폐지본법",
            "현행법",
        ]),
        encoding="utf-8",
    )
    laws = [
        {"법령명한글": "현행법"},
        {"법령명한글": "다른현행법"},
    ]

    names = fetch_cache._history_names_from_laws(
        laws,
        history_name_files=[seed_file],
        limit=1,
    )

    assert names == ["현행법", "폐지본법"]


def test_main_exits_when_skip_history_detail_fetch_has_errors(monkeypatch):
    import laws.history_allowlist as history_allowlist

    monkeypatch.setattr(sys, "argv", ["laws.fetch_cache", "--skip-history", "--workers", "1"])
    monkeypatch.setattr(history_allowlist, "load_allowlist", lambda: {})
    monkeypatch.setattr(
        fetch_cache,
        "fetch_all_msts",
        lambda: [{"법령일련번호": "1", "법령명한글": "실패법"}],
    )
    monkeypatch.setattr(
        fetch_cache,
        "_fetch_detail_task",
        lambda mst, name, counter: counter.inc("errors"),
    )

    with pytest.raises(SystemExit, match="law detail fetch failed: errors=1"):
        fetch_cache.main()


def test_fetch_detail_task_checks_active_allowlisted_failure_without_retries(
    tmp_path: Path,
    monkeypatch,
):
    allowlist_path = tmp_path / "known_detail_failures.yaml"
    allowlist_path.write_text(
        "\n".join([
            "entries:",
            '  - mst: "123"',
            '    law_name: "깨진법"',
            '    reason: "upstream_malformed_xml"',
            '    expected_error: "mismatched tag"',
            '    expires_on: "2099-01-01"',
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(detail_failure_allowlist, "_DEFAULT_PATH", allowlist_path)
    detail_failure_allowlist.load_allowlist.cache_clear()
    from core.counter import Counter

    counter = Counter()
    with patch.object(
        fetch_cache,
        "get_law_detail",
        side_effect=RuntimeError("mismatched tag: line 1"),
    ) as mock_get_law_detail:
        fetch_cache._fetch_detail_task("123", "", counter)

    mock_get_law_detail.assert_called_once_with("123", max_retries=0)
    assert counter.snapshot() == (0, 0, 0)
    assert counter.snapshot_all()["known_failures"] == 1


def test_fetch_detail_task_retries_normally_for_unexpected_allowlisted_error(
    tmp_path: Path,
    monkeypatch,
):
    allowlist_path = tmp_path / "known_detail_failures.yaml"
    allowlist_path.write_text(
        "\n".join([
            "entries:",
            '  - mst: "123"',
            '    law_name: "깨진법"',
            '    reason: "upstream_http_500"',
            '    expected_error: "500 Server Error"',
            '    expires_on: "2099-01-01"',
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(detail_failure_allowlist, "_DEFAULT_PATH", allowlist_path)
    detail_failure_allowlist.load_allowlist.cache_clear()

    from core.counter import Counter

    counter = Counter()
    with patch.object(
        fetch_cache,
        "get_law_detail",
        side_effect=[RuntimeError("connection reset"), None],
    ) as mock_get_law_detail:
        fetch_cache._fetch_detail_task("123", "", counter)

    assert mock_get_law_detail.call_args_list == [
        call("123", max_retries=0),
        call("123"),
    ]
    assert counter.snapshot() == (0, 1, 0)


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
