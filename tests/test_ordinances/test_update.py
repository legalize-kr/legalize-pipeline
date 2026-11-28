"""Tests for ordinances/update.py."""

import pytest

from ordinances import update


@pytest.fixture(autouse=True)
def isolate_reviewed_source_defects(monkeypatch):
    monkeypatch.setattr(update.deferred_revisions, "load_entries", lambda: {})


def test_run_fetches_then_imports(tmp_path, monkeypatch):
    class Counter:
        def snapshot(self):
            return (1, 2, 0)

    calls = []
    monkeypatch.setattr(
        update,
        "fetch_all_current",
        lambda types, **kwargs: calls.append(("fetch", types, kwargs))
        or [{"자치법규ID": "1", "자치법규일련번호": "current", "자치법규명": "현재 조례", "공포일자": "20260101"}],
    )
    monkeypatch.setattr(
        update,
        "fetch_history_for_entries",
        lambda entries, types: calls.append(("history", entries, types))
        or [
            {"자치법규ID": "1", "자치법규일련번호": "old", "자치법규명": "이전 조례", "공포일자": "20200101"},
            {"자치법규ID": "1", "자치법규일련번호": "current", "자치법규명": "현재 조례", "공포일자": "20260101"},
        ],
    )
    monkeypatch.setattr(update, "fetch_details", lambda entries, workers, limit=None, refresh_cached=False: calls.append(("details", entries, workers, limit, refresh_cached)) or Counter())
    monkeypatch.setattr(update, "_committed_metadata", lambda repo: (set(), set()))
    monkeypatch.setattr(
        update,
        "import_from_cache",
        lambda repo, limit, commit, serials, skip_dedup: calls.append(("import", repo, limit, commit, serials, skip_dedup))
        or {"written": 4, "committed": 5, "skipped": 6, "errors": 7},
    )

    monkeypatch.setattr(update, "_date_range", lambda days: "20260101~20260115")
    stats = update.run(repo=tmp_path, limit=10, workers=2, commit=True, types=["조례"], org="11", sborg="110")

    assert stats == {
        "cached": 1,
        "fetched": 2,
        "fetch_errors": 0,
        "deferred": 0,
        "written": 4,
        "committed": 5,
        "skipped": 6,
        "errors": 7,
        "missing": 2,
    }
    assert calls[0] == ("fetch", ["조례"], {"org": "11", "sborg": "110", "max_entries": 10, "date_range": "20260101~20260115"})
    assert calls[2][0] == "details"
    assert [entry["자치법규일련번호"] for entry in calls[2][1]] == ["old", "current"]
    assert calls[2][4] is True
    assert calls[3] == ("import", tmp_path, None, True, ["old", "current"], False)


def test_run_imports_only_uncommitted_serials_for_existing_identity(tmp_path, monkeypatch):
    class Counter:
        def snapshot(self):
            return (2, 0, 0)

    imported = []
    monkeypatch.setattr(
        update,
        "fetch_all_current",
        lambda types, **kwargs: [
            {"자치법규ID": "1", "자치법규일련번호": "new", "자치법규명": "현재 조례", "공포일자": "20260102"},
        ],
    )
    monkeypatch.setattr(
        update,
        "fetch_history_for_entries",
        lambda entries, types: [
            {"자치법규ID": "1", "자치법규일련번호": "old-missing", "자치법규명": "이전 조례", "공포일자": "20200101"},
            {"자치법규ID": "1", "자치법규일련번호": "new", "자치법규명": "현재 조례", "공포일자": "20260102"},
        ],
    )
    monkeypatch.setattr(update, "fetch_details", lambda entries, workers, limit=None, refresh_cached=False: Counter())
    monkeypatch.setattr(update, "_committed_metadata", lambda repo: ({"already"}, {"1"}))
    monkeypatch.setattr(
        update,
        "import_from_cache",
        lambda repo, limit, commit, serials, skip_dedup: imported.extend(serials)
        or {"written": 1, "committed": 1, "skipped": 0, "errors": 0},
    )
    monkeypatch.setattr(update, "_date_range", lambda days: "20260101~20260115")

    update.run(repo=tmp_path, commit=True)

    assert imported == ["new"]


def test_committed_metadata_reads_git_history_once(tmp_path, monkeypatch):
    from ordinances import git_engine
    (tmp_path / ".git").mkdir()
    calls = []

    class Result:
        returncode = 0
        stdout = "2026-01-02\n자치법규ID: 1\n자치법규일련번호: 10\n\x002026-01-03\n자치법규ID: 2\n자치법규일련번호: 20\n"

    monkeypatch.setattr(
        git_engine.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Result(),
    )

    serials, identities = update._committed_metadata(tmp_path)

    assert serials == {"10", "20"}
    assert identities == {"1": ("2026-01-02", 10), "2": ("2026-01-03", 20)}
    assert len(calls) == 1


