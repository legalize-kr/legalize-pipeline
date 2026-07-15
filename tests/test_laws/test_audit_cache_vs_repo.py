"""Tests for laws/audit_cache_vs_repo.py."""

import json
from pathlib import Path

from laws.audit_cache_vs_repo import (
    AuditReport,
    MissingContent,
    PathDrift,
    audit,
    failure_reasons,
    load_path_drift_allowlist,
)


def _write_history(cache_dir: Path, name: str, entries: list[dict]) -> None:
    path = cache_dir / "history" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


def _write_detail(
    cache_dir: Path,
    mst: str,
    *,
    name: str,
    law_id: str,
    law_type: str = "법률",
    prom_date: str = "20240101",
    prom_num: str = "1",
) -> None:
    path = cache_dir / "detail" / f"{mst}.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "<법령>",
                f"  <법령명_한글>{name}</법령명_한글>",
                f"  <법령ID>{law_id}</법령ID>",
                f"  <법종구분>{law_type}</법종구분>",
                f"  <공포일자>{prom_date}</공포일자>",
                f"  <공포번호>{prom_num}</공포번호>",
                f"  <시행일자>{prom_date}</시행일자>",
                "</법령>",
            ]
        ),
        encoding="utf-8",
    )


def _write_repo_markdown(
    repo_dir: Path,
    rel_path: str,
    *,
    title: str,
    law_id: str,
    mst: str,
    law_type: str = "법률",
    body_lines: list[str] | None = None,
) -> None:
    path = repo_dir / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f"제목: {title}",
                f"법령MST: {mst}",
                f"법령ID: '{law_id}'",
                f"법령구분: {law_type}",
                "---",
                "",
                f"# {title}",
                "",
                *(body_lines if body_lines is not None else [
                    "##### 제1조 (목적)",
                    "",
                    "이 법은 경로 drift 검증을 위한 본문이다.",
                ]),
            ]
        ),
        encoding="utf-8",
    )


