"""Tests for ordinances/fetch_cache.py."""

import sys

import pytest
import requests

from ordinances import fetch_cache
from core.counter import Counter


def test_fetch_all_current_pages_until_total(monkeypatch):
    calls = []

    def fake_search_ordinances(page, display, org, sborg, date_range, nw):
        calls.append((page, display, org, sborg, date_range, nw))
        return {"totalCnt": 101, "ordinances": [{"자치법규ID": str(page), "자치법규종류": "조례"}]}

    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    entries = fetch_cache.fetch_all_current(["조례"], org="6110000", display=100)
    assert entries == [{"자치법규ID": "1", "자치법규종류": "조례"}, {"자치법규ID": "2", "자치법규종류": "조례"}]
    assert calls == [(1, 100, "6110000", "", "", "1"), (2, 100, "6110000", "", "", "1")]


def test_fetch_all_current_can_request_history(monkeypatch):
    calls = []

    def fake_search_ordinances(page, display, org, sborg, date_range, nw):
        calls.append(nw)
        return {"totalCnt": 1, "ordinances": [{"자치법규ID": "1", "자치법규종류": "조례"}]}

    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    assert fetch_cache.fetch_all_current(["조례"], history=True) == [{"자치법규ID": "1", "자치법규종류": "조례"}]
    assert calls == ["2"]


def test_fetch_all_current_can_parallelize_full_history_pages(monkeypatch):
    calls = []

    def fake_search_ordinances(page, display, org, sborg, date_range, nw):
        calls.append(page)
        return {"totalCnt": 1001, "ordinances": [{"자치법규ID": str(page), "자치법규종류": "조례"}]}

    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    entries = fetch_cache.fetch_all_current(["조례"], display=500, history=True, list_workers=2)

    assert [entry["자치법규ID"] for entry in entries] == ["1", "2", "3"]
    assert sorted(calls) == [1, 2, 3]


def test_fetch_all_current_ignores_stale_page_checkpoint(monkeypatch):
    calls = []

    def fake_search_ordinances(page, display, org, sborg, date_range, nw):
        calls.append(page)
        return {"totalCnt": 1, "ordinances": [{"자치법규ID": "fresh", "자치법규종류": "조례"}]}

    monkeypatch.setattr(fetch_cache.checkpoint, "is_page_processed", lambda ordinance_type, page, org, sborg: True)
    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    assert fetch_cache.fetch_all_current(["조례"]) == [{"자치법규ID": "fresh", "자치법규종류": "조례"}]
    assert calls == [1]


def test_fetch_all_current_filters_date_range(monkeypatch):
    def fake_search_ordinances(page, display, org, sborg, date_range, nw):
        return {
            "totalCnt": 1,
            "ordinances": [
                {"자치법규ID": "old", "자치법규종류": "조례", "공포일자": "20260430"},
                {"자치법규ID": "new", "자치법규종류": "조례", "공포일자": "2026-05-01"},
            ],
        }

    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    assert fetch_cache.fetch_all_current(["조례"], date_range="20260501~20260511") == [
        {"자치법규ID": "new", "자치법규종류": "조례", "공포일자": "2026-05-01"}
    ]


def test_fetch_history_for_entries_filters_same_identity(monkeypatch):
    calls = []

    def fake_search_ordinances(query, page, display, nw):
        calls.append((query, page, nw))
        return {
            "totalCnt": 2,
            "ordinances": [
                {
                    "자치법규ID": "same",
                    "자치법규일련번호": "old",
                    "자치법규명": "이전 조례",
                    "자치법규종류": "조례",
                },
                {
                    "자치법규ID": "other",
                    "자치법규일련번호": "other",
                    "자치법규명": "다른 조례",
                    "자치법규종류": "조례",
                },
            ],
        }

    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    history = fetch_cache.fetch_history_for_entries(
        [{"자치법규ID": "same", "자치법규명": "현재 조례", "자치법규종류": "조례"}],
        ["조례"],
    )

    assert [entry["자치법규일련번호"] for entry in history] == ["old"]
    assert calls == [("현재 조례", 1, "2")]