def _prepare_update(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from ordinances import api_client, cache, checkpoint, fetch_cache
    from tests.test_ordinances.test_converter import SAMPLE_XML

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    for key, value in [("user.name", "Test"), ("user.email", "test@example.invalid")]:
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-m", "initial"], check=True, capture_output=True)
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(cache, "HISTORY_DIR", tmp_path / "cache/history")
    monkeypatch.setattr(checkpoint, "CHECKPOINT_FILE", tmp_path / "checkpoint.json")
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    monkeypatch.setattr(fetch_cache, "append_failure", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_client, "_request", lambda url, params, **kwargs: SimpleNamespace(content=cache.get_detail(params["MST"], historical=True)))
    cache.put_detail("12345", SAMPLE_XML.encode(), historical=True)
    entry = {"자치법규ID": "2000111", "자치법규일련번호": "12345", "공포일자": "20261011"}
    monkeypatch.setattr(update, "fetch_all_current", lambda *args, **kwargs: [entry])
    monkeypatch.setattr(update, "fetch_history_for_entries", lambda *args, **kwargs: [entry])
    monkeypatch.setattr(update, "_date_range", lambda days: "20261001~20261011")
    return repo


def test_update_imports_revision_present_only_on_archive_branch(tmp_path, monkeypatch):
    import subprocess
    from ordinances.import_ordinances import import_from_cache

    repo = _prepare_update(tmp_path, monkeypatch)
    subprocess.run(["git", "-C", str(repo), "switch", "-c", "archive"], check=True)
    assert import_from_cache(repo, commit=True, serials=["12345"])["committed"] == 1
    subprocess.run(["git", "-C", str(repo), "switch", "main"], check=True)
    stats = update.run(repo=repo, commit=True)
    assert stats["committed"] == 1
    assert len(list(repo.rglob("본문.md"))) == 1
    assert "12345" in update._committed_metadata(repo)[0]
    assert update.run(repo=repo, commit=True)["committed"] == 0


def test_cli_rejects_parse_error_and_recovers_on_next_run(tmp_path, monkeypatch):
    import sys
    import pytest
    from ordinances import cache
    from tests.test_ordinances.test_converter import SAMPLE_XML

    repo = _prepare_update(tmp_path, monkeypatch)
    cache.put_detail("12345", b"<broken", historical=True)
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--commit"])
    with pytest.raises(SystemExit, match="fetch_errors=1"):
        update.main()
    assert not list(repo.rglob("본문.md"))
    cache.put_detail("12345", SAMPLE_XML.encode(), historical=True)
    update.main()
    assert len(list(repo.rglob("본문.md"))) == 1
    assert update.run(repo=repo, commit=True)["committed"] == 0


def test_cli_rejects_uncommitted_selected_revision(tmp_path, monkeypatch):
    import sys
    import pytest
    from ordinances import import_ordinances

    repo = _prepare_update(tmp_path, monkeypatch)
    monkeypatch.setattr(import_ordinances, "commit_ordinance", lambda *args, **kwargs: False)
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--commit"])
    with pytest.raises(SystemExit, match="missing=1"):
        update.main()


def test_update_allows_confirmed_source_absence(tmp_path, monkeypatch):
    from ordinances import cache, fetch_cache

    def confirmed_absence(*args, **kwargs):
        raise fetch_cache.NoResultError("no ordinance detail")

    monkeypatch.setattr(fetch_cache, "get_ordinance_detail", confirmed_absence)

    repo = _prepare_update(tmp_path, monkeypatch)
    cache.detail_path("12345", historical=True).unlink()
    cache.add_no_result_serial("12345")
    stats = update.run(repo=repo, commit=True)
    assert stats["fetch_errors"] == stats["errors"] == 0
    assert stats["missing"] == 0


def test_previous_source_absence_does_not_hide_a_missing_restored_commit(tmp_path, monkeypatch):
    import sys
    from ordinances import cache, import_ordinances

    repo = _prepare_update(tmp_path, monkeypatch)
    cache.add_no_result_serial("12345")
    monkeypatch.setattr(import_ordinances, "commit_ordinance", lambda *args, **kwargs: False)
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--commit"])

    with pytest.raises(SystemExit, match="missing=1"):
        update.main()


def test_partial_import_recovers_without_reimporting_successful_revisions(tmp_path, monkeypatch):
    import sys
    import pytest
    from ordinances import cache
    from tests.test_ordinances.test_converter import SAMPLE_XML

    repo = _prepare_update(tmp_path, monkeypatch)
    entries = [
        {"자치법규ID": "2000111", "자치법규일련번호": "12345", "공포일자": "20261011"},
        {"자치법규ID": "2000112", "자치법규일련번호": "12346", "공포일자": "20261011"},
    ]
    monkeypatch.setattr(update, "fetch_all_current", lambda *args, **kwargs: entries)
    monkeypatch.setattr(update, "fetch_history_for_entries", lambda *args, **kwargs: entries)
    fixed_xml = SAMPLE_XML.replace("2000111", "2000112").replace("12345", "12346")
    cache.put_detail("12346", fixed_xml.encode(), historical=True)
    from ordinances import import_ordinances
    write = import_ordinances.atomic_write_text

    def fail_second_write(path, text):
        if "자치법규ID: '2000112'" in text:
            raise OSError("temporary write failure")
        write(path, text)

    monkeypatch.setattr(import_ordinances, "atomic_write_text", fail_second_write)
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--commit"])
    with pytest.raises(SystemExit, match="errors=1, missing=1"):
        update.main()
    assert update._committed_metadata(repo)[0] == {"12345"}
    monkeypatch.setattr(import_ordinances, "atomic_write_text", write)
    stats = update.run(repo=repo, commit=True)
    assert stats["committed"] == 1
    assert stats["missing"] == stats["errors"] == 0
    assert update._committed_metadata(repo)[0] == {"12345", "12346"}
    assert update.run(repo=repo, commit=True)["committed"] == 0


def test_import_cli_fails_on_malformed_cache(tmp_path, monkeypatch):
    import sys
    import pytest
    from ordinances import cache, import_ordinances

    repo = _prepare_update(tmp_path, monkeypatch)
    cache.put_detail("12345", b"<broken", historical=True)
    monkeypatch.setattr(sys, "argv", ["ordinances.import_ordinances", "--repo", str(repo), "--commit"])
    with pytest.raises(SystemExit, match="errors=1"):
        import_ordinances.main()


def test_coverage_accepts_repeal_commit_without_current_document(tmp_path, monkeypatch):
    from ordinances import cache
    from tests.test_ordinances.test_converter import SAMPLE_XML

    repo = _prepare_update(tmp_path, monkeypatch)
    cache.put_detail("12345", SAMPLE_XML.replace("일부개정", "폐지").encode(), historical=True)
    stats = update.run(repo=repo, commit=True)
    assert stats["committed"] == 1
    assert stats["missing"] == stats["errors"] == 0
    assert not list(repo.rglob("본문.md"))
    assert update._committed_metadata(repo)[0] == {"12345"}


def test_cli_rejects_fetch_failure_before_publish(tmp_path, monkeypatch):
    import sys
    import pytest
    from core.counter import Counter
    from ordinances import cache

    repo = _prepare_update(tmp_path, monkeypatch)
    cache.detail_path("12345", historical=True).unlink()
    counter = Counter()
    counter.inc("errors")
    monkeypatch.setattr(update, "fetch_details", lambda *args, **kwargs: counter)
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo)])
    with pytest.raises(SystemExit, match="fetch_errors=1"):
        update.main()
    assert not list(repo.rglob("본문.md"))


