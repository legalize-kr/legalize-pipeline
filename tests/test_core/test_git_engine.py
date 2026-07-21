"""Tests for shared Git historical-date commit helpers."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import git_engine


def _make_run_result(stdout: str = "", returncode: int = 0, stderr: str = "") -> MagicMock:
    result = MagicMock()
    result.stdout = stdout
    result.returncode = returncode
    result.stderr = stderr
    return result


def test_file_has_changes_true(tmp_path: Path):
    with patch("subprocess.run", return_value=_make_run_result("M kr/민법/법률.md")):
        assert git_engine.file_has_changes(tmp_path, [Path("kr/민법/법률.md")]) is True


def test_commit_exists_found(tmp_path: Path):
    with patch("subprocess.run", return_value=_make_run_result("abc1234 법률: 민법")):
        assert git_engine.commit_exists(tmp_path, "법령MST: 253527") is True


def test_commit_exists_does_not_match_identifier_prefix(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "law.md").write_text("content", encoding="utf-8")
    subprocess.run(["git", "add", "law.md"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "법령MST: 2535270",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    assert git_engine.commit_exists(tmp_path, "법령MST: 2535270") is True
    assert git_engine.commit_exists(tmp_path, "법령MST: 253527") is False


def test_commit_with_historical_date_success(tmp_path: Path):
    file_path = Path("kr/민법/법률.md")
    (tmp_path / file_path.parent).mkdir(parents=True)
    (tmp_path / file_path).write_text("# 민법", encoding="utf-8")

    run_results = [
        _make_run_result(""),
        _make_run_result(""),
        _make_run_result("M kr/민법/법률.md"),
        _make_run_result(""),
    ]

    with patch("subprocess.run", side_effect=run_results):
        result = git_engine.commit_with_historical_date(
            tmp_path,
            [file_path],
            "법률: 민법\n\n법령MST: 253527",
            "2024-01-01",
            dedup_grep_key="법령MST: 253527",
        )

    assert result is True


def test_commit_with_historical_date_skips_when_no_changes(tmp_path: Path):
    file_path = Path("kr/민법/법률.md")
    (tmp_path / file_path.parent).mkdir(parents=True)
    (tmp_path / file_path).write_text("# 민법", encoding="utf-8")

    with patch("subprocess.run", side_effect=[_make_run_result(""), _make_run_result(""), _make_run_result("")]):
        result = git_engine.commit_with_historical_date(
            tmp_path,
            [file_path],
            "msg",
            "2024-01-01",
            dedup_grep_key="법령MST: 253527",
        )

    assert result is False


def test_commit_with_historical_date_clamps_pre_epoch(tmp_path: Path):
    file_path = Path("kr/민법/법률.md")
    (tmp_path / file_path.parent).mkdir(parents=True)
    (tmp_path / file_path).write_text("# 민법", encoding="utf-8")
    captured_envs = []

    def side_effect(args, **kwargs):
        if "commit" in args:
            captured_envs.append(kwargs.get("env", {}))
        if "status" in args:
            return _make_run_result("M kr/민법/법률.md")
        return _make_run_result("")

    with patch("subprocess.run", side_effect=side_effect):
        assert git_engine.commit_with_historical_date(tmp_path, [file_path], "msg", "1969-12-31") is True

    assert captured_envs[0]["GIT_AUTHOR_DATE"].startswith("1970-01-01")


def test_commit_with_historical_date_sets_author_and_committer(tmp_path: Path):
    file_path = Path("kr/민법/법률.md")
    (tmp_path / file_path.parent).mkdir(parents=True)
    (tmp_path / file_path).write_text("# 민법", encoding="utf-8")
    captured_envs = []

    def side_effect(args, **kwargs):
        if "commit" in args:
            captured_envs.append(kwargs.get("env", {}))
        if "status" in args:
            return _make_run_result("M kr/민법/법률.md")
        return _make_run_result("")

    with patch("subprocess.run", side_effect=side_effect):
        assert git_engine.commit_with_historical_date(
            tmp_path,
            [file_path],
            "msg",
            "2024-01-01",
            author="legalize-kr-bot <bot@legalize.kr>",
        ) is True

    env = captured_envs[0]
    assert env["GIT_AUTHOR_NAME"] == "legalize-kr-bot"
    assert env["GIT_AUTHOR_EMAIL"] == "bot@legalize.kr"
    assert env["GIT_COMMITTER_NAME"] == "legalize-kr-bot"
    assert env["GIT_COMMITTER_EMAIL"] == "bot@legalize.kr"


def test_commit_with_historical_date_allows_tracked_deletion(tmp_path: Path):
    file_path = Path("old.md")
    run_results = [
        _make_run_result("old.md"),
        _make_run_result(""),
        _make_run_result("D old.md"),
        _make_run_result(""),
    ]

    with patch("subprocess.run", side_effect=run_results):
        result = git_engine.commit_with_historical_date(tmp_path, [file_path], "msg", "2024-01-01")

    assert result is True


def test_commit_with_historical_date_commits_git_mv_with_updated_content(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)

    old_path = Path("kr/이전법/법률.md")
    new_path = Path("kr/현재법/법률.md")
    (repo / old_path).parent.mkdir(parents=True)
    (repo / old_path).write_text("old content", encoding="utf-8")
    subprocess.run(["git", "add", str(old_path)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)

    (repo / new_path).parent.mkdir(parents=True)
    subprocess.run(["git", "mv", str(old_path), str(new_path)], cwd=repo, check=True)
    (repo / new_path).write_text("new content", encoding="utf-8")

    result = git_engine.commit_with_historical_date(
        repo,
        [new_path, old_path],
        "법률: 현재법\n\n법령MST: 2",
        "2024-01-01",
    )

    assert result is True
    assert subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""
    assert subprocess.run(
        ["git", "show", f"HEAD:{new_path}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == "new content"
    assert subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{old_path}"],
        cwd=repo,
        capture_output=True,
    ).returncode != 0


def test_commit_with_historical_date_missing_file(tmp_path: Path):
    assert git_engine.commit_with_historical_date(tmp_path, [Path("missing.md")], "msg", "2024-01-01") is False


def test_commit_with_historical_date_allows_empty_revision(tmp_path: Path):
    calls = []

    def side_effect(args, **kwargs):
        calls.append((args, kwargs))
        return _make_run_result("")

    with patch("subprocess.run", side_effect=side_effect):
        result = git_engine.commit_with_historical_date(
            tmp_path,
            [],
            "조례: 캐시에 선행본이 없는 폐지\n\n자치법규일련번호: 2",
            "2024-01-01",
            dedup_grep_key="자치법규일련번호: 2",
            allow_empty=True,
        )

    assert result is True
    commit_args = next(args for args, _ in calls if "commit" in args)
    assert "--allow-empty" in commit_args
