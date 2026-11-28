"""Regression coverage for source-current selection and publication history."""

import json
import subprocess
from pathlib import Path

import pytest

from admrules import cache, fetch_cache, snapshot, update
from admrules.converter import is_repeal_revision
from admrules.import_admrules import import_from_cache
from admrules.validate import validate_current_snapshot, validate_frontmatter


def detail(serial, *, name="금융감독원 규정", kind="세칙", status="Y", issue="20240101", effective="", amendment="제정", code="200401"):
    return f"""<AdmRulService><행정규칙ID>123</행정규칙ID>
<행정규칙일련번호>{serial}</행정규칙일련번호><행정규칙명>{name}</행정규칙명>
<행정규칙종류>{kind}</행정규칙종류><소관부처명>금융감독원</소관부처명>
<발령일자>{issue}</발령일자><시행일자>{effective}</시행일자><현행여부>{status}</현행여부>
<제개정구분명>{amendment}</제개정구분명><제개정구분코드>{code}</제개정구분코드>
<조문내용>제1조 본문 {serial}</조문내용></AdmRulService>""".encode()


def source_row(serial, **overrides):
    return {"행정규칙ID": "123", "행정규칙일련번호": serial,
            "현행연혁구분": "현행", "제개정구분명": "제정", **overrides}


def init_repo(path):
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.invalid"], check=True)


def rebuild_repo(repo, monkeypatch):
    import sys

    from admrules import rebuild

    init_repo(repo)
    monkeypatch.setattr(sys, "argv", ["admrules.rebuild", "--repo", str(repo), "--commit"])
    rebuild.main()


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


