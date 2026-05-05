"""Tests for admrules/fetch_cache.py."""

from admrules import fetch_cache


def test_fetch_all_current_pages_until_total(monkeypatch):
    calls = []

    def fake_search_admrules(page, display, knd, org, date_range):
        calls.append((page, display, knd, org, date_range))
        return {
            "totalCnt": 101,
            "admrules": [{"행정규칙일련번호": str(page)}],
        }

    monkeypatch.setattr(fetch_cache, "search_admrules", fake_search_admrules)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    entries = fetch_cache.fetch_all_current(knd_values=["3"], org="1741000")
    assert entries == [{"행정규칙일련번호": "1"}, {"행정규칙일련번호": "2"}]
    assert calls == [(1, 100, "3", "1741000", ""), (2, 100, "3", "1741000", "")]


def test_fetch_all_current_ignores_stale_page_checkpoint(monkeypatch):
    calls = []

    def fake_search_admrules(page, display, knd, org, date_range):
        calls.append(page)
        return {"totalCnt": 1, "admrules": [{"행정규칙일련번호": "fresh"}]}

    monkeypatch.setattr(fetch_cache.checkpoint, "is_page_processed", lambda knd, page, org: True)
    monkeypatch.setattr(fetch_cache, "search_admrules", fake_search_admrules)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    assert fetch_cache.fetch_all_current(knd_values=["1"]) == [{"행정규칙일련번호": "fresh"}]
    assert calls == [1]


def test_fetch_all_current_filters_date_range(monkeypatch):
    def fake_search_admrules(page, display, knd, org, date_range):
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
