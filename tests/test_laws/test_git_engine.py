"""Tests for the laws git_engine shim."""

from pathlib import Path
from unittest.mock import patch

import laws.git_engine as git_engine


def test_commit_law_delegates_to_core(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(git_engine, "LAW_REPO", tmp_path)
    with patch("laws.git_engine.commit_with_historical_date", return_value=True) as mock_commit:
        result = git_engine.commit_law("kr/민법/법률.md", "msg", "2024-01-01", "253527")

    assert result is True
    mock_commit.assert_called_once_with(
        tmp_path,
        [Path("kr/민법/법률.md")],
        "msg",
        "2024-01-01",
        author="legalize-kr-bot <bot@legalize.kr>",
        dedup_grep_key="법령MST: 253527",
    )


def test_commit_law_skip_dedup(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(git_engine, "LAW_REPO", tmp_path)
    with patch("laws.git_engine.commit_with_historical_date", return_value=False) as mock_commit:
        result = git_engine.commit_law("kr/민법/법률.md", "msg", "2024-01-01", "253527", skip_dedup=True)

    assert result is False
    assert mock_commit.call_args.kwargs["dedup_grep_key"] is None