def test_audit_classifies_same_law_id_at_old_path_as_path_drift(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"

    _write_history(
        cache_dir,
        "테스트현재법",
        [
            {"법령일련번호": "1", "제개정구분명": "제정"},
            {"법령일련번호": "2", "제개정구분명": "전부개정"},
        ],
    )
    _write_detail(cache_dir, "1", name="테스트이전법", law_id="000001", prom_date="20200101")
    _write_detail(cache_dir, "2", name="테스트현재법", law_id="000001", prom_date="20210101")
    _write_repo_markdown(
        repo_dir,
        "kr/테스트이전법/법률.md",
        title="테스트현재법",
        law_id="000001",
        mst="2",
    )

    report = audit(cache_dir=cache_dir, repo_dir=repo_dir)

    assert len(report.path_drift) == 1
    assert report.path_drift[0].expected_path == "kr/테스트현재법/법률.md"
    assert report.path_drift[0].actual_paths == ["kr/테스트이전법/법률.md"]
    assert report.missing_content == []


def test_audit_assigns_colliding_paths_by_first_lineage_order(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"

    _write_history(
        cache_dir,
        "충돌법",
        [
            {"법령일련번호": "1", "제개정구분명": "제정"},
            {"법령일련번호": "2", "제개정구분명": "제정"},
            {"법령일련번호": "3", "제개정구분명": "일부개정"},
        ],
    )
    _write_detail(cache_dir, "1", name="충돌법", law_id="A", prom_date="20200101")
    _write_detail(cache_dir, "2", name="충돌법", law_id="B", prom_date="20210101")
    _write_detail(cache_dir, "3", name="충돌법", law_id="A", prom_date="20250101")
    _write_repo_markdown(
        repo_dir,
        "kr/충돌법/법률.md",
        title="충돌법",
        law_id="A",
        mst="3",
    )
    _write_repo_markdown(
        repo_dir,
        "kr/충돌법/법률(법률).md",
        title="충돌법",
        law_id="B",
        mst="2",
    )

    report = audit(cache_dir=cache_dir, repo_dir=repo_dir)

    assert report.path_drift == []
    assert report.missing_content == []


def test_audit_reports_missing_content_when_same_law_id_is_absent(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"

    _write_history(cache_dir, "본문누락법", [{"법령일련번호": "10", "제개정구분명": "제정"}])
    _write_detail(cache_dir, "10", name="본문누락법", law_id="000010")

    report = audit(cache_dir=cache_dir, repo_dir=repo_dir)

    assert report.path_drift == []
    assert len(report.missing_content) == 1
    assert report.missing_content[0].expected_path == "kr/본문누락법/법률.md"


def test_audit_reports_empty_expected_file_as_missing_content(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"

    _write_history(cache_dir, "본문빈법", [{"법령일련번호": "11", "제개정구분명": "제정"}])
    _write_detail(cache_dir, "11", name="본문빈법", law_id="000011")
    _write_repo_markdown(
        repo_dir,
        "kr/본문빈법/법률.md",
        title="본문빈법",
        law_id="000011",
        mst="11",
        body_lines=[],
    )

    report = audit(cache_dir=cache_dir, repo_dir=repo_dir)

    assert report.path_drift == []
    assert len(report.missing_content) == 1
    assert report.missing_content[0].expected_path == "kr/본문빈법/법률.md"


def test_audit_accepts_short_full_text_without_article_heading(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"

    _write_history(cache_dir, "전문법", [{"법령일련번호": "12", "제개정구분명": "제정"}])
    _write_detail(cache_dir, "12", name="전문법", law_id="000012")
    _write_repo_markdown(
        repo_dir,
        "kr/전문법/법률.md",
        title="전문법",
        law_id="000012",
        mst="12",
        body_lines=[
            "이 법은 조문 표제 없이 한 문장 본문만 가지는 짧은 전문 법령을 검증하기 위한 충분한 길이의 본문이다.",
            "",
            "## 부칙",
            "",
            "이 법은 공포한 날부터 시행한다.",
        ],
    )

    report = audit(cache_dir=cache_dir, repo_dir=repo_dir)

    assert report.path_drift == []
    assert report.missing_content == []


def test_audit_rejects_placeholder_body_even_when_text_is_long(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"

    _write_history(cache_dir, "대기법", [{"법령일련번호": "13", "제개정구분명": "제정"}])
    _write_detail(cache_dir, "13", name="대기법", law_id="000013")
    _write_repo_markdown(
        repo_dir,
        "kr/대기법/법률.md",
        title="대기법",
        law_id="000013",
        mst="13",
        body_lines=[
            "> 본문은 추후 추가 예정입니다.",
            ">",
            "> 법령 원문: [대기법](https://www.law.go.kr/법령/대기법)",
        ],
    )

    report = audit(cache_dir=cache_dir, repo_dir=repo_dir)

    assert report.path_drift == []
    assert len(report.missing_content) == 1
    assert report.missing_content[0].expected_path == "kr/대기법/법률.md"


def test_audit_prefers_path_drift_when_empty_expected_file_has_same_id_content_elsewhere(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"

    _write_history(cache_dir, "현재경로법", [{"법령일련번호": "12", "제개정구분명": "제정"}])
    _write_detail(cache_dir, "12", name="현재경로법", law_id="000012")
    _write_repo_markdown(
        repo_dir,
        "kr/현재경로법/법률.md",
        title="현재경로법",
        law_id="000012",
        mst="12",
        body_lines=[],
    )
    _write_repo_markdown(
        repo_dir,
        "kr/과거경로법/법률.md",
        title="현재경로법",
        law_id="000012",
        mst="12",
    )

    report = audit(cache_dir=cache_dir, repo_dir=repo_dir)

    assert len(report.path_drift) == 1
    assert report.path_drift[0].expected_path == "kr/현재경로법/법률.md"
    assert report.path_drift[0].actual_paths == ["kr/과거경로법/법률.md"]
    assert report.missing_content == []


def test_audit_tracks_law_type_rename_as_same_law_id_lineage(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"

    _write_history(
        cache_dir,
        "부처변경규칙",
        [
            {"법령일련번호": "20", "제개정구분명": "제정"},
            {"법령일련번호": "21", "제개정구분명": "일부개정"},
        ],
    )
    _write_detail(
        cache_dir,
        "20",
        name="부처변경규칙",
        law_id="000020",
        law_type="총리령",
        prom_date="20200101",
    )
    _write_detail(
        cache_dir,
        "21",
        name="부처변경규칙",
        law_id="000020",
        law_type="국가보훈부령",
        prom_date="20210101",
    )
    _write_repo_markdown(
        repo_dir,
        "kr/부처변경규칙/총리령.md",
        title="부처변경규칙",
        law_id="000020",
        mst="21",
        law_type="총리령",
    )

    report = audit(cache_dir=cache_dir, repo_dir=repo_dir)

    assert len(report.path_drift) == 1
    assert report.path_drift[0].expected_path == "kr/부처변경규칙/국가보훈부령.md"
    assert report.path_drift[0].actual_paths == ["kr/부처변경규칙/총리령.md"]
    assert report.missing_content == []


def test_audit_reports_detail_files_not_referenced_by_history(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"

    _write_history(cache_dir, "히스토리법", [{"법령일련번호": "20", "제개정구분명": "제정"}])
    _write_detail(cache_dir, "20", name="히스토리법", law_id="000020")
    _write_detail(cache_dir, "21", name="상세만있는법", law_id="000021")

    report = audit(cache_dir=cache_dir, repo_dir=repo_dir)

    assert report.detail_not_in_history == ["21"]


def test_audit_uses_detail_outside_history_for_latest_lineage_path(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"

    _write_history(
        cache_dir,
        "새이름법",
        [{"법령일련번호": "1", "제개정구분명": "일부개정"}],
    )
    _write_detail(
        cache_dir,
        "1",
        name="새이름법",
        law_id="000001",
        prom_date="20251230",
    )
    _write_detail(
        cache_dir,
        "2",
        name="종전이름법",
        law_id="000001",
        prom_date="20260310",
    )
    _write_repo_markdown(
        repo_dir,
        "kr/종전이름법/법률.md",
        title="종전이름법",
        law_id="000001",
        mst="2",
    )

    report = audit(cache_dir=cache_dir, repo_dir=repo_dir)

    assert report.detail_not_in_history == ["2"]
    assert report.path_drift == []
    assert report.missing_content == []


def test_audit_does_not_flag_newer_repo_mst_against_stale_cache(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"

    _write_history(
        cache_dir,
        "새이름법",
        [{"법령일련번호": "1", "제개정구분명": "일부개정"}],
    )
    _write_detail(cache_dir, "1", name="새이름법", law_id="000001")
    _write_repo_markdown(
        repo_dir,
        "kr/종전이름법/법률.md",
        title="종전이름법",
        law_id="000001",
        mst="2",
    )

    report = audit(cache_dir=cache_dir, repo_dir=repo_dir)

    assert report.path_drift == []
    assert report.missing_content == []


def test_audit_reports_history_and_detail_parse_problems(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"

    _write_history(cache_dir, "상세없는법", [{"법령일련번호": "30", "제개정구분명": "제정"}])
    _write_history(cache_dir, "메타없는법", [{"법령일련번호": "31", "제개정구분명": "제정"}])
    _write_history(cache_dir, "빈이력법", [])
    _write_history(cache_dir, "항목깨진법", ["not-a-dict"])
    (cache_dir / "history" / "깨진이력법.json").write_text("{", encoding="utf-8")
    (cache_dir / "detail").mkdir(parents=True, exist_ok=True)
    (cache_dir / "detail" / "31.xml").write_text("<법령><법령ID>000031</법령ID></법령>", encoding="utf-8")
    (cache_dir / "detail" / "not-a-number.xml").write_text("<broken", encoding="utf-8")

    report = audit(cache_dir=cache_dir, repo_dir=repo_dir)

    assert report.empty_history == 1
    assert report.malformed_history == 2
    assert report.missing_detail == ["30"]
    assert report.empty_or_invalid_detail_meta == ["31"]
    assert report.detail_not_in_history == ["not-a-number"]


def test_failure_reasons_respects_selected_gates():
    report = AuditReport(
        history_names=1,
        historical_msts=1,
        detail_msts=1,
        entries_parsed_valid_meta=1,
        final_paths=1,
        empty_history=0,
        malformed_history=0,
        missing_detail=[],
        empty_or_invalid_detail_meta=[],
        detail_not_in_history=[],
        path_drift=[
            PathDrift(
                expected_path="kr/현재법/법률.md",
                actual_paths=["kr/과거법/법률.md"],
                mst="2",
                law_id="000002",
                law_type="법률",
                law_name="현재법",
            )
        ],
        missing_content=[
            MissingContent(
                expected_path="kr/누락법/법률.md",
                mst="1",
                law_id="000001",
                law_type="법률",
                law_name="누락법",
            )
        ],
    )

    assert failure_reasons(report) == []
    assert failure_reasons(report, fail_on_missing_content=True) == ["missing_content=1"]
    assert failure_reasons(report, fail_on_path_drift=True) == ["path_drift=1"]
    assert failure_reasons(
        report,
        fail_on_missing_content=True,
        fail_on_path_drift=True,
    ) == ["missing_content=1", "path_drift=1"]
    assert failure_reasons(
        report,
        fail_on_path_drift=True,
        allowed_path_drift={"kr/현재법/법률.md"},
    ) == []
    assert failure_reasons(
        report,
        fail_on_path_drift=True,
        allowed_path_drift=set(),
    ) == ["new_path_drift=1"]


def test_load_path_drift_allowlist_accepts_expected_paths_dict(tmp_path: Path):
    allowlist = tmp_path / "known_path_drift.yaml"
    allowlist.write_text(
        "expected_paths:\n"
        "  - kr/현재법/법률.md\n",
        encoding="utf-8",
    )

    assert load_path_drift_allowlist(allowlist) == {"kr/현재법/법률.md"}
