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
