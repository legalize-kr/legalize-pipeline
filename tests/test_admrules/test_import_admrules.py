"""Tests for admrules/import_admrules.py."""

from admrules import import_admrules


def test_import_from_cache_writes_markdown(tmp_path, monkeypatch):
    xml = """
    <AdmRulService>
      <행정규칙일련번호>123</행정규칙일련번호>
      <행정규칙명>공공데이터 관리지침</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240504</발령일자>
      <조문내용>제1조 목적</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    monkeypatch.setattr(import_admrules.cache, "list_cached_serials", lambda: ["123"])
    monkeypatch.setattr(import_admrules.cache, "get_detail", lambda serial: xml)

    counters = import_admrules.import_from_cache(tmp_path)

    assert counters["written"] == 1
    assert (tmp_path / "행정안전부/_본부/고시/공공데이터 관리지침/본문.md").exists()


def test_import_from_cache_commits_in_date_order(tmp_path, monkeypatch):
    old_xml = """
    <AdmRulService>
      <행정규칙일련번호>200</행정규칙일련번호>
      <행정규칙명>옛 행정규칙</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20200101</발령일자>
      <조문내용>옛 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    new_xml = """
    <AdmRulService>
      <행정규칙일련번호>100</행정규칙일련번호>
      <행정규칙명>새 행정규칙</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20210101</발령일자>
      <조문내용>새 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    details = {"100": new_xml, "200": old_xml}
    commits = []
    monkeypatch.setattr(import_admrules.cache, "list_cached_serials", lambda: ["100", "200"])
    monkeypatch.setattr(import_admrules.cache, "get_detail", lambda serial: details[serial])
    monkeypatch.setattr(
        import_admrules,
        "commit_admrule",
        lambda repo, path, msg, date, serial, **kwargs: commits.append(serial) or True,
    )

    counters = import_admrules.import_from_cache(tmp_path, commit=True)

    assert counters["committed"] == 2
    assert commits == ["200", "100"]


def test_import_from_cache_removes_stale_path_when_rule_name_changes(tmp_path, monkeypatch):
    old_xml = """
    <AdmRulService>
      <행정규칙일련번호>123</행정규칙일련번호>
      <행정규칙명>이전 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240101</발령일자>
      <조문내용>이전 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    new_xml = """
    <AdmRulService>
      <행정규칙일련번호>123</행정규칙일련번호>
      <행정규칙명>새 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240201</발령일자>
      <조문내용>새 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    details = {"old": old_xml, "new": new_xml}
    monkeypatch.setattr(import_admrules.cache, "list_cached_serials", lambda: ["new", "old"])
    monkeypatch.setattr(import_admrules.cache, "get_detail", lambda serial: details[serial])

    counters = import_admrules.import_from_cache(tmp_path)

    assert counters["written"] == 2
    assert (tmp_path / "행정안전부/_본부/고시/새 고시/본문.md").exists()
    assert not (tmp_path / "행정안전부/_본부/고시/이전 고시/본문.md").exists()


def test_import_from_cache_tracks_name_changes_by_rule_id(tmp_path, monkeypatch):
    old_xml = """
    <AdmRulService>
      <행정규칙ID>92956</행정규칙ID>
      <행정규칙일련번호>111</행정규칙일련번호>
      <행정규칙명>이전 소방 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>소방청</소관부처명>
      <발령일자>20240101</발령일자>
      <조문내용>이전 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    new_xml = """
    <AdmRulService>
      <행정규칙ID>92956</행정규칙ID>
      <행정규칙일련번호>222</행정규칙일련번호>
      <행정규칙명>새 소방 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>소방청</소관부처명>
      <발령일자>20240201</발령일자>
      <조문내용>새 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    details = {"old": old_xml, "new": new_xml}
    monkeypatch.setattr(import_admrules.cache, "list_cached_serials", lambda: ["new", "old"])
    monkeypatch.setattr(import_admrules.cache, "get_detail", lambda serial: details[serial])

    counters = import_admrules.import_from_cache(tmp_path)

    assert counters["written"] == 2
    assert (tmp_path / "행정안전부/소방청/고시/새 소방 고시/본문.md").exists()
    assert not (tmp_path / "행정안전부/소방청/고시/이전 소방 고시/본문.md").exists()


def test_import_from_cache_deletes_repealed_rule_from_head(tmp_path, monkeypatch):
    active_xml = """
    <AdmRulService>
      <행정규칙ID>92956</행정규칙ID>
      <행정규칙일련번호>111</행정규칙일련번호>
      <행정규칙명>소방 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>소방청</소관부처명>
      <발령일자>20240101</발령일자>
      <조문내용>본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    repeal_xml = """
    <AdmRulService>
      <행정규칙ID>92956</행정규칙ID>
      <행정규칙일련번호>222</행정규칙일련번호>
      <행정규칙명>소방 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>소방청</소관부처명>
      <발령일자>20240201</발령일자>
      <제개정구분명>폐지</제개정구분명>
      <조문내용>폐지</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    details = {"active": active_xml, "repeal": repeal_xml}
    monkeypatch.setattr(import_admrules.cache, "list_cached_serials", lambda: ["repeal", "active"])
    monkeypatch.setattr(import_admrules.cache, "get_detail", lambda serial: details[serial])

    counters = import_admrules.import_from_cache(tmp_path)

    assert counters["written"] == 1
    assert counters["deleted"] == 1
    assert not (tmp_path / "행정안전부/소방청/고시/소방 고시/본문.md").exists()


def test_import_from_cache_keeps_rule_when_non_current_revision_is_not_latest(tmp_path, monkeypatch):
    old_xml = """
    <AdmRulService>
      <행정규칙ID>ABC</행정규칙ID>
      <행정규칙일련번호>111</행정규칙일련번호>
      <행정규칙명>현행 복귀 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240101</발령일자>
      <현행여부>N</현행여부>
      <조문내용>중간 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    latest_xml = """
    <AdmRulService>
      <행정규칙ID>ABC</행정규칙ID>
      <행정규칙일련번호>222</행정규칙일련번호>
      <행정규칙명>현행 복귀 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240201</발령일자>
      <현행여부>Y</현행여부>
      <조문내용>최신 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    details = {"old": old_xml, "latest": latest_xml}
    monkeypatch.setattr(import_admrules.cache, "list_cached_serials", lambda: ["latest", "old"])
    monkeypatch.setattr(import_admrules.cache, "get_detail", lambda serial: details[serial])

    counters = import_admrules.import_from_cache(tmp_path)

    path = tmp_path / "행정안전부/_본부/고시/현행 복귀 고시/본문.md"
    assert counters["written"] == 2
    assert counters["deleted"] == 0
    assert path.exists()
    assert "최신 본문" in path.read_text()


def test_import_from_cache_deletes_rule_when_latest_revision_is_non_current(tmp_path, monkeypatch):
    active_xml = """
    <AdmRulService>
      <행정규칙ID>ABC</행정규칙ID>
      <행정규칙일련번호>111</행정규칙일련번호>
      <행정규칙명>비현행 전환 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240101</발령일자>
      <현행여부>Y</현행여부>
      <조문내용>현행 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    non_current_xml = """
    <AdmRulService>
      <행정규칙ID>ABC</행정규칙ID>
      <행정규칙일련번호>222</행정규칙일련번호>
      <행정규칙명>비현행 전환 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240201</발령일자>
      <현행여부>N</현행여부>
      <조문내용>비현행 마지막 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    details = {"active": active_xml, "non_current": non_current_xml}
    monkeypatch.setattr(import_admrules.cache, "list_cached_serials", lambda: ["non_current", "active"])
    monkeypatch.setattr(import_admrules.cache, "get_detail", lambda serial: details[serial])

    counters = import_admrules.import_from_cache(tmp_path)

    assert counters["written"] == 2
    assert counters["deleted"] == 1
    assert not (tmp_path / "행정안전부/_본부/고시/비현행 전환 고시/본문.md").exists()


def test_import_from_cache_commits_non_current_final_state_deletion(tmp_path, monkeypatch):
    active_xml = """
    <AdmRulService>
      <행정규칙ID>ABC</행정규칙ID>
      <행정규칙일련번호>111</행정규칙일련번호>
      <행정규칙명>비현행 전환 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240101</발령일자>
      <현행여부>Y</현행여부>
      <조문내용>현행 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    non_current_xml = """
    <AdmRulService>
      <행정규칙ID>ABC</행정규칙ID>
      <행정규칙일련번호>222</행정규칙일련번호>
      <행정규칙명>비현행 전환 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240201</발령일자>
      <현행여부>N</현행여부>
      <조문내용>비현행 마지막 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    details = {"active": active_xml, "non_current": non_current_xml}
    commits = []
    monkeypatch.setattr(import_admrules.cache, "list_cached_serials", lambda: ["non_current", "active"])
    monkeypatch.setattr(import_admrules.cache, "get_detail", lambda serial: details[serial])
    monkeypatch.setattr(
        import_admrules,
        "commit_admrule",
        lambda repo, path, msg, date, serial, **kwargs: commits.append(("write", path, msg, serial, kwargs)) or True,
    )
    monkeypatch.setattr(
        import_admrules,
        "commit_admrule_deletion",
        lambda repo, path, msg, date, serial, **kwargs: commits.append(("delete", path, msg, serial, kwargs)) or True,
    )

    counters = import_admrules.import_from_cache(tmp_path, commit=True)

    assert counters["committed"] == 3
    assert [commit[0] for commit in commits] == ["write", "write", "delete"]
    delete_commit = commits[-1]
    assert delete_commit[1] == "행정안전부/_본부/고시/비현행 전환 고시/본문.md"
    assert "비현행 제외: 비현행 전환 고시" in delete_commit[2]
    assert delete_commit[4]["dedup_grep_key"] == "비현행 제외 행정규칙일련번호: 222"


def test_import_from_cache_commits_stale_path_deletion(tmp_path, monkeypatch):
    old_xml = """
    <AdmRulService>
      <행정규칙일련번호>123</행정규칙일련번호>
      <행정규칙명>이전 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240101</발령일자>
      <조문내용>이전 본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    new_xml = old_xml.replace("이전 고시".encode(), "새 고시".encode()).replace(
        "20240101".encode(),
        "20240201".encode(),
    )
    details = {"old": old_xml, "new": new_xml}
    commits = []
    monkeypatch.setattr(import_admrules.cache, "list_cached_serials", lambda: ["old", "new"])
    monkeypatch.setattr(import_admrules.cache, "get_detail", lambda serial: details[serial])
    monkeypatch.setattr(
        import_admrules,
        "commit_admrule",
        lambda repo, path, msg, date, serial, **kwargs: commits.append((path, kwargs.get("stale_paths", []))) or True,
    )

    counters = import_admrules.import_from_cache(tmp_path, commit=True)

    assert counters["committed"] == 2
    assert commits[-1] == (
        "행정안전부/_본부/고시/새 고시/본문.md",
        ["행정안전부/_본부/고시/이전 고시/본문.md"],
    )


