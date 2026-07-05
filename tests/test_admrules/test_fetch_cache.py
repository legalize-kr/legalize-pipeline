"""Tests for admrules/fetch_cache.py."""

import sys

import pytest

import admrules.detail_failure_allowlist as detail_failure_allowlist
from admrules import fetch_cache
from core.counter import Counter


def test_fetch_all_current_pages_until_total(monkeypatch):
    calls = []

    def fake_search_admrules(page, display, knd, org, date_range, history):
        calls.append((page, display, knd, org, date_range, history))
        return {
            "totalCnt": 101,
            "admrules": [{"행정규칙일련번호": str(page)}],
        }

    monkeypatch.setattr(fetch_cache, "search_admrules", fake_search_admrules)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    entries = fetch_cache.fetch_all_current(knd_values=["3"], org="1741000")
    assert entries == [{"행정규칙일련번호": "1"}, {"행정규칙일련번호": "2"}]
    assert calls == [(1, 100, "3", "1741000", "", True), (2, 100, "3", "1741000", "", True)]


def test_fetch_all_current_ignores_stale_page_checkpoint(monkeypatch):
    calls = []

    def fake_search_admrules(page, display, knd, org, date_range, history):
        assert history is True
        calls.append(page)
        return {"totalCnt": 1, "admrules": [{"행정규칙일련번호": "fresh"}]}

    monkeypatch.setattr(fetch_cache.checkpoint, "is_page_processed", lambda knd, page, org: True)
    monkeypatch.setattr(fetch_cache, "search_admrules", fake_search_admrules)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    assert fetch_cache.fetch_all_current(knd_values=["1"]) == [{"행정규칙일련번호": "fresh"}]
    assert calls == [1]


def test_fetch_all_current_filters_date_range(monkeypatch):
    def fake_search_admrules(page, display, knd, org, date_range, history):
        assert history is True
        return {
            "totalCnt": 1,
            "admrules": [
                {"행정규칙일련번호": "old", "발령일자": "20260430"},
                {"행정규칙일련번호": "new", "발령일자": "2026-05-01"},
            ],
        }

    monkeypatch.setattr(fetch_cache, "search_admrules", fake_search_admrules)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    assert fetch_cache.fetch_all_current(knd_values=["1"], date_range="20260501~20260511") == [
        {"행정규칙일련번호": "new", "발령일자": "2026-05-01"}
    ]


def test_fetch_details_deduplicates_and_limits(monkeypatch):
    fetched = []

    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda serial: None)
    monkeypatch.setattr(fetch_cache, "get_admrule_detail", lambda serial: fetched.append(serial))
    monkeypatch.setattr(fetch_cache.checkpoint, "mark_detail_processed", lambda serial: None)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    counter = fetch_cache.fetch_details(
        [
            {"행정규칙일련번호": "1"},
            {"행정규칙일련번호": "1"},
            {"행정규칙일련번호": "2"},
        ],
        workers=1,
        limit=1,
    )
    assert fetched == ["1"]
    assert counter.snapshot() == (0, 1, 0)


def test_fetch_detail_task_skips_allowlisted_upstream_failure(tmp_path, monkeypatch):
    allowlist_path = tmp_path / "known_detail_failures.yaml"
    allowlist_path.write_text(
        "\n".join([
            "entries:",
            '  - serial: "2100000000001"',
            '    reason: "upstream_http_500"',
            '    expected_error: "500 Server Error"',
            '    expires_on: "2099-01-01"',
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(detail_failure_allowlist, "_DEFAULT_PATH", allowlist_path)
    detail_failure_allowlist.load_allowlist.cache_clear()
    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda serial: None)
    monkeypatch.setattr(
        fetch_cache,
        "get_admrule_detail",
        lambda serial: (_ for _ in ()).throw(RuntimeError("500 Server Error")),
    )

    counter = Counter()
    fetch_cache._fetch_detail_task("2100000000001", counter)

    assert counter.snapshot() == (0, 0, 0)
    assert counter.snapshot_all()["known_failures"] == 1


def test_main_prunes_stale_cache_on_full_history_run(monkeypatch):
    pruned = []

    monkeypatch.setattr(sys, "argv", ["admrules.fetch_cache", "--skip-quota-check"])
    monkeypatch.setattr(fetch_cache, "fetch_all_current", lambda knd_values=None, org="", max_entries=None: [
        {"행정규칙일련번호": "keep"},
    ])
    monkeypatch.setattr(fetch_cache.cache, "prune_details", lambda serials: pruned.append(set(serials)) or ["stale"])
    monkeypatch.setattr(fetch_cache, "fetch_details", lambda entries, workers, limit: Counter())

    fetch_cache.main()

    assert pruned == [{"keep"}]


def test_main_does_not_prune_stale_cache_on_partial_run(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["admrules.fetch_cache", "--skip-quota-check", "--limit", "1"])
    monkeypatch.setattr(fetch_cache, "fetch_all_current", lambda knd_values=None, org="", max_entries=None: [
        {"행정규칙일련번호": "keep"},
    ])
    monkeypatch.setattr(
        fetch_cache.cache,
        "prune_details",
        lambda serials: (_ for _ in ()).throw(AssertionError("partial runs must not prune")),
    )
    monkeypatch.setattr(fetch_cache, "fetch_details", lambda entries, workers, limit: Counter())

    fetch_cache.main()


def test_main_exits_when_detail_fetch_has_errors(monkeypatch):
    counter = Counter()
    counter.inc("errors")

    monkeypatch.setattr(sys, "argv", ["admrules.fetch_cache", "--skip-quota-check"])
    monkeypatch.setattr(fetch_cache, "fetch_all_current", lambda knd_values=None, org="", max_entries=None: [])
    monkeypatch.setattr(fetch_cache, "fetch_details", lambda entries, workers, limit: counter)

    with pytest.raises(SystemExit, match="admrule detail fetch failed: errors=1"):
        fetch_cache.main()
