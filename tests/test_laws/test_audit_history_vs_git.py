"""Tests for laws/audit_history_vs_git.py."""

import json
import os
import subprocess
from datetime import date
from pathlib import Path

from laws.audit_history_vs_git import audit, failure_reasons


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
    amendment: str = "일부개정",
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
                f"  <제개정구분명>{amendment}</제개정구분명>",
                "</법령>",
            ]
        ),
        encoding="utf-8",
    )


def _run_git(repo_dir: Path, *args: str, env: dict | None = None) -> None:
    subprocess.run(["git", "-C", str(repo_dir), *args], check=True, env=env)


def _init_repo(repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True)
    subprocess.run(["git", "init", str(repo_dir)], check=True)
    _run_git(repo_dir, "config", "user.name", "Tester")
    _run_git(repo_dir, "config", "user.email", "tester@example.com")


def _commit_mst(
    repo_dir: Path,
    mst: str,
    *,
    subject: str,
    commit_date: str,
    promulgation_date: str,
    promulgation_number: str,
) -> None:
    marker = repo_dir / "marker.txt"
    marker.write_text(f"{mst}\n", encoding="utf-8")
    _run_git(repo_dir, "add", "marker.txt")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Tester",
        "GIT_AUTHOR_EMAIL": "tester@example.com",
        "GIT_AUTHOR_DATE": f"{commit_date}T12:00:00+09:00",
        "GIT_COMMITTER_NAME": "Tester",
        "GIT_COMMITTER_EMAIL": "tester@example.com",
        "GIT_COMMITTER_DATE": f"{commit_date}T12:00:00+09:00",
    }
    _run_git(
        repo_dir,
        "commit",
        "-m",
        "\n".join(
            [
                subject,
                "",
                f"공포일자: {promulgation_date}",
                f"공포번호: {promulgation_number}",
                f"법령MST: {mst}",
            ]
        ),
        env=env,
    )


def test_audit_history_vs_git_classifies_recent_and_long_term_missing(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"
    _init_repo(repo_dir)
    _commit_mst(
        repo_dir,
        "100",
        subject="법률: 현재법 (일부개정)",
        commit_date="2026-06-01",
        promulgation_date="2026-06-01",
        promulgation_number="100",
    )

    _write_history(
        cache_dir,
        "테스트법",
        [
            {
                "법령일련번호": "100",
                "법령명한글": "현재법",
                "제개정구분명": "일부개정",
                "법령구분": "법률",
                "공포일자": "20260601",
                "공포번호": "100",
            },
            {
                "법령일련번호": "200",
                "법령명한글": "장기누락법",
                "제개정구분명": "제정",
                "법령구분": "법률",
                "공포일자": "20220101",
                "공포번호": "200",
            },
            {
                "법령일련번호": "300",
                "법령명한글": "최근캐시법",
                "제개정구분명": "일부개정",
                "법령구분": "법률",
                "공포일자": "20260602",
                "공포번호": "300",
            },
            {
                "법령일련번호": "400",
                "법령명한글": "상세없는법",
                "제개정구분명": "제정",
                "법령구분": "법률",
                "공포일자": "20200101",
                "공포번호": "400",
            },
        ],
    )
    _write_detail(
        cache_dir,
        "100",
        name="현재법",
        law_id="000100",
        prom_date="20260601",
        prom_num="100",
        amendment="일부개정",
    )
    _write_detail(cache_dir, "200", name="장기누락법", law_id="000200", prom_date="20220101")
    _write_detail(cache_dir, "300", name="최근캐시법", law_id="000300", prom_date="20260602")

    report = audit(
        cache_dir=cache_dir,
        repo_dir=repo_dir,
        recent_days=365,
        check_commit_metadata=True,
        today=date(2026, 6, 23),
    )

    assert report.history_names == 1
    assert report.historical_msts == 4
    assert report.git_msts == 1
    assert [record.mst for record in report.missing_in_git_with_valid_detail] == [
        "200",
        "300",
    ]
    assert [record.mst for record in report.missing_in_git_without_valid_detail] == [
        "400",
    ]
    assert report.commit_metadata_checked is True
    assert report.commit_metadata_mismatches == []
    assert [record.mst for record in report.recent_cache_ahead] == ["300"]
    assert [record.mst for record in report.long_term_missing] == ["200"]
    assert report.missing_in_git_with_valid_detail[0].promulgation_number == "200"
    assert failure_reasons(report, fail_on_long_term_missing=True) == [
        "long_term_missing=1"
    ]
    assert failure_reasons(report, fail_on_any_valid_missing=True) == [
        "missing_in_git_with_valid_detail=2"
    ]


def test_audit_history_vs_git_reports_commit_metadata_mismatch(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    repo_dir = tmp_path / "legalize-kr"
    _init_repo(repo_dir)
    _commit_mst(
        repo_dir,
        "500",
        subject="대통령령: 다른법 (타법개정)",
        commit_date="2026-06-05",
        promulgation_date="2026-06-04",
        promulgation_number="999",
    )
    _write_history(
        cache_dir,
        "메타검증법",
        [
            {
                "법령일련번호": "500",
                "법령명한글": "메타검증법",
                "제개정구분명": "일부개정",
                "법령구분": "법률",
                "공포일자": "20260603",
                "공포번호": "500",
            },
        ],
    )
    _write_detail(
        cache_dir,
        "500",
        name="메타검증법",
        law_id="000500",
        law_type="법률",
        prom_date="20260603",
        prom_num="500",
        amendment="일부개정",
    )

    report = audit(
        cache_dir=cache_dir,
        repo_dir=repo_dir,
        recent_days=365,
        check_commit_metadata=True,
        today=date(2026, 6, 23),
    )

    fields = {mismatch.field for mismatch in report.commit_metadata_mismatches}
    assert fields == {
        "commit_date",
        "공포일자",
        "공포번호",
        "제개정구분",
        "법령구분",
        "법령명",
    }
    assert failure_reasons(report, fail_on_commit_metadata_mismatch=True) == [
        "commit_metadata_mismatches=6"
    ]
