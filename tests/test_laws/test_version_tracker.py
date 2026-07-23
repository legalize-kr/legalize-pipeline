"""Tests for the HEAD-regression guard (laws.import_laws.VersionTracker).

The guard had no coverage at all, which is how a quoting bug in
``head_law_version`` reached main: ``build_csv_markdown`` writes
``공포일자: '2024-01-15'`` while the API path writes it bare, and an unstripped
quote sorts below every digit — parking the HEAD baseline at the bottom so no
backfill ever looked like a regression.
"""

import subprocess

import pytest

from laws import git_engine
from laws.import_laws import VersionTracker


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


@pytest.mark.parametrize("quoted", [False, True])
def test_backfilling_an_older_version_is_flagged(law_repo, quoted):
    """The core guard: an older MST committed over a newer HEAD must regress."""
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "00031", quoted=quoted)

    tracker = VersionTracker()
    tracker.seen("kr/민법/법률.md")
    tracker.committed("kr/민법/법률.md", {"공포일자": "19900101", "공포번호": "00001"}, "100")

    assert tracker.regressed() == [("kr/민법/법률.md", "300", "19900101")]


def test_same_date_lower_promulgation_number_is_a_regression(law_repo):
    """MST 는 더 크지만 공포번호가 낮다 — 공포번호가 실제로 비교돼야 잡힌다."""
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "00031")

    tracker = VersionTracker()
    tracker.seen("kr/민법/법률.md")
    tracker.committed("kr/민법/법률.md", {"공포일자": "20240115", "공포번호": "00030"}, "301")

    assert [p for p, _, _ in tracker.regressed()] == ["kr/민법/법률.md"]


def test_same_date_and_number_lower_mst_is_a_regression(law_repo):
    """공포번호까지 같으면 MST 가 마지막 tie-break 다."""
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "00031")

    tracker = VersionTracker()
    tracker.seen("kr/민법/법률.md")
    tracker.committed("kr/민법/법률.md", {"공포일자": "20240115", "공포번호": "00031"}, "299")

    assert [p for p, _, _ in tracker.regressed()] == ["kr/민법/법률.md"]


def test_same_date_higher_promulgation_number_is_not_a_regression(law_repo):
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "00031")

    tracker = VersionTracker()
    tracker.seen("kr/민법/법률.md")
    tracker.committed("kr/민법/법률.md", {"공포일자": "20240115", "공포번호": "00032"}, "301")

    assert tracker.regressed() == []


def test_promulgation_number_compares_numerically_not_lexically(law_repo):
    """31 > 8 이지만 문자열로는 '31' < '8' 이다 — 문자 비교면 허위 퇴행이 뜬다."""
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "8")

    tracker = VersionTracker()
    tracker.seen("kr/민법/법률.md")
    tracker.committed("kr/민법/법률.md", {"공포일자": "20240115", "공포번호": "31"}, "301")

    assert tracker.regressed() == []


def test_zero_padded_promulgation_number_is_the_same_version(law_repo):
    """'00031' 과 '31' 은 같은 개정이므로 퇴행이 아니다."""
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "00031")

    tracker = VersionTracker()
    tracker.seen("kr/민법/법률.md")
    tracker.committed("kr/민법/법률.md", {"공포일자": "20240115", "공포번호": "31"}, "300")

    assert tracker.regressed() == []


def test_newer_version_after_older_leaves_nothing_to_restore(law_repo):
    """Ascending order within one run is the normal path — no restore needed."""
    _commit_version(law_repo, "kr/민법/법률.md", "100", "1990-01-01", "00001")

    tracker = VersionTracker()
    tracker.seen("kr/민법/법률.md")
    tracker.committed("kr/민법/법률.md", {"공포일자": "20240115", "공포번호": "00031"}, "300")

    assert tracker.regressed() == []


def test_file_absent_from_head_is_not_a_regression(law_repo):
    """A brand-new law has no baseline to fall behind."""
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "00031")

    tracker = VersionTracker()
    tracker.seen("kr/신법/법률.md")
    tracker.committed("kr/신법/법률.md", {"공포일자": "20240101", "공포번호": "00001"}, "400")

    assert tracker.regressed() == []


def test_seen_is_idempotent_and_keeps_the_first_baseline(law_repo):
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "00031")

    tracker = VersionTracker()
    tracker.seen("kr/민법/법률.md")
    tracker.committed("kr/민법/법률.md", {"공포일자": "19900101", "공포번호": "00001"}, "100")
    tracker.seen("kr/민법/법률.md")  # must not reset the baseline to the older commit

    assert tracker.regressed() == [("kr/민법/법률.md", "300", "19900101")]


def test_missing_promulgation_date_sorts_lowest(law_repo):
    _commit_version(law_repo, "kr/민법/법률.md", "300", "2024-01-15", "00031")

    tracker = VersionTracker()
    tracker.seen("kr/민법/법률.md")
    tracker.committed("kr/민법/법률.md", {"공포일자": "", "공포번호": ""}, "1")

    assert [p for p, _, _ in tracker.regressed()] == ["kr/민법/법률.md"]