def test_repeal_without_predecessor_preserves_publication_in_git(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1", status="N", amendment="폐지", code="200404"))
    repo = tmp_path / "out"
    init_repo(repo)

    assert import_from_cache(repo, commit=True)["committed"] == 1
    assert import_from_cache(repo, commit=True)["committed"] == 0
    assert not list(repo.rglob("본문.md"))
    message = subprocess.check_output(["git", "-C", str(repo), "log", "-1", "--format=%B"], text=True)
    assert "행정규칙일련번호: 1" in message


def test_future_revision_stays_in_history_and_current_body_is_restored(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    monkeypatch.setattr(fetch_cache.checkpoint, "mark_detail_processed", lambda *args: None)
    cache.put_detail("1", detail("1"))
    cache.put_detail("2", detail("2", name="새 규정", status="N", issue="20260201", effective="20990101"))
    snapshot.write_current_snapshot([source_row("1"), source_row("2", 현행연혁구분="연혁")])
    repo = tmp_path / "out"
    init_repo(repo)
    assert import_from_cache(repo, commit=True)["errors"] == 0
    assert "본문 2" in next(repo.rglob("본문.md")).read_text()
    assert subprocess.check_output(["git", "-C", str(repo), "rev-list", "--count", "HEAD"], text=True).strip() == "2"
    snapshot.reconcile_current_snapshot(repo, commit=True)
    files = list(repo.rglob("본문.md"))
    assert len(files) == 1 and "본문 1" in files[0].read_text()
    log = subprocess.check_output(["git", "-C", str(repo), "log", "--format=%B"], text=True)
    assert "행정규칙일련번호: 2" in log
    future_commit = subprocess.check_output(["git", "-C", str(repo), "log", "--format=%H", "--grep=^세칙: 새 규정"], text=True).strip()
    assert "본문 2" in subprocess.check_output(["git", "-C", str(repo), "show", f"{future_commit}:국무총리/금융위원회/금융감독원/세칙/새 규정/본문.md"], text=True)
    assert snapshot.reconcile_current_snapshot(repo, commit=True)["snapshot_committed"] == 0

    # Activation must work after the publication lookback and after deduplication.
    from admrules import api_client
    monkeypatch.setattr(api_client, "get_admrule_detail", lambda serial, **kwargs: cache.get_detail(serial))
    monkeypatch.setattr(update, "fetch_all_current", lambda **kwargs: [source_row("2")] if kwargs.get("history") is False else [])
    monkeypatch.setattr(fetch_cache, "get_admrule_detail", lambda serial, **kwargs: cache.get_detail(serial))
    with pytest.raises(snapshot.RebuildRequired, match="rebuild required"):
        update.run(repo=repo, commit=True)
    assert "본문 1" in files[0].read_text()
    rebuilt = tmp_path / "rebuilt"
    rebuild_repo(rebuilt, monkeypatch)
    files = list(rebuilt.rglob("본문.md"))
    assert len(files) == 1 and "본문 2" in files[0].read_text()


@pytest.mark.parametrize("scenario,expected", [
    ("stale_current_list", "2"),
    ("outside_lookback", "2"),
    ("withdrawn", "1"),
    ("newer_noncurrent", "1"),
    ("future_effective", "1"),
    ("multiple_live_current", None),
    ("unknown_live_status", None),
    ("no_live_current", None),
])
def test_daily_rechecks_older_snapshot_selection(tmp_path, monkeypatch, scenario, expected):
    from types import SimpleNamespace

    from admrules import api_client

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    older = detail("1")
    newer = detail("2", issue="20240201", effective="20240201")
    cache.put_detail("1", older)
    snapshot.write_current_snapshot([source_row("1")], history_entries=[])
    if scenario == "future_effective":
        newer = detail("2", issue="20240201", effective="20990101", status="N")
    cache.put_detail("2", newer)
    repo = tmp_path / "out"
    init_repo(repo)
    published = ["1"] if scenario == "future_effective" else ["1", "2"]
    assert import_from_cache(repo, serials=published, commit=True)["committed"] == len(published)
    path = next(repo.rglob("본문.md"))
    before = path.read_bytes()
    manifest = cache.CACHE_DIR / snapshot.SNAPSHOT_NAME
    before_manifest = manifest.read_bytes()
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    history = [source_row("2", 발령일자="20240201", 시행일자="20240201")]
    if scenario in {"outside_lookback", "withdrawn"}:
        history = []
    if scenario == "future_effective":
        history = [source_row("2", 발령일자="20240201", 시행일자="20990101", 현행연혁구분="연혁")]

    responses = {
        "1": detail("1", status="N") if expected == "2" or scenario == "no_live_current" else older,
        "2": {
            "withdrawn": "<Law>일치하는 행정규칙이 없습니다.</Law>".encode(),
            "unknown_live_status": detail("2", issue="20240201", effective="20240201", status=""),
            "newer_noncurrent": detail("2", issue="20240201", effective="20240201", status="N"),
            "no_live_current": detail("2", issue="20240201", effective="20240201", status="N"),
        }.get(scenario, newer),
    }
    requests = []

    def request(url, params):
        assert url.endswith("/lawService.do")
        serial = params["ID"]
        requests.append(serial)
        return SimpleNamespace(content=responses[serial])

    monkeypatch.setattr(api_client, "_request", request)
    monkeypatch.setattr(update, "fetch_all_current", lambda **kwargs: [source_row("1")]
                        if kwargs.get("history") is False else history)

    if expected is None:
        with pytest.raises(RuntimeError, match="Current admrule revision conflict"):
            update.run(repo=repo, workers=1, commit=True)
        assert manifest.read_bytes() == before_manifest
        assert path.read_bytes() == before
        assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == head
        return

    if expected == "1":
        with pytest.raises(snapshot.RebuildRequired, match="rebuild required"):
            update.run(repo=repo, workers=1, commit=True)
        assert path.read_bytes() == before
        assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == head
        repo = tmp_path / "rebuilt"
        rebuild_repo(repo, monkeypatch)
        path = next(repo.rglob("본문.md"))
    else:
        update.run(repo=repo, workers=1, commit=True)
    selection = snapshot.load_current_snapshot()
    assert selection["rules"] == {"123": expected}
    assert f"본문 {expected}" in path.read_text()
    assert validate_current_snapshot(repo, manifest) == []
    if expected == "2":
        assert {"1", "2"} <= set(requests)
        assert selection["conflicts"] == [{"id": "123", "serial": "2", "listed_serial": "1",
                                           "reason": "older_current_list_revision"}]
        assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == head
    elif scenario == "withdrawn":
        assert {"1", "2"} <= set(requests)
        assert selection["excluded"] == [{"id": "123", "serial": "2", "reason": "live_detail_no_result"}]
        assert cache.get_detail("2") == newer
        update.run(repo=repo, workers=1, commit=True)
        assert snapshot.load_current_snapshot()["excluded"] == selection["excluded"]


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
    ("<Law><result>사용자 정보 검증에 실패</result><msg>일치하는 행정규칙이 없습니다</msg></Law>", "API error"),
    ("<html><body>일치하는 행정규칙이 없습니다</body></html>", "unexpected admrule detail root"),
    ("<Law>일시적인 서버 오류입니다.</Law>", "unexpected admrule detail root"),
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


@pytest.mark.parametrize("entrypoint", ["update", "fetch_cache"])
def test_absent_rule_no_result_excludes_current_but_preserves_history(tmp_path, monkeypatch, caplog, entrypoint):
    import sys
    from types import SimpleNamespace
    from admrules import api_client
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    cache.put_detail("1", detail("1"))
    withdrawn = detail("2", name="목록에서 제외된 규정").replace(b">123<", b">456<")
    cache.put_detail("2", withdrawn)
    snapshot.write_current_snapshot([source_row("1"), source_row("2", 행정규칙ID="456")])
    repo = tmp_path / "out"
    init_repo(repo)
    assert import_from_cache(repo, commit=True)["committed"] == 2

    response = "<Law>일치하는 행정규칙이 없습니다. 행정규칙명을 확인하여 주십시오.</Law>".encode()
    monkeypatch.setattr(api_client, "_request", lambda *args: SimpleNamespace(content=response))
    rows = [source_row("1")]
    monkeypatch.setattr(fetch_cache, "fetch_all_current", lambda **kwargs: rows)
    monkeypatch.setattr(update, "fetch_all_current", lambda **kwargs: rows)
    if entrypoint == "update":
        with pytest.raises(snapshot.RebuildRequired, match="rebuild required"):
            update.run(repo=repo, commit=True)
        assert len(list(repo.rglob("본문.md"))) == 2
        repo = tmp_path / "rebuilt"
        rebuild_repo(repo, monkeypatch)
    else:
        monkeypatch.setattr(sys, "argv", ["admrules.fetch_cache", "--skip-quota-check"])
        fetch_cache.main()
        snapshot.reconcile_current_snapshot(repo, commit=True)

    selection = snapshot.load_current_snapshot()
    assert selection["rules"] == {"123": "1"}
    assert selection["excluded"] == [{"id": "456", "serial": "2", "reason": "live_detail_no_result"}]
    assert "456/2" in caplog.text
    assert cache.get_detail("2") == withdrawn
    files = list(repo.rglob("본문.md"))
    assert len(files) == 1 and "본문 1" in files[0].read_text()
    history = subprocess.check_output(["git", "-C", str(repo), "log", "--format=%B"], text=True)
    assert "행정규칙일련번호: 2" in history
    assert validate_current_snapshot(repo, cache.CACHE_DIR / snapshot.SNAPSHOT_NAME) == []

    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    repeated = snapshot.write_current_snapshot(rows, history_entries=[])
    assert repeated["rules"] == selection["rules"]
    assert repeated["excluded"] == selection["excluded"]
    assert snapshot.reconcile_current_snapshot(repo, commit=True)["snapshot_committed"] == 0
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == head
    assert cache.get_detail("2") == withdrawn

    monkeypatch.setattr(api_client, "_request", lambda *args: SimpleNamespace(content=withdrawn))
    recovered = snapshot.write_current_snapshot(rows, history_entries=[])
    assert recovered["rules"] == {"123": "1", "456": "2"}
    assert recovered["excluded"] == []
    snapshot.reconcile_current_snapshot(repo)
    assert len(list(repo.rglob("본문.md"))) == 2


def test_current_list_no_result_still_preserves_previous_snapshot(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from admrules import api_client
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1"))
    snapshot.write_current_snapshot([source_row("1")])
    path = cache.CACHE_DIR / snapshot.SNAPSHOT_NAME
    before = path.read_bytes()
    wrong_identity = detail("1").replace(b">123<", b">456<")
    cache.put_detail("1", wrong_identity)
    response = "<Law>일치하는 행정규칙이 없습니다.</Law>".encode()
    monkeypatch.setattr(api_client, "_request", lambda *args: SimpleNamespace(content=response))

    with pytest.raises(RuntimeError):
        snapshot.write_current_snapshot([source_row("1")])

    assert path.read_bytes() == before
    assert cache.get_detail("1") == wrong_identity


@pytest.mark.parametrize("corroborated", [False, True])
def test_missing_id_is_excluded_only_when_live_detail_has_a_supported_reassignment(tmp_path, monkeypatch, corroborated):
    from types import SimpleNamespace

    from admrules import api_client

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1"))
    cache.put_detail("2", detail("2").replace(b">123<", b">456<"))
    snapshot.write_current_snapshot([source_row("1"), source_row("2", 행정규칙ID="456")])
    manifest = cache.CACHE_DIR / snapshot.SNAPSHOT_NAME
    before = manifest.read_bytes()
    new_identity = b"123" if corroborated else b"789"
    live = detail("2", status="N").replace(b">123<", b">" + new_identity + b"<")
    monkeypatch.setattr(api_client, "_request", lambda *args: SimpleNamespace(content=live))
    if not corroborated:
        with pytest.raises(RuntimeError, match="Supplemental admrule identity mismatch"):
            snapshot.write_current_snapshot([source_row("1")], history_entries=[])
        assert manifest.read_bytes() == before
        return
    selection = snapshot.write_current_snapshot([source_row("1")], history_entries=[])
    assert selection["rules"] == {"123": "1"}
    assert selection["excluded"] == [{"id": "456", "serial": "2", "reason": "live_detail_identity_reassigned",
                                      "live_id": "123"}]
    assert cache.get_detail("2") == live


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


def test_full_git_rebuild_requires_selection_before_recording_history(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1", status="N"))
    repo = tmp_path / "rebuilt"
    with pytest.raises(RuntimeError, match="current_snapshot.json"):
        rebuild_repo(repo, monkeypatch)
    assert not list(repo.rglob("본문.md"))
    assert subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"], capture_output=True).returncode


def test_full_import_cli_refuses_existing_history(tmp_path, monkeypatch):
    import sys

    from admrules import rebuild

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.put_detail("1", detail("1"))
    snapshot.write_current_snapshot([source_row("1")])
    repo = tmp_path / "out"
    init_repo(repo)
    import_from_cache(repo, commit=True)
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    monkeypatch.setattr(sys, "argv", ["admrules.rebuild", "--repo", str(repo), "--commit"])
    with pytest.raises(SystemExit, match="2"):
        rebuild.main()
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == head
    assert not subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"])


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
    assert result == {"snapshot_written": 2, "snapshot_deleted": 2, "snapshot_committed": 1}
    assert subprocess.check_output(["git", "-C", str(repo), "log", "-1", "--format=%s"], text=True).strip() == "build(admrules): 현행 트리 생성"
    assert validate_current_snapshot(repo, cache.CACHE_DIR / snapshot.SNAPSHOT_NAME) == []
    assert snapshot.reconcile_current_snapshot(repo, commit=True)["snapshot_committed"] == 0


@pytest.mark.parametrize('stale_kind', ['name', 'body', 'empty'])
def test_daily_rechecks_changed_cached_y_against_live_detail(tmp_path, monkeypatch, stale_kind):
    from admrules import api_client
    from types import SimpleNamespace
    monkeypatch.setattr(cache, 'CACHE_DIR', tmp_path / 'cache')
    fresh = detail('1')
    cache.put_detail('1', fresh)
    snapshot.write_current_snapshot([source_row('1')])
    repo = tmp_path / 'repo'
    init_repo(repo)
    import_from_cache(repo, commit=True)
    before = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'])
    stale = fresh.replace('금융감독원 규정'.encode(), '오래된 규정'.encode()) if stale_kind == 'name' else fresh.replace('제1조 본문 1'.encode(), b'' if stale_kind == 'empty' else '오래된 본문'.encode())
    cache.put_detail('1', stale)
    monkeypatch.setattr(update, 'fetch_all_current', lambda **kw: [source_row('1')] if kw.get('history') is False else [])
    calls = []
    monkeypatch.setattr(api_client, '_request', lambda url, params: calls.append(params) or SimpleNamespace(content=fresh))
    result = update.run(repo=repo, commit=True, workers=1)
    assert len(calls) == 1
    assert cache.get_detail('1') == fresh
    assert result['committed'] == 0
    assert subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD']) == before


@pytest.mark.parametrize('failure', ['empty', 'network', 'wrong_identity'])
def test_daily_refetch_failure_preserves_published_tree_and_selection(tmp_path, monkeypatch, failure):
    from admrules import api_client
    from types import SimpleNamespace
    monkeypatch.setattr(cache, 'CACHE_DIR', tmp_path / 'cache')
    fresh = detail('1')
    cache.put_detail('1', fresh)
    snapshot.write_current_snapshot([source_row('1')])
    repo = tmp_path / 'repo'
    init_repo(repo)
    import_from_cache(repo, commit=True)
    before = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'])
    files = {str(p): p.read_bytes() for p in repo.rglob('본문.md')}
    selection = (cache.CACHE_DIR / snapshot.SNAPSHOT_NAME).read_bytes()
    cache.put_detail('1', fresh.replace('제1조 본문 1'.encode(), b''))
    monkeypatch.setattr(update, 'fetch_all_current', lambda **kw: [source_row('1')] if kw.get('history') is False else [])
    def request(url, params):
        if failure == 'network':
            raise RuntimeError('network unavailable')
        raw = fresh.replace('제1조 본문 1'.encode(), b'') if failure == 'empty' else fresh.replace('<행정규칙ID>123</행정규칙ID>'.encode(), b'')
        return SimpleNamespace(content=raw)
    monkeypatch.setattr(api_client, '_request', request)
    with pytest.raises(RuntimeError):
        update.run(repo=repo, commit=True, workers=1)
    assert subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD']) == before
    assert {str(p): p.read_bytes() for p in repo.rglob('본문.md')} == files
    assert (cache.CACHE_DIR / snapshot.SNAPSHOT_NAME).read_bytes() == selection


def test_live_same_serial_correction_requires_rebuild(tmp_path, monkeypatch):
    from admrules import api_client
    from types import SimpleNamespace
    monkeypatch.setattr(cache, 'CACHE_DIR', tmp_path / 'cache')
    old = detail('1')
    cache.put_detail('1', old)
    snapshot.write_current_snapshot([source_row('1')])
    repo = tmp_path / 'repo'
    init_repo(repo)
    import_from_cache(repo, commit=True)
    fresh = detail('1', name='정정된 규정').replace('본문 1'.encode(), '정정 본문'.encode())
    cache.put_detail('1', fresh)
    monkeypatch.setattr(update, 'fetch_all_current', lambda **kw: [source_row('1')] if kw.get('history') is False else [])
    calls = []
    monkeypatch.setattr(api_client, '_request', lambda url, params: calls.append(params) or SimpleNamespace(content=fresh))
    with pytest.raises(snapshot.RebuildRequired, match="rebuild required"):
        update.run(repo=repo, commit=True)
    assert '본문 1' in next(repo.rglob('본문.md')).read_text()
    repo = tmp_path / "rebuilt"
    rebuild_repo(repo, monkeypatch)
    assert '정정 본문' in next(repo.rglob('본문.md')).read_text()
    second = update.run(repo=repo, commit=True)
    assert second['committed'] == 0
    assert second['snapshot_refetched'] == 0 and len(calls) == 1


def test_required_body_is_checked_before_any_snapshot_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, 'CACHE_DIR', tmp_path / 'cache')
    cache.put_detail('1', detail('1'))
    snapshot.write_current_snapshot([source_row('1')])
    repo = tmp_path / 'repo'
    import_from_cache(repo)
    before = {str(p): p.read_bytes() for p in repo.rglob('본문.md')}
    cache.put_detail('1', detail('1', name='잘못된 새 경로').replace('제1조 본문 1'.encode(), b''))
    with pytest.raises(RuntimeError, match='body regression'):
        snapshot.reconcile_current_snapshot(repo)
    assert {str(p): p.read_bytes() for p in repo.rglob('본문.md')} == before
    # The publication validator also rejects a previously valid body lost later.
    path = next(repo.rglob('본문.md'))
    path.write_text(path.read_text().replace("본문출처: 'api-text'", "본문출처: 'parsing-failed'"))
    assert any('body regression' in error for error in validate_current_snapshot(repo, cache.CACHE_DIR / snapshot.SNAPSHOT_NAME))


def test_live_attachment_only_rule_preserves_original_file_links(tmp_path, monkeypatch):
    from admrules import api_client, converter
    from types import SimpleNamespace
    monkeypatch.setattr(cache, 'CACHE_DIR', tmp_path / 'cache')
    old = detail('1')
    cache.put_detail('1', old)
    snapshot.write_current_snapshot([source_row('1')])
    repo = tmp_path / 'repo'
    init_repo(repo)
    import_from_cache(repo, commit=True)
    fresh = old.replace('제1조 본문 1'.encode(), b'').replace(b'</AdmRulService>', '''<첨부파일>
<첨부파일명>원문.pdf</첨부파일명><첨부파일링크>http://law.go.kr/flDownload.do?flSeq=1</첨부파일링크>
<첨부파일명>원문.hwpx</첨부파일명><첨부파일링크>/LSW/flDownload.do?flSeq=2</첨부파일링크>
</첨부파일></AdmRulService>'''.encode())
    cache.put_detail('1', fresh)
    monkeypatch.setattr(update, 'fetch_all_current', lambda **kw: [source_row('1')] if kw.get('history') is False else [])
    monkeypatch.setattr(api_client, '_request', lambda url, params: SimpleNamespace(content=fresh))
    with pytest.raises(snapshot.RebuildRequired, match="rebuild required"):
        update.run(repo=repo, workers=1, commit=True)
    repo = tmp_path / "rebuilt"
    rebuild_repo(repo, monkeypatch)
    path = next(repo.rglob('본문.md'))
    text = path.read_text()
    assert "본문출처: 'attachment-only'" in text and 'parsing-failed' not in text
    assert '<http://law.go.kr/flDownload.do?flSeq=1>' in text
    assert '<https://www.law.go.kr/LSW/flDownload.do?flSeq=2>' in text
    assert converter.has_current_content(fresh)
    assert validate_frontmatter(path) == []
    assert validate_current_snapshot(repo, cache.CACHE_DIR / snapshot.SNAPSHOT_NAME) == []
