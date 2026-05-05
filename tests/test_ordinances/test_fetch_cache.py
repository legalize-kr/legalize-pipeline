"""Tests for ordinances/fetch_cache.py."""

from ordinances import fetch_cache


def test_fetch_all_current_pages_until_total(monkeypatch):
    calls = []

    def fake_search_ordinances(page, display, org, sborg, date_range):
        calls.append((page, display, org, sborg, date_range))
        return {"totalCnt": 101, "ordinances": [{"자치법규ID": str(page), "자치법규종류": "조례"}]}

    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    entries = fetch_cache.fetch_all_current(["조례"], org="6110000", display=100)
    assert entries == [{"자치법규ID": "1", "자치법규종류": "조례"}, {"자치법규ID": "2", "자치법규종류": "조례"}]
    assert calls == [(1, 100, "6110000", "", ""), (2, 100, "6110000", "", "")]


def test_fetch_all_current_ignores_stale_page_checkpoint(monkeypatch):
    calls = []

    def fake_search_ordinances(page, display, org, sborg, date_range):
        calls.append(page)
        return {"totalCnt": 1, "ordinances": [{"자치법규ID": "fresh", "자치법규종류": "조례"}]}

    monkeypatch.setattr(fetch_cache.checkpoint, "is_page_processed", lambda ordinance_type, page, org, sborg: True)
    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    assert fetch_cache.fetch_all_current(["조례"]) == [{"자치법규ID": "fresh", "자치법규종류": "조례"}]
    assert calls == [1]


def test_fetch_all_current_filters_date_range(monkeypatch):
    def fake_search_ordinances(page, display, org, sborg, date_range):
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


def test_fetch_details_deduplicates_and_limits(monkeypatch):
    fetched = []

    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda ordinance_id: None)
    monkeypatch.setattr(fetch_cache, "get_ordinance_detail", lambda ordinance_id: fetched.append(ordinance_id))
    monkeypatch.setattr(fetch_cache.checkpoint, "mark_detail_processed", lambda ordinance_id: None)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    counter = fetch_cache.fetch_details(
        [{"자치법규ID": "1"}, {"자치법규ID": "1"}, {"자치법규ID": "2"}],
        workers=1,
        limit=1,
    )
    assert fetched == ["1"]
    assert counter.snapshot() == (0, 1, 0)


def test_fetch_details_records_detail_failures(monkeypatch):
    failures = []

    def raise_detail(ordinance_id):
        raise RuntimeError(f"boom {ordinance_id}")

    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda ordinance_id: None)
    monkeypatch.setattr(fetch_cache, "get_ordinance_detail", raise_detail)
    monkeypatch.setattr(fetch_cache, "append_failure", lambda row: failures.append(row))

    counter = fetch_cache.fetch_details([{"자치법규ID": "bad"}], workers=1)

    assert counter.snapshot() == (0, 0, 1)
    assert failures == [{"자치법규ID": "bad", "reason": "detail_fetch_failed"}]
