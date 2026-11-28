"""Tests for admrules/fetch_cache.py."""

import hashlib
import json
import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import admrules.detail_failure_allowlist as detail_failure_allowlist
from admrules import fetch_cache
from core.counter import Counter


@pytest.fixture
def verified_no_result(tmp_path, monkeypatch, fixtures_dir):
    from admrules import api_client

    class ProbeDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 3)

    monkeypatch.setattr(detail_failure_allowlist, "date", ProbeDate)
    detail_failure_allowlist.load_allowlist.cache_clear()
    monkeypatch.setattr(fetch_cache.cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(fetch_cache.checkpoint, "CHECKPOINT_FILE", tmp_path / "checkpoint.json")
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    evidence = json.loads((fixtures_dir / "admrule_no_result_2100000287624.json").read_text(encoding="utf-8"))
    raw = (fixtures_dir / evidence["detail"]["fixture"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == evidence["detail"]["sha256"]
    request = Mock(return_value=SimpleNamespace(content=raw))
    monkeypatch.setattr(api_client, "_request", request)
    yield request
    detail_failure_allowlist.load_allowlist.cache_clear()


def test_verified_no_result_retries_without_caching_and_recovers(verified_no_result):
    serial = "2100000287624"
    counter = Counter()
    fetch_cache._fetch_detail_task(serial, counter)
    fetch_cache._fetch_detail_task(serial, counter)

    assert counter.snapshot_all() == {"cached": 0, "fetched": 0, "errors": 0, "known_failures": 2}
    assert verified_no_result.call_count == 2
    assert fetch_cache.cache.get_detail(serial) is None
    assert fetch_cache.checkpoint.get_processed_serials() == set()

    recovered = f"<AdmRulService><행정규칙일련번호>{serial}</행정규칙일련번호></AdmRulService>".encode()
    verified_no_result.return_value = SimpleNamespace(content=recovered)
    fetch_cache._fetch_detail_task(serial, counter)

    assert counter.snapshot() == (0, 1, 0)
    assert fetch_cache.cache.get_detail(serial) == recovered
    assert fetch_cache.checkpoint.get_processed_serials() == {serial}


def test_unverified_no_result_remains_an_error(verified_no_result):
    counter = Counter()
    fetch_cache._fetch_detail_task("2100000287625", counter)

    assert counter.snapshot() == (0, 0, 1)
    assert fetch_cache.checkpoint.get_processed_serials() == set()


@pytest.mark.parametrize("listed_current", [False, True])
@pytest.mark.parametrize("entrypoint", ["fetch", "update"])
def test_verified_no_result_preserves_current_selection(verified_no_result, tmp_path, monkeypatch, listed_current, entrypoint):
    from admrules import snapshot, update

    current = {"행정규칙일련번호": "1", "행정규칙ID": "1", "현행연혁구분": "현행"}
    raw = (
        "<AdmRulService><행정규칙일련번호>1</행정규칙일련번호><행정규칙ID>1</행정규칙ID>"
        "<행정규칙명>기존 규칙</행정규칙명><행정규칙종류>훈령</행정규칙종류>"
        "<소관부처명>행정안전부</소관부처명><발령일자>20261101</발령일자>"
        "<현행여부>Y</현행여부><조문내용>제1조 기존 본문</조문내용></AdmRulService>"
    ).encode()
    unavailable_response = verified_no_result.return_value
    verified_no_result.side_effect = lambda url, params: SimpleNamespace(content=raw) if params["ID"] == "1" else unavailable_response
    fetch_cache.cache.put_detail("1", raw)
    snapshot.write_current_snapshot([current], history_entries=[current])
    path = fetch_cache.cache.CACHE_DIR / snapshot.SNAPSHOT_NAME
    before = path.read_bytes()
    unavailable = {"행정규칙일련번호": "2100000287624", "행정규칙ID": "2",
                   "현행연혁구분": "현행" if listed_current else "연혁"}
    rows = [current, unavailable]
    monkeypatch.setattr(sys, "argv", ["admrules.fetch_cache", "--skip-quota-check"])
    module = fetch_cache if entrypoint == "fetch" else update
    monkeypatch.setattr(module, "fetch_all_current", lambda **kwargs: rows if kwargs.get("history", True) or listed_current else [current])
    run = fetch_cache.main if entrypoint == "fetch" else lambda: update.run(repo=tmp_path / "output")
    prune = Mock(wraps=fetch_cache.prune_stale_cache)
    monkeypatch.setattr(fetch_cache, "prune_stale_cache", prune)

    if listed_current:
        with pytest.raises(RuntimeError, match="Missing current admrule detail"):
            run()
        assert path.read_bytes() == before
        prune.assert_not_called()
    else:
        stats = run()
        if entrypoint == "update":
            assert stats["fetch_errors"] == stats["errors"] == 0
            assert stats["skipped"] == 1
        assert snapshot.load_current_snapshot()["rules"] == {"1": "1"}
        assert prune.call_count == (1 if entrypoint == "fetch" else 0)
    assert fetch_cache.cache.get_detail("1") == raw
    assert fetch_cache.cache.get_detail("2100000287624") is None


def test_fetch_all_current_pages_until_total(monkeypatch):
    calls = []

    def fake_search_admrules(page, display, knd, org, date_range, history):
        calls.append((page, display, knd, org, date_range, history))
        return {
            "totalCnt": 101,
            "admrules": [{"행정규칙일련번호": str(i)} for i in range((page - 1) * 100, min(page * 100, 101))],
        }

    monkeypatch.setattr(fetch_cache, "search_admrules", fake_search_admrules)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    entries = fetch_cache.fetch_all_current(knd_values=["3"], org="1741000")
    assert entries == [{"행정규칙일련번호": str(i)} for i in range(101)]
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
            "totalCnt": 2,
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


def test_main_prunes_stale_cache_on_full_history_run(monkeypatch, tmp_path):
    from admrules import snapshot

    selection = Mock()
    monkeypatch.setattr(snapshot, "write_current_snapshot", selection)
    recovered = Mock()
    monkeypatch.setattr(fetch_cache, "recover_published_details", recovered)
    pruned = []

    monkeypatch.setattr(sys, "argv", ["admrules.fetch_cache", "--skip-quota-check", "--published-repo", str(tmp_path)])
    monkeypatch.setattr(fetch_cache, "fetch_all_current", lambda **kwargs: [
        {"행정규칙일련번호": "keep"},
    ])
    monkeypatch.setattr(fetch_cache.cache, "prune_details", lambda serials: pruned.append(set(serials)) or ["stale"])
    monkeypatch.setattr(fetch_cache, "fetch_details", lambda entries, workers, limit, **kwargs: Counter())

    fetch_cache.main()

    assert selection.call_args.kwargs["repo"] == tmp_path
    recovered.assert_called_once_with(tmp_path, [{"행정규칙일련번호": "keep"}] * 2)
    assert pruned == [{"keep"}]


def test_unreadable_published_history_stops_full_recovery(tmp_path):
    with pytest.raises(ValueError, match="Expected a published"):
        fetch_cache.recover_published_details(tmp_path, [])


def test_full_fetch_recovers_unlisted_published_xml_before_archiving(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(fetch_cache.cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(fetch_cache, "committed_serials", lambda repo: {"1", "2", "3", "4"})
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    fetch_cache.cache.put_detail("2", b"previously cached")
    calls = []

    def fetch(serial, *, refresh):
        calls.append(serial)
        assert refresh
        if serial == "4":
            raise fetch_cache.NoResultError()
        fetch_cache.cache.put_detail(serial, b"recovered")

    monkeypatch.setattr(fetch_cache, "get_admrule_detail", fetch)
    rows = [{"행정규칙일련번호": "1"}]
    fetch_cache.recover_published_details(tmp_path, rows)
    assert calls == ["3", "4"]
    assert "Published admrule 4 has no source detail" in caplog.text
    assert set(fetch_cache.prune_stale_cache(rows)) == {"2", "3"}
    assert (tmp_path / "retired/3.xml").read_bytes() == b"recovered"


def test_main_does_not_prune_stale_cache_on_partial_run(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["admrules.fetch_cache", "--skip-quota-check", "--limit", "1"])
    monkeypatch.setattr(fetch_cache, "fetch_all_current", lambda **kwargs: [
        {"행정규칙일련번호": "keep"},
    ])
    monkeypatch.setattr(
        fetch_cache.cache,
        "prune_details",
        lambda serials: (_ for _ in ()).throw(AssertionError("partial runs must not prune")),
    )
    monkeypatch.setattr(fetch_cache, "fetch_details", lambda entries, workers, limit, **kwargs: Counter())

    fetch_cache.main()


def test_main_exits_when_detail_fetch_has_errors(monkeypatch):
    counter = Counter()
    counter.inc("errors")

    monkeypatch.setattr(sys, "argv", ["admrules.fetch_cache", "--skip-quota-check"])
    monkeypatch.setattr(fetch_cache, "fetch_all_current", lambda **kwargs: [{"행정규칙일련번호": "1"}])
    monkeypatch.setattr(fetch_cache, "fetch_details", lambda entries, workers, limit, **kwargs: counter)

    with pytest.raises(SystemExit, match="admrule detail fetch failed: errors=1"):
        fetch_cache.main()


def test_default_fetch_has_no_kind_filter_and_keeps_nonstandard_types(monkeypatch):
    calls = []
    def search(**kwargs):
        calls.append(kwargs)
        return {"totalCnt": 1, "admrules": [{"행정규칙일련번호": "123", "행정규칙종류": "세칙"}]}
    monkeypatch.setattr(fetch_cache, "search_admrules", search)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    assert fetch_cache.fetch_all_current()[0]["행정규칙종류"] == "세칙"
    assert len(calls) == 1 and calls[0]["knd"] == "" and calls[0]["history"] is True


@pytest.mark.parametrize("responses", [
    [{"totalCnt": 100, "admrules": []}],
    [{"totalCnt": 2, "admrules": [{"행정규칙일련번호": "1"}] * 2}],
    [{"totalCnt": 1, "admrules": [{}]}],
    [{"totalCnt": 101, "admrules": [{"행정규칙일련번호": str(i)} for i in range(100)]},
     {"totalCnt": 100, "admrules": []}],
])
def test_incomplete_list_fails_before_pruning(monkeypatch, responses):
    responses = iter(responses)
    monkeypatch.setattr(fetch_cache, "search_admrules", lambda **kwargs: next(responses))
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError):
        fetch_cache.fetch_all_current()


def test_failed_details_never_prune_or_publish_snapshot(monkeypatch):
    from admrules import snapshot
    monkeypatch.setattr(sys, "argv", ["admrules.fetch_cache", "--skip-quota-check"])
    monkeypatch.setattr(fetch_cache, "fetch_all_current", lambda **kwargs: [{"행정규칙일련번호": "1"}])
    counter = Counter()
    counter.inc("errors")
    monkeypatch.setattr(fetch_cache, "fetch_details", lambda *args, **kwargs: counter)
    def forbidden(*args):
        raise AssertionError("incomplete fetch must preserve cache and snapshot")
    monkeypatch.setattr(fetch_cache, "prune_stale_cache", forbidden)
    monkeypatch.setattr(snapshot, "write_current_snapshot", forbidden)
    with pytest.raises(SystemExit):
        fetch_cache.main()
