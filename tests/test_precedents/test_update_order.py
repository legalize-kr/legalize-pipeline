"""Tests for deterministic precedent update ordering."""

import subprocess
from pathlib import Path

import pytest

import precedents.update as update_mod


def _valid_prec_xml(serial: str, case_no: str = "2024다1") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PrecService>
  <판례정보일련번호>{serial}</판례정보일련번호>
  <사건명>테스트</사건명>
  <사건번호>{case_no}</사건번호>
  <선고일자>20240101</선고일자>
  <법원명>대법원</법원명>
  <법원종류코드>400201</법원종류코드>
  <사건종류명>민사</사건종류명>
  <판례내용>본문</판례내용>
</PrecService>
""".encode("utf-8")


def test_collect_recent_ids_sorts_by_date_and_serial(monkeypatch):
    responses = {
        1: {
            "totalCnt": 3,
            "precedents": [
                {"판례일련번호": "30", "선고일자": "20240102"},
                {"판례일련번호": "9", "선고일자": "20240101"},
                {"판례일련번호": "20", "선고일자": "20240101"},
            ],
        },
    }

    def search_stub(*, query, page, display, sort, date_range):
        return responses[page]

    monkeypatch.setattr(update_mod, "search_precedents", search_stub)

    recent = update_mod._collect_recent_ids(days=1)

    assert [item["판례일련번호"] for item in recent] == ["20", "9", "30"]


def test_collect_id_window_ids_uses_overlap_and_probe_horizon(monkeypatch, tmp_path):
    monkeypatch.setattr(update_mod, "_max_committed_precedent_id", lambda output_dir: 100)

    candidates = update_mod._collect_id_window_ids(
        tmp_path,
        overlap=2,
        probe_horizon=3,
    )

    assert [item["판례일련번호"] for item in candidates] == [
        "98",
        "99",
        "100",
        "101",
        "102",
        "103",
    ]
    assert {item["_source"] for item in candidates} == {"id_window"}


def test_max_committed_precedent_id_reads_frontmatter_without_git(tmp_path):
    first = tmp_path / "민사" / "first.md"
    second = tmp_path / "형사" / "second.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("---\n판례일련번호: '100'\n---\n", encoding="utf-8")
    second.write_text("---\n판례일련번호: '200'\n---\n", encoding="utf-8")

    assert update_mod._max_committed_precedent_id(tmp_path) == 200


def test_collect_id_window_ids_rejects_negative_window(tmp_path):
    with pytest.raises(ValueError):
        update_mod._collect_id_window_ids(tmp_path, overlap=-1, probe_horizon=0)


def test_merge_candidates_dedupes_and_preserves_sources():
    merged = update_mod._merge_candidates(
        [{"판례일련번호": "100", "선고일자": "20240101", "_source": "date"}],
        [
            {"판례일련번호": "99", "_source": "id_window"},
            {"판례일련번호": "100", "_source": "id_window"},
        ],
    )

    by_id = {item["판례일련번호"]: item for item in merged}
    assert set(by_id) == {"99", "100"}
    assert by_id["100"]["_source"] == "date,id_window"


def test_resolve_output_path_adds_serial_suffix_for_existing_different_serial(tmp_path):
    existing = tmp_path / "민사" / "대법원" / "대법원_2024-01-01_2024다1.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("---\n판례일련번호: '100'\n---\n", encoding="utf-8")

    resolved = update_mod._resolve_output_path(
        "민사/대법원/대법원_2024-01-01_2024다1.md",
        {"판례정보일련번호": "200"},
        tmp_path,
    )

    assert resolved == "민사/대법원/대법원_2024-01-01_2024다1_200.md"


def test_run_uses_id_window_without_persisting_probe_no_result(monkeypatch, tmp_path):
    added_no_result: list[str] = []
    committed: list[tuple[str, bool]] = []

    monkeypatch.setattr(update_mod, "_collect_recent_ids", lambda days: [])
    monkeypatch.setattr(
        update_mod,
        "_collect_id_window_ids",
        lambda output_dir, *, overlap, probe_horizon: [
            {"판례일련번호": "101", "_source": "id_window"},
            {"판례일련번호": "102", "_source": "id_window"},
        ],
    )
    monkeypatch.setattr(update_mod.cache, "load_no_result_ids", lambda: set())
    monkeypatch.setattr(
        update_mod.cache,
        "add_no_result_id",
        lambda prec_id: added_no_result.append(prec_id),
    )

    def detail_stub(prec_id, *, refresh=False):
        assert refresh is False
        if prec_id == "101":
            return _valid_prec_xml("101")
        raise update_mod.NoResultError(prec_id, "missing")

    def commit_stub(path, parsed, *, cwd, skip_dedup=False):
        committed.append((path, skip_dedup))
        return "abc123"

    monkeypatch.setattr(update_mod, "get_precedent_detail", detail_stub)
    monkeypatch.setattr(update_mod, "commit_precedent", commit_stub)

    stats = update_mod.run(
        days=180,
        output_dir=tmp_path,
        id_overlap=1,
        id_probe_horizon=1,
    )

    assert stats["found"] == 2
    assert stats["date_found"] == 0
    assert stats["id_window_found"] == 2
    assert stats["committed"] == 1
    assert stats["no_result"] == 1
    assert added_no_result == []
    assert committed == [("민사/대법원/대법원_2024-01-01_2024다1.md", True)]


def test_run_records_date_search_no_result(monkeypatch, tmp_path):
    added_no_result: list[str] = []

    monkeypatch.setattr(
        update_mod,
        "_collect_recent_ids",
        lambda days: [{"판례일련번호": "101", "선고일자": "20240101", "_source": "date"}],
    )
    monkeypatch.setattr(update_mod, "_collect_id_window_ids", lambda *args, **kwargs: [])
    monkeypatch.setattr(update_mod.cache, "load_no_result_ids", lambda: set())
    monkeypatch.setattr(
        update_mod.cache,
        "add_no_result_id",
        lambda prec_id: added_no_result.append(prec_id),
    )

    def detail_stub(prec_id, *, refresh=False):
        raise update_mod.NoResultError(prec_id, "missing")

    monkeypatch.setattr(update_mod, "get_precedent_detail", detail_stub)

    stats = update_mod.run(days=180, output_dir=tmp_path)

    assert stats["no_result"] == 1
    assert added_no_result == ["101"]


def test_run_refreshes_recent_candidates_and_allows_update_commits(monkeypatch, tmp_path):
    calls: list[tuple[str, bool]] = []
    committed: list[bool] = []

    monkeypatch.setattr(
        update_mod,
        "_collect_recent_ids",
        lambda days: [{"판례일련번호": "101", "선고일자": "20240101", "_source": "date"}],
    )
    monkeypatch.setattr(update_mod, "_collect_id_window_ids", lambda *args, **kwargs: [])
    monkeypatch.setattr(update_mod.cache, "load_no_result_ids", lambda: set())

    def detail_stub(prec_id, *, refresh=False):
        calls.append((prec_id, refresh))
        return _valid_prec_xml("101")

    def commit_stub(path, parsed, *, cwd, skip_dedup=False):
        committed.append(skip_dedup)
        return "abc123"

    monkeypatch.setattr(update_mod, "get_precedent_detail", detail_stub)
    monkeypatch.setattr(update_mod, "commit_precedent", commit_stub)

    stats = update_mod.run(days=180, output_dir=tmp_path, refresh_recent=True)

    assert stats["committed"] == 1
    assert calls == [("101", True)]
    assert committed == [True]

def test_import_dedup_uses_exact_serial_on_current_branch(tmp_path):
    from precedents.git_engine import commit_precedent

    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("commit", "--allow-empty", "-m", "published", "-m", "판례일련번호: 1230")
    git("switch", "-c", "archive")
    git("commit", "--allow-empty", "-m", "archived", "-m", "판례일련번호: 123")
    git("switch", "main")
    (tmp_path / "case.md").write_text("decision")
    parsed = {"판례정보일련번호": "123", "선고일자": "20240101"}
    assert commit_precedent("case.md", parsed, cwd=tmp_path)
    assert commit_precedent("case.md", parsed, cwd=tmp_path) is None