def test_fetch_history_for_entries_removes_smart_quotes_from_search_query(monkeypatch):
    calls = []

    def fake_search_ordinances(query, page, display, nw):
        calls.append(query)
        return {
            "totalCnt": 1,
            "ordinances": [
                {
                    "자치법규ID": "same",
                    "자치법규일련번호": "old",
                    "자치법규명": "이전 조례",
                    "자치법규종류": "조례",
                }
            ],
        }

    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    history = fetch_cache.fetch_history_for_entries(
        [{"자치법규ID": "same", "자치법규명": "일본군‘위안부’ 지원 조례", "자치법규종류": "조례"}],
        ["조례"],
    )

    assert [entry["자치법규일련번호"] for entry in history] == ["old"]
    assert calls == ["일본군위안부 지원 조례"]


def test_fetch_details_deduplicates_and_limits(monkeypatch):
    fetched = []
    recorded = []

    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda cache_key, **kwargs: None)
    def fake_get_detail(ordinance_id, mst="", on_request_attempt=None):
        on_request_attempt()
        fetched.append((ordinance_id, mst))

    monkeypatch.setattr(fetch_cache, "get_ordinance_detail", fake_get_detail)
    monkeypatch.setattr(fetch_cache.checkpoint, "mark_detail_processed", lambda ordinance_id: None)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: recorded.append((count, corpus)))

    counter = fetch_cache.fetch_details(
        [
            {"자치법규ID": "1", "자치법규일련번호": "mst-1"},
            {"자치법규ID": "1", "자치법규일련번호": "mst-1"},
            {"자치법규ID": "2", "자치법규일련번호": "mst-2"},
        ],
        workers=1,
        limit=1,
    )
    assert fetched == [("1", "mst-1")]
    assert counter.snapshot() == (0, 1, 0)
    assert recorded == [(1, "ordinances")]


def test_fetch_details_records_detail_failures(monkeypatch):
    failures = []

    def raise_detail(ordinance_id, mst="", on_request_attempt=None):
        on_request_attempt()
        raise RuntimeError(f"boom {ordinance_id}")

    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda cache_key, **kwargs: None)
    monkeypatch.setattr(fetch_cache, "get_ordinance_detail", raise_detail)
    monkeypatch.setattr(fetch_cache, "append_failure", lambda row: failures.append(row))

    counter = fetch_cache.fetch_details([{"자치법규ID": "bad"}], workers=1)

    assert counter.snapshot() == (0, 0, 1)
    assert failures == [{"자치법규ID": "bad", "자치법규일련번호": "", "reason": "detail_fetch_failed"}]


def test_fetch_details_records_history_404_as_no_result(monkeypatch):
    recorded = []
    no_results = []

    def raise_404(ordinance_id, mst="", on_request_attempt=None):
        on_request_attempt()
        response = requests.Response()
        response.status_code = 404
        raise requests.HTTPError("not found", response=response)

    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda cache_key, **kwargs: None)
    monkeypatch.setattr(fetch_cache, "get_ordinance_detail", raise_404)
    monkeypatch.setattr(fetch_cache.cache, "add_no_result_serial", no_results.append)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: recorded.append((count, corpus)))

    counter = fetch_cache.fetch_details(
        [{"자치법규ID": "1", "자치법규일련번호": "missing-mst"}],
        workers=1,
    )

    assert counter.snapshot_all() == {"cached": 0, "fetched": 0, "errors": 0, "no_result": 1}
    assert no_results == ["missing-mst"]
    assert recorded == [(1, "ordinances")]


def test_fetch_details_accepts_allowlisted_http_error(monkeypatch):
    failures = []

    def raise_500(ordinance_id, mst="", on_request_attempt=None):
        on_request_attempt()
        response = requests.Response()
        response.status_code = 500
        raise requests.HTTPError("500 Server Error: Internal Server Error", response=response)

    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda cache_key, **kwargs: None)
    monkeypatch.setattr(fetch_cache, "get_ordinance_detail", raise_500)
    monkeypatch.setattr(fetch_cache, "append_failure", lambda row: failures.append(row))
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    counter = fetch_cache.fetch_details(
        [{"자치법규ID": "2050384", "자치법규일련번호": "899529"}],
        workers=1,
    )

    assert counter.snapshot_all() == {
        "cached": 0,
        "fetched": 0,
        "errors": 0,
        "known_failures": 1,
    }
    assert failures == []


