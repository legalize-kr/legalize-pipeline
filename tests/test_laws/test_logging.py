"""Tests for structured failure logging and routing at import_from_cache call sites."""

import logging
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_detail(articles=None, addenda=None):
    """Minimal detail dict for get_law_detail monkeypatching."""
    return {
        "metadata": {
            "법령명한글": "테스트법",
            "법령MST": "999",
            "법령ID": "",
            "법령구분": "법률",
            "법령구분코드": "",
            "소관부처명": "",
            "소관부처코드": "",
            "공포일자": "20240101",
            "공포번호": "",
            "시행일자": "",
            "제개정구분": "",
            "법령분야": "",
        },
        "articles": articles if articles is not None else [],
        "addenda": addenda if addenda is not None else [],
        "raw_xml": b"<law/>",
    }


# ---------------------------------------------------------------------------
# test_empty_body_caller_calls_mark_failed_and_quarantine
# ---------------------------------------------------------------------------

def test_empty_body_caller_calls_mark_failed_and_quarantine(tmp_path, monkeypatch):
    """ValueError from law_to_markdown routes to mark_failed_and_quarantine with reason='empty_body'."""
    import laws.import_laws as il
    import laws.failures as failures
    import laws.cache as cache_mod
    import laws.converter as conv

    # Point KR_DIR at tmp_path/kr and FAILED_FILE into tmp_path
    kr_dir = tmp_path / "kr"
    kr_dir.mkdir()
    monkeypatch.setattr(il, "KR_DIR", kr_dir)
    monkeypatch.setattr(conv, "KR_DIR", kr_dir, raising=False)
    monkeypatch.setattr(failures, "FAILED_FILE", tmp_path / ".failed_msts.json")

    # Seed a single MST in the cache list
    monkeypatch.setattr(cache_mod, "list_cached_msts", lambda: ["999"])

    # get_law_detail returns a detail with empty body (no articles, no addenda content)
    detail = _make_detail(articles=[], addenda=[])
    monkeypatch.setattr(il, "get_law_detail", lambda _mst: detail)

    # Stub commit_law so git is not invoked
    monkeypatch.setattr(il, "commit_law", lambda *_a, **_kw: False)
    monkeypatch.setattr(il, "mark_processed", lambda _mst: None)

    mock_quarantine = MagicMock()
    monkeypatch.setattr(failures, "mark_failed_and_quarantine", mock_quarantine)

    il.import_from_cache(dry_run=False)

    mock_quarantine.assert_called_once()
    call_kwargs = mock_quarantine.call_args
    assert call_kwargs.kwargs["reason"] == "empty_body"
    assert "path" in call_kwargs.kwargs


# ---------------------------------------------------------------------------
# test_unknown_exception_routes_to_classify_and_mark_failed
# ---------------------------------------------------------------------------

def test_unknown_exception_routes_to_classify_and_mark_failed(tmp_path, monkeypatch):
    """A KeyError inside the loop body routes to mark_failed with reason='metadata_missing'."""
    import laws.import_laws as il
    import laws.failures as failures
    import laws.cache as cache_mod

    kr_dir = tmp_path / "kr"
    kr_dir.mkdir()
    monkeypatch.setattr(il, "KR_DIR", kr_dir)
    monkeypatch.setattr(failures, "FAILED_FILE", tmp_path / ".failed_msts.json")

    monkeypatch.setattr(cache_mod, "list_cached_msts", lambda: ["999"])

    # get_law_detail raises KeyError (simulates metadata_missing)
    def _raise_key_error(mst):
        raise KeyError("법령명한글")

    monkeypatch.setattr(il, "get_law_detail", _raise_key_error)
    monkeypatch.setattr(il, "commit_law", lambda *_a, **_kw: False)
    monkeypatch.setattr(il, "mark_processed", lambda _mst: None)

    mock_mark_failed = MagicMock()
    monkeypatch.setattr(failures, "mark_failed", mock_mark_failed)

    il.import_from_cache(dry_run=False)

    # Should have been called at least once (parse-time or write-time handler)
    assert mock_mark_failed.call_count >= 1
    # Find any call with reason="metadata_missing"
    reasons = [c.kwargs.get("reason") for c in mock_mark_failed.call_args_list]
    assert "metadata_missing" in reasons


# ---------------------------------------------------------------------------
# test_caplog_emits_stable_keys_on_failure
# ---------------------------------------------------------------------------

def test_caplog_emits_stable_keys_on_failure(tmp_path, monkeypatch, caplog):
    """log_failure emits an 'import_failure' record with step, mst, exc_type extra fields."""
    import laws.import_laws as il
    import laws.failures as failures
    import laws.cache as cache_mod

    kr_dir = tmp_path / "kr"
    kr_dir.mkdir()
    monkeypatch.setattr(il, "KR_DIR", kr_dir)
    monkeypatch.setattr(failures, "FAILED_FILE", tmp_path / ".failed_msts.json")

    monkeypatch.setattr(cache_mod, "list_cached_msts", lambda: ["999"])

    def _raise_runtime(mst):
        raise RuntimeError("api down")

    monkeypatch.setattr(il, "get_law_detail", _raise_runtime)
    monkeypatch.setattr(il, "commit_law", lambda *_a, **_kw: False)
    monkeypatch.setattr(il, "mark_processed", lambda _mst: None)

    with caplog.at_level(logging.ERROR, logger="laws.failures"):
        il.import_from_cache(dry_run=False)

    failure_records = [r for r in caplog.records if r.getMessage() == "import_failure"]
    assert failure_records, "Expected at least one 'import_failure' log record"
    rec = failure_records[0]
    assert hasattr(rec, "step")
    assert hasattr(rec, "mst")
    assert hasattr(rec, "exc_type")
