"""Tests for ordinances/update.py."""

from ordinances import update


def test_run_fetches_then_imports(tmp_path, monkeypatch):
    class Counter:
        def snapshot(self):
            return (1, 2, 3)

    calls = []
    monkeypatch.setattr(update, "fetch_all_current", lambda types, **kwargs: calls.append(("fetch", types, kwargs)) or [{"자치법규ID": "1"}])
    monkeypatch.setattr(update, "fetch_details", lambda entries, workers, limit: calls.append(("details", entries, workers, limit)) or Counter())
    monkeypatch.setattr(update, "_committed_ids", lambda repo: set())
    monkeypatch.setattr(
        update,
        "import_from_cache",
        lambda repo, limit, commit, ids, skip_dedup: calls.append(("import", repo, limit, commit, ids, skip_dedup))
        or {"written": 4, "committed": 5, "skipped": 6, "errors": 7},
    )

    monkeypatch.setattr(update, "_date_range", lambda days: f"range-{days}")
    stats = update.run(repo=tmp_path, limit=10, workers=2, commit=True, types=["조례"], org="11", sborg="110")

    assert stats == {
        "cached": 1,
        "fetched": 2,
        "fetch_errors": 3,
        "written": 4,
        "committed": 5,
        "skipped": 6,
        "errors": 7,
    }
    assert calls[0] == ("fetch", ["조례"], {"org": "11", "sborg": "110", "max_entries": 10, "date_range": "range-10"})
    assert calls[2] == ("import", tmp_path, None, True, ["1"], True)


def test_run_imports_only_uncommitted_current_ids(tmp_path, monkeypatch):
    class Counter:
        def snapshot(self):
            return (2, 0, 0)

    imported = []
    monkeypatch.setattr(
        update,
        "fetch_all_current",
        lambda types, **kwargs: [
            {"자치법규ID": "1"},
            {"자치법규ID": "2"},
            {"자치법규ID": "2"},
        ],
    )
    monkeypatch.setattr(update, "fetch_details", lambda entries, workers, limit: Counter())
    monkeypatch.setattr(update, "_committed_ids", lambda repo: {"1"})
    monkeypatch.setattr(
        update,
        "import_from_cache",
        lambda repo, limit, commit, ids, skip_dedup: imported.extend(ids)
        or {"written": 1, "committed": 1, "skipped": 0, "errors": 0},
    )
    monkeypatch.setattr(update, "_date_range", lambda days: f"range-{days}")

    update.run(repo=tmp_path, commit=True)

    assert imported == ["2"]
