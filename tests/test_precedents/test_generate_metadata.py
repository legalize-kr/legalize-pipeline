"""Tests for precedents/generate_metadata.py."""

import json
from pathlib import Path

import pytest

import precedents.generate_metadata as gen_meta


@pytest.fixture(autouse=True)
def patch_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gen_meta, "METADATA_FILE", tmp_path / "metadata.json")
    monkeypatch.setattr(gen_meta, "STATS_FILE", tmp_path / "stats.json")


def _write_precedent(path: Path, serial: str, case_type: str = "민사") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""\
---
판례일련번호: {serial}
사건명: 테스트 사건
사건번호: 2024다{serial}
선고일자: 2024-01-01
법원명: 대법원
사건종류: {case_type}
판결유형: 판결
---

본문
"""
    path.write_text(content, encoding="utf-8")


def test_generate_reads_frontmatter_and_builds_metadata(tmp_path: Path):
    _write_precedent(tmp_path / "민사" / "대법원" / "2024다111.md", "111", "민사")
    _write_precedent(tmp_path / "형사" / "하급심" / "2024고합222.md", "222", "형사")

    metadata, skipped = gen_meta.generate(output_dir=tmp_path)

    assert len(metadata) == 2
    assert skipped == 0
    assert "111" in metadata
    assert "222" in metadata
    assert metadata["111"]["path"] == "민사/대법원/2024다111.md"
    assert metadata["111"]["사건종류"] == "민사"
    assert "사건종류명" not in metadata["111"]
    assert metadata["222"]["사건종류"] == "형사"


def test_build_stats_courts_by_tier_case_types_by_category():
    metadata = {
        "111": {"path": "민사/대법원/X.md", "사건종류": "민사"},
        "222": {"path": "형사/하급심/Y.md", "사건종류": "형사"},
    }
    stats = gen_meta.build_stats(metadata, skipped_errors=0)

    assert stats["courts"] == {"대법원": 1, "하급심": 1}
    assert stats["case_types"] == {"민사": 1, "형사": 1}


def test_build_stats_handles_short_path():
    metadata = {
        "999": {"path": "nodirfile.md", "사건종류": "민사"},
    }
    stats = gen_meta.build_stats(metadata, skipped_errors=0)

    assert stats["courts"]["미분류"] == 1


def test_build_stats_has_generated_at():
    metadata = {
        "1": {"path": "민사/대법원/A.md", "사건종류": "민사"},
    }
    stats = gen_meta.build_stats(metadata, skipped_errors=0)

    assert "generated_at" in stats
    # Should be a valid ISO string
    assert "T" in stats["generated_at"]


def test_save_writes_both_files(tmp_path: Path):
    _write_precedent(tmp_path / "민사" / "대법원" / "2024다1.md", "1", "민사")

    count = gen_meta.save(output_dir=tmp_path)

    assert count == 1
    assert (tmp_path / "metadata.json").exists()
    assert (tmp_path / "stats.json").exists()
    meta = json.loads((tmp_path / "metadata.json").read_text())
    assert "1" in meta
    stats = json.loads((tmp_path / "stats.json").read_text())
    assert stats["total"] == 1
