"""Regression coverage for refusing historical backfills on a published law tree."""

import subprocess

import pytest

from laws import git_engine
from laws import import_laws, rebuild
from laws.import_laws import RebuildRequired, require_monotonic_revision


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _frontmatter(mst: str, prom: str, num: str, *, quoted: bool) -> str:
    q = "'" if quoted else ""
    return (
        "---\n"
        f"법령MST: {mst}\n"
        f"공포일자: {q}{prom}{q}\n"
        f"공포번호: {q}{num}{q}\n"
        "---\n\n본문\n"
    )


@pytest.fixture
def law_repo(tmp_path, monkeypatch):
    """A git repo standing in for legalize-kr, wired into laws.git_engine."""
    repo = tmp_path / "legalize-kr"
    (repo / "kr" / "민법").mkdir(parents=True)
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@t")
    monkeypatch.setattr(git_engine, "LAW_REPO", repo)
    return repo


def _commit_version(repo, rel, mst, prom, num, *, quoted=False):
    (repo / rel).write_text(_frontmatter(mst, prom, num, quoted=quoted), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"법령MST: {mst}")


@pytest.mark.parametrize("quoted", [False, True])
def test_head_law_version_reads_quoted_and_bare_frontmatter(law_repo, quoted):
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "00031", quoted=quoted)

    assert git_engine.head_law_version("kr/민법/법률.md") == ("20240115", "00031", "300")


def test_head_law_version_returns_none_for_unknown_path(law_repo):
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "00031")

    assert git_engine.head_law_version("kr/없는법/법률.md") is None


@pytest.mark.parametrize("head_num, candidate_date, num, mst, blocked", [
    ("00031", "19900101", "1", "100", True),
    ("00031", "20240115", "30", "301", True),
    ("00031", "20240115", "31", "299", True),
    ("00031", "20240115", "32", "301", False),
    ("8", "20240115", "31", "301", False),
    ("00031", "20240115", "31", "300", False),
    ("00031", "", "", "1", True),
])
def test_backfill_guard_uses_date_number_and_serial(law_repo, head_num, candidate_date, num, mst, blocked):
    path = "kr/민법/법률.md"
    _commit_version(law_repo, path, "300", "2024-01-15", head_num, quoted=True)
    candidate = {"공포일자": candidate_date, "공포번호": num}
    if blocked:
        with pytest.raises(RebuildRequired, match=f"MST {mst} predates published MST 300"):
            require_monotonic_revision(path, candidate, mst)
    else:
        require_monotonic_revision(path, candidate, mst)


def test_new_law_does_not_require_rebuild(law_repo):
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "00031")
    require_monotonic_revision("kr/신법/법률.md", {"공포일자": "20240101", "공포번호": "1"}, "400")


def test_dry_run_does_not_stage_infrastructure(law_repo, monkeypatch):
    (law_repo / "README.md").write_text("Local documentation")
    monkeypatch.setattr(rebuild, "LAW_REPO", law_repo)
    assert rebuild.commit_infra(dry_run=True) is None
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=law_repo, text=True)
    assert status == "?? README.md\n"


def test_csv_backfill_requires_rebuild_without_detail_fetch(law_repo, monkeypatch, tmp_path):
    """CSV backfills leave the published file and history intact."""
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "00031")
    monkeypatch.setattr(import_laws, "KR_DIR", law_repo / "kr")
    monkeypatch.setattr(import_laws, "get_processed_msts", lambda: set())
    monkeypatch.setattr(import_laws, "mark_processed", lambda _mst: None)
    monkeypatch.setattr(import_laws, "parse_csv", lambda _path: [{
        "법령MST": "100",
        "소관부처명": "법무부",
        "법령ID": "000001",
        "법령명": "민법",
        "공포일자": "19900101",
        "공포번호": "1",
        "시행일자": "19900101",
        "법령구분코드": "A",
        "법령구분명": "법률",
        "법령분야명": "민사",
    }])
    monkeypatch.setattr(
        import_laws,
        "get_law_detail",
        lambda _mst: pytest.fail("CSV 복원은 상세 조회를 호출하면 안 된다"),
    )

    with pytest.raises(RebuildRequired, match="MST 100 predates published MST 300"):
        import_laws.import_from_csv(tmp_path / "fallback.csv")

    assert "법령MST: 300" in subprocess.check_output(
        ["git", "show", "HEAD:kr/민법/법률.md"], cwd=law_repo, text=True
    )
