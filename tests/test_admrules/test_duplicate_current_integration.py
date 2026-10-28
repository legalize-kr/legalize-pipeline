"""Replay the duplicate source identity through both daily entrypoints."""

import json
import subprocess
import sys
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from requests.exceptions import Timeout

from admrules import api_client, cache, checkpoint, fetch_cache, snapshot, update
from admrules.import_admrules import metadata_from_raw
from admrules.validate import validate_current_snapshot, validate_frontmatter


@pytest.fixture
def duplicate_source(tmp_path, monkeypatch, fixtures_dir):
    source = fixtures_dir / "admrule_duplicate_current_2088530"
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(checkpoint, "CHECKPOINT_FILE", tmp_path / "checkpoint.json")
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    monkeypatch.setattr(update, "_date_range", lambda days: "20261014~20261028")
    requests = []

    def request(url, params):
        requests.append(dict(params))
        if url.endswith("/lawSearch.do"):
            assert params["page"] == "1"
            return SimpleNamespace(content=(source / "search.xml").read_bytes())
        assert url.endswith("/lawService.do")
        return SimpleNamespace(content=(source / f"{params['ID']}.xml").read_bytes())

    monkeypatch.setattr(api_client, "_request", request)
    # A previously current cached revision must not win over fresh details.
    raw = (source / "2100000254642.xml").read_bytes()
    cache.put_detail("2100000254642", raw.replace("<현행여부>N".encode(), "<현행여부>Y".encode()))
    return source, requests


