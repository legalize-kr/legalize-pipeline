"""Tests for laws/generate_metadata.py."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import laws.generate_metadata as gen_meta


@pytest.fixture(autouse=True)
def patch_dirs(tmp_path: Path, monkeypatch):
    kr_dir = tmp_path / "kr"
    kr_dir.mkdir()
    monkeypatch.setattr(gen_meta, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(gen_meta, "METADATA_FILE", tmp_path / "metadata.json")
    monkeypatch.setattr(gen_meta, "STATS_FILE", tmp_path / "stats.json")
    # generate() reads KR_DIR from laws.config at call time via the imported name
    import laws.config as lconf
    monkeypatch.setattr(lconf, "KR_DIR", kr_dir)
    # Also patch the name directly in gen_meta's module namespace
    monkeypatch.setattr(gen_meta, "KR_DIR", kr_dir, raising=False)


def _write_law(path: Path, mst: str, title: str, law_type: str = "법률") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""\
---
제목: {title}
법령MST: {mst}
법령구분: {law_type}
법령구분코드: {law_type}
소관부처:
  - 법무부
공포일자: 2024-01-01
시행일자: 2024-01-01
상태: 시행
---

# {title}
"""
    path.write_text(content, encoding="utf-8")


def test_parse_frontmatter(tmp_path: Path):
    path = tmp_path / "kr" / "민법" / "법률.md"
    _write_law(path, "253527", "민법")
    fm = gen_meta.parse_frontmatter(path)
    assert fm is not None
    assert fm["제목"] == "민법"
    assert fm["법령MST"] == 253527


def test_parse_frontmatter_no_yaml(tmp_path: Path):
    path = tmp_path / "kr" / "민법" / "법률.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 민법\n본문\n", encoding="utf-8")
    fm = gen_meta.parse_frontmatter(path)
    assert fm is None


def test_generate_and_build_stats(tmp_path: Path):
    kr_dir = tmp_path / "kr"
    _write_law(kr_dir / "민법" / "법률.md", "253527", "민법", "법률")
    _write_law(kr_dir / "민법" / "시행령.md", "100001", "민법 시행령", "대통령령")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "abc commit\ndef commit"
        metadata = gen_meta.generate()

    assert len(metadata) == 2
    assert "253527" in metadata
    assert "100001" in metadata
    assert metadata["253527"]["제목"] == "민법"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "abc commit"
        stats = gen_meta.build_stats(metadata)

    assert stats["total"] == 2
    assert "법률" in stats["types"]
    assert "대통령령" in stats["types"]


def test_save_writes_files(tmp_path: Path):
    kr_dir = tmp_path / "kr"
    _write_law(kr_dir / "민법" / "법률.md", "253527", "민법")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        count = gen_meta.save()

    assert count == 1
    assert (tmp_path / "metadata.json").exists()
    assert (tmp_path / "stats.json").exists()
    meta = json.loads((tmp_path / "metadata.json").read_text())
    assert "253527" in meta
