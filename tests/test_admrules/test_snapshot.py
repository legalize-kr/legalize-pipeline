"""Regression coverage for source-current selection and publication history."""

import json
import subprocess
from pathlib import Path

import pytest

from admrules import cache, fetch_cache, snapshot, update
from admrules.converter import is_repeal_revision
from admrules.import_admrules import import_from_cache
from admrules.validate import validate_current_snapshot, validate_frontmatter


def detail(serial, *, name="금융감독원 규정", kind="세칙", status="Y", issue="20240101", amendment="제정", code="200401"):
    return f"""<AdmRulService><행정규칙ID>123</행정규칙ID>
<행정규칙일련번호>{serial}</행정규칙일련번호><행정규칙명>{name}</행정규칙명>
<행정규칙종류>{kind}</행정규칙종류><소관부처명>금융감독원</소관부처명>
<발령일자>{issue}</발령일자><현행여부>{status}</현행여부>
<제개정구분명>{amendment}</제개정구분명><제개정구분코드>{code}</제개정구분코드>
<조문내용>제1조 본문 {serial}</조문내용></AdmRulService>""".encode()


def source_row(serial, **overrides):
    return {"행정규칙ID": "123", "행정규칙일련번호": serial,
            "현행연혁구분": "현행", "제개정구분명": "제정", **overrides}


def init_repo(path):
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.invalid"], check=True)


