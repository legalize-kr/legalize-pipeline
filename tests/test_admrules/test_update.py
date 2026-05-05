"""Tests for admrules/update.py."""

from admrules import update


def test_run_fetches_then_imports(tmp_path, monkeypatch):
    class Counter:
        def snapshot(self):
            return (1, 2, 3)

    calls = []
    monkeypatch.setattr(update, "fetch_all_current", lambda **kwargs: calls.append(("fetch", kwargs)) or [{"행정규칙일련번호": "1"}])
    monkeypatch.setattr(update, "fetch_details", lambda entries, workers, limit: calls.append(("details", entries, workers, limit)) or Counter())
    monkeypatch.setattr(update, "_committed_serials", lambda repo: set())
    monkeypatch.setattr(
        update,
        "import_from_cache",
        lambda repo, limit, commit, serials, skip_dedup: calls.append(("import", repo, limit, commit, serials, skip_dedup))
        or {"written": 4, "committed": 5, "skipped": 6, "errors": 7},
    )

    monkeypatch.setattr(update, "_date_range", lambda days: f"range-{days}")
    stats = update.run(repo=tmp_path, limit=10, workers=2, commit=True, knd=["1"], org="1741000")

    assert stats == {
        "cached": 1,
        "fetched": 2,
        "fetch_errors": 3,
        "written": 4,
        "committed": 5,
        "skipped": 6,
        "errors": 7,
    }
    assert calls[0] == ("fetch", {"knd_values": ["1"], "org": "1741000", "max_entries": 10, "date_range": "range-14"})
    assert calls[2] == ("import", tmp_path, None, True, ["1"], True)


def test_run_imports_only_uncommitted_current_serials(tmp_path, monkeypatch):
    class Counter:
        def snapshot(self):
            return (2, 0, 0)

    imported = []
    monkeypatch.setattr(
        update,
        "fetch_all_current",
        lambda **kwargs: [
            {"행정규칙일련번호": "1"},
            {"행정규칙일련번호": "2"},
            {"행정규칙일련번호": "2"},
        ],
    )
    monkeypatch.setattr(update, "fetch_details", lambda entries, workers, limit: Counter())
    monkeypatch.setattr(update, "_committed_serials", lambda repo: {"1"})
    monkeypatch.setattr(
        update,
        "import_from_cache",
        lambda repo, limit, commit, serials, skip_dedup: imported.extend(serials)
        or {"written": 1, "committed": 1, "skipped": 0, "errors": 0},
    )
    monkeypatch.setattr(update, "_date_range", lambda days: f"range-{days}")

    update.run(repo=tmp_path, commit=True)

    assert imported == ["2"]