def test_retry_of_older_revision_does_not_overwrite_newer_revision(tmp_path, monkeypatch):
    import sys
    import pytest
    from ordinances import cache
    from ordinances.import_ordinances import import_from_cache
    from tests.test_ordinances.test_converter import SAMPLE_XML

    repo = _prepare_update(tmp_path, monkeypatch)
    newer = SAMPLE_XML.replace("12345", "12346").replace("20210930", "20261011")
    cache.put_detail("12346", newer.encode(), historical=True)
    assert import_from_cache(repo, commit=True, serials=["12346"])["committed"] == 1
    current = next(repo.rglob("본문.md"))
    before = current.read_bytes()
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--commit"])
    with pytest.raises(SystemExit, match="errors=1"):
        update.main()
    assert current.read_bytes() == before


def test_daily_backfill_cannot_resurrect_repealed_ordinance(tmp_path, monkeypatch):
    import subprocess
    from ordinances import cache
    from ordinances.import_ordinances import import_from_cache
    from tests.test_ordinances.test_converter import SAMPLE_XML

    repo = _prepare_update(tmp_path, monkeypatch)
    repeal = SAMPLE_XML.replace("12345", "12346").replace("일부개정", "폐지")
    cache.put_detail("12346", repeal.encode(), historical=True)
    assert import_from_cache(repo, commit=True, serials=["12346"])["committed"] == 1
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    stats = update.run(repo=repo, commit=True)
    assert stats["errors"] == stats["missing"] == 1
    assert not list(repo.rglob("본문.md"))
    assert head == subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])

    cache.put_detail("12347", SAMPLE_XML.replace("12345", "12347").encode(), historical=True)
    assert import_from_cache(repo, commit=True, serials=["12347"])["committed"] == 1
    assert "12347" in next(repo.rglob("본문.md")).read_text()