@pytest.mark.parametrize("kind", ["세칙", "규정", "등기예규", "가족관계등록예규", "매뉴얼"])
def test_nonstandard_rule_survives_import_and_validation(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1", kind=kind))
    repo = tmp_path / "out"
    assert import_from_cache(repo)["written"] == 1
    files = list(repo.rglob("본문.md"))
    assert len(files) == 1 and validate_frontmatter(files[0]) == []


@pytest.mark.parametrize("name,code,expected", [
    ("폐지제정", "200407", False), ("폐지제정", "", False),
    ("폐지", "200404", True), ("타법폐지", "200410", True),
    ("폐지", "", True), ("타법폐지", "", True),
])
def test_repeal_codes_are_exact(name, code, expected):
    assert is_repeal_revision({"제개정구분": name, "제개정구분코드": code}) is expected


def test_repeal_reenact_writes_body(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1", amendment="폐지제정", code="200407"))
    assert import_from_cache(tmp_path / "out")["written"] == 1
    assert len(list((tmp_path / "out").rglob("본문.md"))) == 1


def test_future_revision_stays_in_history_and_current_body_is_restored(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    monkeypatch.setattr(fetch_cache.checkpoint, "mark_detail_processed", lambda *args: None)
    cache.put_detail("1", detail("1"))
    cache.put_detail("2", detail("2", name="새 규정", status="N", issue="20260201"))
    snapshot.write_current_snapshot([source_row("1"), source_row("2", 현행연혁구분="연혁")])
    repo = tmp_path / "out"
    init_repo(repo)
    assert import_from_cache(repo, commit=True)["errors"] == 0
    snapshot.reconcile_current_snapshot(repo, commit=True)
    files = list(repo.rglob("본문.md"))
    assert len(files) == 1 and "본문 1" in files[0].read_text()
    log = subprocess.check_output(["git", "-C", str(repo), "log", "--format=%B"], text=True)
    assert "행정규칙일련번호: 2" in log
    future_commit = subprocess.check_output(["git", "-C", str(repo), "log", "--format=%H", "--grep=^세칙: 새 규정"], text=True).strip()
    assert "본문 2" in subprocess.check_output(["git", "-C", str(repo), "show", f"{future_commit}:국무총리/금융위원회/금융감독원/세칙/새 규정/본문.md"], text=True)
    assert snapshot.reconcile_current_snapshot(repo, commit=True)["snapshot_committed"] == 0

    # Activation must work after the publication lookback and after deduplication.
    monkeypatch.setattr(update, "fetch_all_current", lambda **kwargs: [source_row("2")] if kwargs.get("history") is False else [])
    monkeypatch.setattr(fetch_cache, "get_admrule_detail", lambda serial, **kwargs: cache.get_detail(serial))
    result = update.run(repo=repo, commit=True)
    assert result["snapshot_written"] == 1
    files = list(repo.rglob("본문.md"))
    assert len(files) == 1 and "본문 2" in files[0].read_text()


def test_missing_detail_does_not_replace_snapshot_or_modify_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1"))
    snapshot.write_current_snapshot([source_row("1")])
    original = (cache.CACHE_DIR / snapshot.SNAPSHOT_NAME).read_bytes()
    with pytest.raises(RuntimeError, match="Missing current"):
        snapshot.write_current_snapshot([source_row("2")])
    assert (cache.CACHE_DIR / snapshot.SNAPSHOT_NAME).read_bytes() == original
    repo = tmp_path / "out"
    import_from_cache(repo)
    before = {str(p): p.read_bytes() for p in repo.rglob("본문.md")}
    data = json.loads(original)
    data["rules"]["123"] = "2"
    (cache.CACHE_DIR / snapshot.SNAPSHOT_NAME).write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="Missing snapshot"):
        snapshot.reconcile_current_snapshot(repo)
    assert {str(p): p.read_bytes() for p in repo.rglob("본문.md")} == before


def test_snapshot_validator_detects_missing_and_wrong_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1"))
    snapshot.write_current_snapshot([source_row("1")])
    manifest = cache.CACHE_DIR / snapshot.SNAPSHOT_NAME
    repo = tmp_path / "out"
    import_from_cache(repo)
    assert validate_current_snapshot(repo, manifest) == []
    path = next(repo.rglob("본문.md"))
    path.write_text(path.read_text().replace("행정규칙일련번호: '1'", "행정규칙일련번호: '2'"))
    assert any("Incorrect current revisions" in e for e in validate_current_snapshot(repo, manifest))
    path.unlink()
    assert any("Missing current rules" in e for e in validate_current_snapshot(repo, manifest))


def test_live_current_detail_is_retained_when_search_omits_it(tmp_path, monkeypatch):
    from admrules import api_client
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1"))
    supplemental = detail("2").replace(b">123<", b">456<")
    cache.put_detail("2", supplemental)
    probes = []
    def live_detail(serial, *, refresh):
        assert refresh is True
        probes.append(serial)
        return supplemental
    monkeypatch.setattr(api_client, "get_admrule_detail", live_detail)
    result = snapshot.write_current_snapshot([source_row("1")], history_entries=[])
    assert result["rules"] == {"123": "1", "456": "2"}
    assert probes == ["2"]
    assert result["supplemental"][0]["id"] == "456"

    # A later daily run rechecks the retained rule even without a recent issue date.
    retired = supplemental.replace(b">Y<", b">N<")
    monkeypatch.setattr(api_client, "get_admrule_detail", lambda *args, **kwargs: retired)
    result = snapshot.write_current_snapshot([source_row("1")], history_entries=[])
    assert result["rules"] == {"123": "1"}
    assert result["excluded"][0]["reason"] == "live_detail_non_current"


def test_current_identity_change_refreshes_detail_before_selection(tmp_path, monkeypatch):
    from admrules import api_client
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1").replace(b">123<", b">456<"))
    calls = []
    def refreshed(serial, *, refresh):
        calls.append((serial, refresh))
        cache.put_detail(serial, detail(serial))
        return detail(serial)
    monkeypatch.setattr(api_client, "get_admrule_detail", refreshed)
    assert snapshot.write_current_snapshot([source_row("1")])["rules"] == {"123": "1"}
    assert calls == [("1", True)]
    original = (cache.CACHE_DIR / snapshot.SNAPSHOT_NAME).read_bytes()
    cache.put_detail("1", detail("1").replace(b">123<", b">456<"))
    monkeypatch.setattr(api_client, "get_admrule_detail", lambda *args, **kwargs: cache.get_detail("1"))
    with pytest.raises(RuntimeError, match="Current admrule identity mismatch"):
        snapshot.write_current_snapshot([source_row("1")])
    assert (cache.CACHE_DIR / snapshot.SNAPSHOT_NAME).read_bytes() == original


@pytest.mark.parametrize("response, message", [
    ("<Law><result>사용자 정보 검증에 실패</result><msg>bad key</msg></Law>", "API error"),
    ("<Law/>", "unexpected admrule detail root"),
])
def test_api_failure_during_absent_rule_probe_preserves_selection(tmp_path, monkeypatch, response, message):
    from admrules import api_client
    from types import SimpleNamespace
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1"))
    cache.put_detail("2", detail("2").replace(b">123<", b">456<"))
    original = {"schema_version": 1, "observed_on": "2026-10-09", "rules": {"123": "1", "456": "2"}}
    path = cache.CACHE_DIR / snapshot.SNAPSHOT_NAME
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    monkeypatch.setattr(api_client, "_request", lambda *args: SimpleNamespace(content=response.encode()))
    with pytest.raises(RuntimeError, match=message):
        snapshot.write_current_snapshot([source_row("1")], history_entries=[])
    assert path.read_bytes() == before
    assert cache.get_detail("2") == detail("2").replace(b">123<", b">456<")


@pytest.mark.parametrize("entrypoint", ["update", "import"])
def test_archive_only_revision_does_not_skip_main_import(tmp_path, monkeypatch, entrypoint):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    cache.put_detail("1", detail("1"))
    repo = tmp_path / "out"
    init_repo(repo)
    (repo / "README.md").write_text("test")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "switch", "-c", "archive"], check=True, capture_output=True)
    import_from_cache(repo, commit=True)
    subprocess.run(["git", "-C", str(repo), "switch", "main"], check=True, capture_output=True)
    row = source_row("1", 현행연혁구분="연혁")
    monkeypatch.setattr(update, "fetch_all_current", lambda **kwargs: [row])
    stats = (update.run(repo=repo, commit=True, knd=["3"]) if entrypoint == "update"
             else import_from_cache(repo, commit=True))
    assert stats["committed"] == 1
    assert list(repo.rglob("본문.md"))
    log = subprocess.check_output(["git", "-C", str(repo), "log", "HEAD", "--format=%B"], text=True)
    assert "행정규칙일련번호: 1" in log


