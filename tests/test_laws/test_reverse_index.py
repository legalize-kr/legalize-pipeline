"""Tests for laws.reverse_index.resolve_canonical_mst."""

import logging

from laws.reverse_index import resolve_canonical_mst


def _candidate(name: str, 구분: str, 공포일자: str, mst: str) -> dict:
    return {
        "법령명한글": name,
        "법령구분": 구분,
        "공포일자": 공포일자,
        "법령일련번호": mst,
    }


def test_empty_candidates_returns_none():
    assert resolve_canonical_mst("민법", []) is None


def test_no_exact_match_returns_none():
    candidates = [_candidate("민법 시행령", "대통령령", "20230101", "100")]
    assert resolve_canonical_mst("민법", candidates) is None


def test_single_exact_match_returns_its_mst():
    candidates = [_candidate("민법", "법률", "20230101", "42")]
    assert resolve_canonical_mst("민법", candidates) == "42"


def test_collision_prefers_법률_over_시행령():
    candidates = [
        _candidate("민법", "대통령령", "20230101", "200"),
        _candidate("민법", "법률", "20230101", "100"),
    ]
    assert resolve_canonical_mst("민법", candidates) == "100"


def test_collision_within_법률_prefers_latest_공포일자():
    candidates = [
        _candidate("민법", "법률", "20220101", "101"),
        _candidate("민법", "법률", "20230601", "102"),
    ]
    assert resolve_canonical_mst("민법", candidates) == "102"


def test_collision_logs_name_collision_event(caplog):
    candidates = [
        _candidate("민법", "법률", "20220101", "101"),
        _candidate("민법", "법률", "20230601", "102"),
    ]
    with caplog.at_level(logging.WARNING, logger="laws.reverse_index"):
        resolve_canonical_mst("민법", candidates)
    assert any(r.levelno == logging.WARNING and "name_collision" in r.getMessage()
               for r in caplog.records)