def test_fetch_details_records_history_no_result_xml(monkeypatch):
    no_results = []

    def raise_no_result(ordinance_id, mst="", on_request_attempt=None):
        on_request_attempt()
        raise fetch_cache.NoResultError("no ordinance detail")

    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda cache_key, **kwargs: None)
    monkeypatch.setattr(fetch_cache, "get_ordinance_detail", raise_no_result)
    monkeypatch.setattr(fetch_cache.cache, "add_no_result_serial", no_results.append)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    counter = fetch_cache.fetch_details(
        [{"자치법규ID": "2201906", "자치법규일련번호": "1536019"}],
        workers=1,
    )

    assert counter.snapshot_all() == {"cached": 0, "fetched": 0, "errors": 0, "no_result": 1}
    assert no_results == ["1536019"]


def test_missing_detail_entries_checks_serial_history_cache(monkeypatch):
    calls = []

    def fake_get(cache_key, **kwargs):
        calls.append((cache_key, kwargs))
        return b"cached" if cache_key == "cached" else None

    monkeypatch.setattr(fetch_cache.cache, "get_detail", fake_get)
    monkeypatch.setattr(fetch_cache.cache, "load_no_result_serials", lambda: set())
    entries = [
        {"자치법규ID": "1", "자치법규일련번호": "cached"},
        {"자치법규ID": "2", "자치법규일련번호": "missing"},
    ]

    assert fetch_cache.missing_detail_entries(entries) == [entries[1]]
    assert calls == [
        ("cached", {"historical": True}),
        ("missing", {"historical": True}),
    ]


def test_missing_detail_entries_skips_negative_cache(monkeypatch):
    entries = [
        {"자치법규ID": "1", "자치법규일련번호": "gone"},
        {"자치법규ID": "2", "자치법규일련번호": "missing"},
    ]
    monkeypatch.setattr(fetch_cache.cache, "load_no_result_serials", lambda: {"gone"})
    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda cache_key, **kwargs: None)

    assert fetch_cache.missing_detail_entries(entries) == [entries[1]]


def test_main_exits_when_detail_fetch_has_errors(monkeypatch):
    counter = Counter()
    counter.inc("errors")

    monkeypatch.setattr(sys, "argv", ["ordinances.fetch_cache", "--skip-quota-check"])
    monkeypatch.setattr(
        fetch_cache,
        "fetch_all_current",
        lambda types, org="", sborg="", display=100, max_entries=None, history=False, list_workers=1: [],
    )
    monkeypatch.setattr(fetch_cache, "fetch_details", lambda entries, workers, limit: counter)

    with pytest.raises(SystemExit, match="ordinance detail fetch failed: errors=1"):
        fetch_cache.main()


def test_main_recovers_failed_details_after_batch(monkeypatch):
    entry = {"자치법규ID": "1", "자치법규일련번호": "mst-1"}
    failed = Counter()
    failed.inc("errors")
    recovered = Counter()
    recovered.inc("fetched")
    fetch_calls = []

    monkeypatch.setattr(sys, "argv", ["ordinances.fetch_cache", "--skip-quota-check"])
    monkeypatch.setattr(
        fetch_cache,
        "fetch_all_current",
        lambda types, org="", sborg="", display=100, max_entries=None, history=False, list_workers=1: [entry],
    )
    monkeypatch.setattr(fetch_cache, "missing_detail_entries", lambda entries: list(entries))

    def fake_fetch_details(entries, workers, limit):
        fetch_calls.append(list(entries))
        return failed if len(fetch_calls) == 1 else recovered

    monkeypatch.setattr(fetch_cache, "fetch_details", fake_fetch_details)

    fetch_cache.main()

    assert fetch_calls == [[entry], [entry]]


def test_main_exits_when_recovery_pass_still_has_errors(monkeypatch):
    entry = {"자치법규ID": "1", "자치법규일련번호": "mst-1"}
    failed = Counter()
    failed.inc("errors")
    fetch_calls = []

    monkeypatch.setattr(sys, "argv", ["ordinances.fetch_cache", "--skip-quota-check"])
    monkeypatch.setattr(
        fetch_cache,
        "fetch_all_current",
        lambda types, org="", sborg="", display=100, max_entries=None, history=False, list_workers=1: [entry],
    )
    monkeypatch.setattr(fetch_cache, "missing_detail_entries", lambda entries: list(entries))

    def fake_fetch_details(entries, workers, limit):
        fetch_calls.append(list(entries))
        return failed

    monkeypatch.setattr(fetch_cache, "fetch_details", fake_fetch_details)

    with pytest.raises(SystemExit, match="ordinance detail fetch failed: errors=1"):
        fetch_cache.main()

    assert fetch_calls == [[entry], [entry]]