def test_full_import_cli_rejects_bad_snapshot_before_writing(tmp_path, monkeypatch):
    from admrules import import_admrules
    import sys
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1"))
    path = cache.CACHE_DIR / snapshot.SNAPSHOT_NAME
    path.write_text(json.dumps({"schema_version": 1, "observed_on": "2026-10-09", "rules": {"123": "2"}}))
    repo = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["admrules.import_admrules", "--repo", str(repo)])
    with pytest.raises(RuntimeError, match="Missing snapshot"):
        import_admrules.main()
    assert not repo.exists()


@pytest.mark.parametrize("rows", [[], [source_row("1"), source_row("1")]])
def test_empty_or_duplicate_selection_does_not_replace_snapshot(tmp_path, monkeypatch, rows):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1"))
    snapshot.write_current_snapshot([source_row("1")])
    path = cache.CACHE_DIR / snapshot.SNAPSHOT_NAME
    before = path.read_bytes()
    with pytest.raises(RuntimeError):
        snapshot.write_current_snapshot(rows)
    assert path.read_bytes() == before


def test_current_cached_non_current_detail_is_refetched_through_api(tmp_path, monkeypatch):
    from admrules import api_client
    from types import SimpleNamespace
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    monkeypatch.setattr(fetch_cache.checkpoint, "mark_detail_processed", lambda *args: None)
    cache.put_detail("1", detail("1", status="N"))
    calls = []
    monkeypatch.setattr(api_client, "_request", lambda url, params: calls.append(params) or SimpleNamespace(content=detail("1")))
    result = fetch_cache.fetch_details([source_row("1")], workers=1, refresh_current=True)
    assert result.snapshot() == (0, 1, 0)
    assert len(calls) == 1 and cache.get_detail("1") == detail("1")
    assert snapshot.write_current_snapshot([source_row("1")])["conflicts"] == []


def test_daily_unknown_fetch_failure_preserves_tree_and_snapshot(tmp_path, monkeypatch):
    from core.counter import Counter
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1"))
    snapshot.write_current_snapshot([source_row("1")])
    repo = tmp_path / "out"
    import_from_cache(repo)
    before = {str(p): p.read_bytes() for p in repo.rglob("본문.md")}
    selection = (cache.CACHE_DIR / snapshot.SNAPSHOT_NAME).read_bytes()
    errors = Counter()
    errors.inc("errors")
    monkeypatch.setattr(update, "fetch_all_current", lambda **kwargs: [source_row("2")])
    monkeypatch.setattr(update, "fetch_details", lambda *args, **kwargs: errors)
    with pytest.raises(RuntimeError, match="Incomplete administrative rule update"):
        update.run(repo=repo)
    assert {str(p): p.read_bytes() for p in repo.rglob("본문.md")} == before
    assert (cache.CACHE_DIR / snapshot.SNAPSHOT_NAME).read_bytes() == selection


@pytest.mark.parametrize("limit", [0, 1])
def test_partial_import_does_not_apply_global_selection(tmp_path, monkeypatch, limit):
    from admrules import import_admrules
    import sys
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1"))
    (cache.CACHE_DIR / snapshot.SNAPSHOT_NAME).write_text('{"schema_version":999}')
    repo = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["admrules.import_admrules", "--repo", str(repo), "--limit", str(limit)])
    import_admrules.main()
    assert len(list(repo.rglob("본문.md"))) == limit


def test_snapshot_path_swap_preserves_both_identities(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1", name="규칙 A"))
    cache.put_detail("2", detail("2", name="규칙 B").replace(b">123<", b">456<"))
    repo = tmp_path / "out"
    init_repo(repo)
    import_from_cache(repo, commit=True)
    cache.put_detail("3", detail("3", name="규칙 B", issue="20250101"))
    cache.put_detail("4", detail("4", name="규칙 A", issue="20250101").replace(b">123<", b">456<"))
    snapshot.write_current_snapshot([source_row("3"), source_row("4", 행정규칙ID="456")])
    result = snapshot.reconcile_current_snapshot(repo, commit=True)
    assert result == {"snapshot_written": 2, "snapshot_deleted": 2, "snapshot_committed": 4}
    assert validate_current_snapshot(repo, cache.CACHE_DIR / snapshot.SNAPSHOT_NAME) == []
    assert snapshot.reconcile_current_snapshot(repo, commit=True)["snapshot_committed"] == 0
