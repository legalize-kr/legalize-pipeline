"""Tests for ordinances/import_ordinances.py."""

from ordinances import import_ordinances
from .test_converter import SAMPLE_XML


def test_import_from_cache_writes_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(import_ordinances.cache, "list_cached_ids", lambda: ["2000111"])
    monkeypatch.setattr(import_ordinances.cache, "get_detail", lambda ordinance_id: SAMPLE_XML.encode("utf-8"))

    counters = import_ordinances.import_from_cache(tmp_path)

    assert counters["written"] == 1
    assert (tmp_path / "서울특별시/_본청/조례/서울특별시 테스트 조례/본문.md").exists()


def test_import_from_cache_commits_in_date_order(tmp_path, monkeypatch):
    old_xml = SAMPLE_XML.replace("<자치법규ID>2000111</자치법규ID>", "<자치법규ID>200</자치법규ID>").replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20200101</공포일자>",
    )
    new_xml = SAMPLE_XML.replace("<자치법규ID>2000111</자치법규ID>", "<자치법규ID>100</자치법규ID>").replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20210101</공포일자>",
    )
    details = {"100": new_xml.encode("utf-8"), "200": old_xml.encode("utf-8")}
    commits = []
    monkeypatch.setattr(import_ordinances.cache, "list_cached_ids", lambda: ["100", "200"])
    monkeypatch.setattr(import_ordinances.cache, "get_detail", lambda ordinance_id: details[ordinance_id])
    monkeypatch.setattr(
        import_ordinances,
        "commit_ordinance",
        lambda repo, path, msg, date, ordinance_id, **kwargs: commits.append(ordinance_id) or True,
    )

    counters = import_ordinances.import_from_cache(tmp_path, commit=True)

    assert counters["committed"] == 2
    assert commits == ["200", "100"]


def test_import_from_cache_removes_stale_path_when_ordinance_name_changes(tmp_path, monkeypatch):
    old_xml = SAMPLE_XML.replace("서울특별시 테스트 조례", "이전 조례").replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20240101</공포일자>",
    )
    new_xml = SAMPLE_XML.replace("서울특별시 테스트 조례", "새 조례").replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20240201</공포일자>",
    )
    details = {"old": old_xml.encode("utf-8"), "new": new_xml.encode("utf-8")}
    monkeypatch.setattr(import_ordinances.cache, "list_cached_ids", lambda: ["new", "old"])
    monkeypatch.setattr(import_ordinances.cache, "get_detail", lambda ordinance_id: details[ordinance_id])

    counters = import_ordinances.import_from_cache(tmp_path)

    assert counters["written"] == 2
    assert (tmp_path / "서울특별시/_본청/조례/새 조례/본문.md").exists()
    assert not (tmp_path / "서울특별시/_본청/조례/이전 조례/본문.md").exists()


def test_import_from_cache_commits_stale_path_deletion(tmp_path, monkeypatch):
    old_xml = SAMPLE_XML.replace("서울특별시 테스트 조례", "이전 조례").replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20240101</공포일자>",
    )
    new_xml = SAMPLE_XML.replace("서울특별시 테스트 조례", "새 조례").replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20240201</공포일자>",
    )
    details = {"old": old_xml.encode("utf-8"), "new": new_xml.encode("utf-8")}
    commits = []
    monkeypatch.setattr(import_ordinances.cache, "list_cached_ids", lambda: ["old", "new"])
    monkeypatch.setattr(import_ordinances.cache, "get_detail", lambda ordinance_id: details[ordinance_id])
    monkeypatch.setattr(
        import_ordinances,
        "commit_ordinance",
        lambda repo, path, msg, date, ordinance_id, **kwargs: commits.append(
            (path, kwargs.get("stale_paths", []))
        )
        or True,
    )

    counters = import_ordinances.import_from_cache(tmp_path, commit=True)

    assert counters["committed"] == 2
    assert commits[-1] == (
        "서울특별시/_본청/조례/새 조례/본문.md",
        ["서울특별시/_본청/조례/이전 조례/본문.md"],
    )