def test_import_from_cache_commits_repeal_deletion(tmp_path, monkeypatch):
    active_xml = """
    <AdmRulService>
      <행정규칙ID>92956</행정규칙ID>
      <행정규칙일련번호>111</행정규칙일련번호>
      <행정규칙명>소방 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>소방청</소관부처명>
      <발령일자>20240101</발령일자>
      <조문내용>본문</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    repeal_xml = """
    <AdmRulService>
      <행정규칙ID>92956</행정규칙ID>
      <행정규칙일련번호>222</행정규칙일련번호>
      <행정규칙명>소방 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>소방청</소관부처명>
      <발령일자>20240201</발령일자>
      <제개정구분명>폐지</제개정구분명>
      <조문내용>폐지</조문내용>
    </AdmRulService>
    """.encode("utf-8")
    details = {"active": active_xml, "repeal": repeal_xml}
    deleted = []
    monkeypatch.setattr(import_admrules.cache, "list_cached_serials", lambda: ["repeal", "active"])
    monkeypatch.setattr(import_admrules.cache, "get_detail", lambda serial: details[serial])
    monkeypatch.setattr(import_admrules, "commit_admrule", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        import_admrules,
        "commit_admrule_deletion",
        lambda repo, path, msg, date, serial, **kwargs: deleted.append((path, serial)) or True,
    )

    counters = import_admrules.import_from_cache(tmp_path, commit=True)

    assert counters["committed"] == 2
    assert deleted == [("행정안전부/소방청/고시/소방 고시/본문.md", "repeal")]
