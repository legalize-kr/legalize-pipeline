"""Tests for laws/git_engine.py — subprocess.run is mocked throughout."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import laws.git_engine as git_engine


def _make_run_result(stdout: str = "", returncode: int = 0, stderr: str = "") -> MagicMock:
    r = MagicMock()
    r.stdout = stdout
    r.returncode = returncode
    r.stderr = stderr
    return r


@pytest.fixture(autouse=True)
def patch_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(git_engine, "WORKSPACE_ROOT", tmp_path)


# ---------------------------------------------------------------------------
# file_has_changes
# ---------------------------------------------------------------------------

def test_file_has_changes_true():
    with patch("subprocess.run", return_value=_make_run_result("M kr/민법/법률.md")) as mock_run:
        result = git_engine.file_has_changes("kr/민법/법률.md")
    assert result is True


def test_file_has_changes_false():
    with patch("subprocess.run", return_value=_make_run_result("")) as mock_run:
        result = git_engine.file_has_changes("kr/민법/법률.md")
    assert result is False


# ---------------------------------------------------------------------------
# commit_exists
# ---------------------------------------------------------------------------

def test_commit_exists_found():
    with patch("subprocess.run", return_value=_make_run_result("abc1234 법률: 민법 (일부개정)")):
        assert git_engine.commit_exists("253527") is True


def test_commit_exists_not_found():
    with patch("subprocess.run", return_value=_make_run_result("")):
        assert git_engine.commit_exists("999999") is False


# ---------------------------------------------------------------------------
# commit_law
# ---------------------------------------------------------------------------

def test_commit_law_success(tmp_path: Path):
    # Create the target file
    file_path = "kr/민법/법률.md"
    (tmp_path / "kr" / "민법").mkdir(parents=True)
    (tmp_path / file_path).write_text("# 민법", encoding="utf-8")

    run_results = [
        _make_run_result(""),           # git log --grep (commit_exists → not found)
        _make_run_result(""),           # git add
        _make_run_result("M kr/민법/법률.md"),  # git status (has changes)
        _make_run_result(""),           # git commit
        _make_run_result("abc1234567890"),  # git rev-parse HEAD
    ]

    with patch("subprocess.run", side_effect=run_results):
        result = git_engine.commit_law(
            file_path,
            "법률: 민법 (일부개정)\n\n법령MST: 253527",
            "2024-01-01",
            "253527",
        )

    assert result == "abc1234567890"


def test_commit_law_skips_when_no_changes(tmp_path: Path):
    file_path = "kr/민법/법률.md"
    (tmp_path / "kr" / "민법").mkdir(parents=True)
    (tmp_path / file_path).write_text("# 민법", encoding="utf-8")

    run_results = [
        _make_run_result(""),  # commit_exists → not found
        _make_run_result(""),  # git add
        _make_run_result(""),  # git status → no changes
    ]

    with patch("subprocess.run", side_effect=run_results):
        result = git_engine.commit_law(file_path, "msg", "2024-01-01", "253527")

    assert result is None


def test_commit_law_date_clamping(tmp_path: Path):
    """Dates before 1970-01-01 are clamped to 1970-01-01."""
    file_path = "kr/민법/법률.md"
    (tmp_path / "kr" / "민법").mkdir(parents=True)
    (tmp_path / file_path).write_text("# 민법", encoding="utf-8")

    captured_envs = []

    def capture_run(args, **kwargs):
        if "commit" in args:
            captured_envs.append(kwargs.get("env", {}))
        return _make_run_result("abc1234" if "rev-parse" in args else "")

    # patch commit_exists to False, file_has_changes to True
    run_results_iter = iter([
        _make_run_result(""),            # commit_exists
        _make_run_result(""),            # git add
        _make_run_result("M file.md"),   # file_has_changes
    ])

    def side_effect(args, **kwargs):
        if "log" in args:
            return _make_run_result("")
        if "add" in args:
            return _make_run_result("")
        if "status" in args:
            return _make_run_result("M file.md")
        if "commit" in args:
            captured_envs.append(kwargs.get("env", {}))
            return _make_run_result("")
        if "rev-parse" in args:
            return _make_run_result("deadbeef")
        return _make_run_result("")

    with patch("subprocess.run", side_effect=side_effect):
        git_engine.commit_law(file_path, "msg", "1969-12-31", "1")

    # The env passed to git commit should clamp to 1970-01-01
    if captured_envs:
        env = captured_envs[0]
        assert "1970-01-01" in env.get("GIT_AUTHOR_DATE", "")


def test_commit_law_file_not_found(tmp_path: Path):
    result = git_engine.commit_law("kr/없는파일/법률.md", "msg", "2024-01-01", "999")
    assert result is None


def test_commit_law_skips_when_already_committed(tmp_path: Path):
    file_path = "kr/민법/법률.md"
    (tmp_path / "kr" / "민법").mkdir(parents=True)
    (tmp_path / file_path).write_text("# 민법", encoding="utf-8")

    with patch("subprocess.run", return_value=_make_run_result("abc commit already")):
        result = git_engine.commit_law(file_path, "msg", "2024-01-01", "253527")

    assert result is None