@pytest.mark.parametrize("entrypoint", ["fetch_cache", "update"])
@pytest.mark.parametrize("current_serial", ["2100000286966", "2100000241092"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("warm_cache", [False, True])
def test_duplicate_current_source_through_daily_entrypoints(tmp_path, monkeypatch, duplicate_source, entrypoint, current_serial, reverse, warm_cache):
    source, requests = duplicate_source
    request = api_client._request

    def reordered(url, params):
        response = request(url, params)
        root = ElementTree.fromstring(response.content)
        if "ID" in params:
            root.find(".//현행여부").text = "Y" if params["ID"] == current_serial else "N"
        elif reverse:
            rows = root.findall("admrul")
            for row in rows:
                root.remove(row)
            root.extend(reversed(rows))
        return SimpleNamespace(content=ElementTree.tostring(root, encoding="utf-8"))

    monkeypatch.setattr(api_client, "_request", reordered)
    if warm_cache:
        for detail in source.glob("[0-9]*.xml"):
            cache.put_detail(detail.stem, detail.read_bytes().replace("<현행여부>N".encode(), "<현행여부>Y".encode()))
    repo = tmp_path / "repo"
    if entrypoint == "fetch_cache":
        monkeypatch.setattr(sys, "argv", ["admrules.fetch_cache", "--skip-quota-check", "--workers", "1"])
        fetch_cache.main()
    else:
        subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
        monkeypatch.setattr(sys, "argv", ["admrules.update", "--repo", str(repo), "--workers", "1", "--days", "14", "--commit"])
        update.main()

    selection = snapshot.load_current_snapshot()
    assert selection["rules"] == {"2088530": current_serial}
    assert selection["conflicts"][0]["reason"] == "duplicate_current_list_identity"
    serials = {path.stem for path in source.glob("[0-9]*.xml")}
    assert set(cache.list_cached_serials()) == serials
    # Every candidate, including the stale Y cache entry, needs a live probe.
    assert serials <= {params["ID"] for params in requests if "ID" in params}
    assert metadata_from_raw(cache.get_detail("2100000254642"))["현행여부"] == "N"
    if entrypoint == "update":
        files = list(repo.rglob("본문.md"))
        assert len(files) == 1
        assert validate_frontmatter(files[0]) == []
        assert validate_current_snapshot(repo, cache.CACHE_DIR / snapshot.SNAPSHOT_NAME) == []
        assert current_serial in files[0].read_text()
        log = subprocess.check_output(["git", "-C", str(repo), "log", "--format=%B"], text=True)
        assert all(f"행정규칙일련번호: {serial}" in log for serial in serials)
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    request_count = len(requests)
    if entrypoint == "update":
        update.main()
        assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == head
    else:
        fetch_cache.main()
    assert snapshot.load_current_snapshot()["rules"] == {"2088530": current_serial}
    assert set(cache.list_cached_serials()) == serials
    assert serials <= {params["ID"] for params in requests[request_count:] if "ID" in params}


@pytest.mark.parametrize("entrypoint", ["fetch_cache", "update"])
@pytest.mark.parametrize("failure,error,message", [
    ("no_current", RuntimeError, "Ambiguous current admrule identity"),
    ("multiple_current", RuntimeError, "Ambiguous current admrule identity"),
    ("missing_status", RuntimeError, "Unknown current admrule status"),
    ("wrong_identity", RuntimeError, "Current admrule identity mismatch"),
    ("wrong_serial", RuntimeError, "detail serial mismatch"),
    ("no_result", RuntimeError, "no admrule detail"),
    ("api_error", RuntimeError, "API error"),
    ("network_error", Timeout, "read timed out"),
    ("malformed_xml", ElementTree.ParseError, "no element found"),
    ("html_error", RuntimeError, "unexpected admrule detail root"),
    ("body_loss", RuntimeError, "Current admrule body regression"),
])
def test_unresolved_duplicates_preserve_snapshot_and_tree(tmp_path, monkeypatch, duplicate_source, entrypoint, failure, error, message):
    source, requests = duplicate_source
    serial = "2100000286966"
    # Force errors to occur during fresh duplicate probes, after detail fetching.
    for detail in source.glob("[0-9]*.xml"):
        cache.put_detail(detail.stem, detail.read_bytes().replace("<현행여부>N".encode(), "<현행여부>Y".encode()))
    original = {"schema_version": 1, "observed_on": "2026-10-27", "rules": {"2088530": serial}, "required_body_ids": ["2088530"]}
    path = cache.CACHE_DIR / snapshot.SNAPSHOT_NAME
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    sentinel = repo / "existing.md"
    sentinel.write_text("Existing published data\n")
    subprocess.run(["git", "-C", str(repo), "add", "existing.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "baseline"], check=True, capture_output=True)
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    request = api_client._request
    rows = ElementTree.parse(source / "search.xml").getroot().findall("admrul")
    last_serial = rows[-1].findtext("행정규칙일련번호")

    def broken(url, params):
        response = request(url, params)
        if "ID" not in params:
            return response
        if failure not in {"no_current", "multiple_current"} and params["ID"] != (serial if failure == "body_loss" else last_serial):
            return response
        root = ElementTree.fromstring(response.content)
        if failure == "no_current":
            root.find(".//현행여부").text = "N"
        elif failure == "multiple_current":
            root.find(".//현행여부").text = "Y"
        elif failure == "missing_status":
            root.find(".//현행여부").text = ""
        elif failure == "wrong_identity":
            root.find(".//행정규칙ID").text = "OTHER"
        elif failure == "wrong_serial":
            root.find(".//행정규칙일련번호").text = "999"
        elif failure == "no_result":
            return SimpleNamespace(content="<Law>일치하는 행정규칙이 없습니다</Law>".encode())
        elif failure == "api_error":
            return SimpleNamespace(content="<Law><result>실패</result><msg>서버 오류</msg></Law>".encode())
        elif failure == "network_error":
            raise Timeout("read timed out")
        elif failure == "malformed_xml":
            return SimpleNamespace(content=b"<AdmRulService>")
        elif failure == "html_error":
            return SimpleNamespace(content=b"<html/>")
        elif failure == "body_loss":
            for parent in root.iter():
                for child in list(parent):
                    if child.tag in {"조문내용", "첨부파일"}:
                        parent.remove(child)
        return SimpleNamespace(content=ElementTree.tostring(root, encoding="utf-8"))

    monkeypatch.setattr(api_client, "_request", broken)
    if entrypoint == "fetch_cache":
        monkeypatch.setattr(sys, "argv", ["admrules.fetch_cache", "--skip-quota-check", "--workers", "1"])
        run = fetch_cache.main
    else:
        monkeypatch.setattr(sys, "argv", ["admrules.update", "--repo", str(repo), "--workers", "1", "--commit"])
        run = update.main
    with pytest.raises(error, match=message):
        run()
    assert path.read_bytes() == before
    assert last_serial in {params["ID"] for params in requests if "ID" in params} or failure == "body_loss"
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == head
    assert subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"]) == b""
    assert sentinel.read_text() == "Existing published data\n"
    assert not (cache.CACHE_DIR / "retired").exists()
    # The next scheduled run must recover after the source failure stops.
    monkeypatch.setattr(api_client, "_request", request)
    run()
    assert snapshot.load_current_snapshot()["rules"] == {"2088530": serial}
    if entrypoint == "update":
        assert validate_current_snapshot(repo, path) == []