def test_reimport_of_committed_old_revision_leaves_latest_tree_unchanged(tmp_path, monkeypatch):
    from ordinances import cache
    from ordinances.import_ordinances import import_from_cache
    from tests.test_ordinances.test_converter import SAMPLE_XML

    repo = _prepare_update(tmp_path, monkeypatch)
    newer = SAMPLE_XML.replace("12345", "12346").replace("20210930", "20261011")
    cache.put_detail("12346", newer.encode(), historical=True)
    assert import_from_cache(repo, commit=True, serials=["12345", "12346"])["committed"] == 2
    current = next(repo.rglob("본문.md"))
    before = current.read_bytes()
    stats = import_from_cache(repo, commit=True, serials=["12345"])
    assert stats["written"] == stats["committed"] == 0
    assert stats["skipped"] == 1
    assert current.read_bytes() == before


def test_incremental_import_preserves_existing_identity_at_colliding_path(tmp_path, monkeypatch):
    from ordinances import cache
    from ordinances.import_ordinances import import_from_cache
    from tests.test_ordinances.test_converter import SAMPLE_XML

    repo = _prepare_update(tmp_path, monkeypatch)
    assert import_from_cache(repo, commit=True, serials=["12345"])["committed"] == 1
    original = next(repo.rglob("본문.md"))
    before = original.read_bytes()
    other = SAMPLE_XML.replace("2000111", "2000112").replace("12345", "12346")
    cache.put_detail("12346", other.encode(), historical=True)
    assert import_from_cache(repo, commit=True, serials=["12346"])["committed"] == 1
    assert original.read_bytes() == before
    assert len(list(repo.rglob("본문.md"))) == 2


def test_update_recovers_revision_from_negative_cache(tmp_path, monkeypatch):
    from ordinances import cache, fetch_cache
    from tests.test_ordinances.test_converter import SAMPLE_XML

    repo = _prepare_update(tmp_path, monkeypatch)
    cache.detail_path("12345", historical=True).unlink()
    cache.add_no_result_serial("12345")
    requests = []

    def recovered_detail(ordinance_id, *, mst, on_request_attempt):
        requests.append(mst)
        on_request_attempt()
        raw = SAMPLE_XML.encode()
        cache.put_detail(mst, raw, historical=True)
        return raw

    monkeypatch.setattr(fetch_cache, "get_ordinance_detail", recovered_detail)
    stats = update.run(repo=repo, commit=True)
    assert requests == ["12345"]
    assert stats["fetched"] == stats["committed"] == 1
    assert stats["errors"] == stats["fetch_errors"] == stats["missing"] == 0
    assert "12345" in update._committed_metadata(repo)[0]


def test_cli_preserves_duplicate_article_numbers(tmp_path, monkeypatch):
    import sys
    from ordinances import cache
    from tests.test_ordinances.test_converter import SAMPLE_XML

    repo = _prepare_update(tmp_path, monkeypatch)
    duplicate = '<조><조문번호>000100</조문번호><조문여부>Y</조문여부><조내용>제1조제1항의 담당자</조내용></조>'
    cache.put_detail("12345", SAMPLE_XML.replace('</자치법규>', duplicate + '</자치법규>').encode(), historical=True)
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--commit"])
    update.main()
    assert "duplicate ordinance article 1" in next(repo.rglob("본문.md")).read_text()
    assert "12345" in update._committed_metadata(repo)[0]


def test_cli_preserves_repeated_article_heading(tmp_path, monkeypatch):
    import sys
    from ordinances import cache
    from tests.test_ordinances.test_converter import SAMPLE_XML

    repo = _prepare_update(tmp_path, monkeypatch)
    malformed = SAMPLE_XML.replace("제1조(목적)", "제1조 제1조\n2(목적)")
    cache.put_detail("12345", malformed.encode(), historical=True)
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--commit"])
    update.main()
    assert "제1조 제1조\n2(목적)" in next(repo.rglob("본문.md")).read_text()
    assert "12345" in update._committed_metadata(repo)[0]
