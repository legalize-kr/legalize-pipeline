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
    monkeypatch.setattr(gen_meta, "ANOMALIES_FILE", tmp_path / "anomalies.json")
    # generate() reads KR_DIR from laws.config at call time via the imported name
    import laws.config as lconf
    monkeypatch.setattr(lconf, "KR_DIR", kr_dir)
    # Also patch the name directly in gen_meta's module namespace
    monkeypatch.setattr(gen_meta, "KR_DIR", kr_dir, raising=False)
    # Redirect failures ledger to tmp_path so tests don't read/write real workspace
    import laws.failures as failures_mod
    monkeypatch.setattr(failures_mod, "FAILED_FILE", tmp_path / ".failed_msts.json")


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


def test_duplicate_mst_raises(tmp_path: Path):
    """Two files with the same MST must fail fast, not silently lose one entry."""
    kr_dir = tmp_path / "kr"
    _write_law(kr_dir / "방송법" / "법률.md", "285487", "방송법", "법률")
    _write_law(kr_dir / "방송법" / "법률(법률).md", "285487", "방송법", "법률")

    with pytest.raises(RuntimeError, match="Duplicate 법령MST=285487"):
        gen_meta.generate()


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


# ---------------------------------------------------------------------------
# P5 tests: classifications + anomalies.json
# ---------------------------------------------------------------------------

MINIMAL_FRONTMATTER = """\
---
제목: 테스트
법령MST: 999
법령ID: X
법령구분: 대통령령
---

# 테스트
"""


def _run_save(monkeypatch):
    """Run save() with git stubbed out to return 0 commits."""
    monkeypatch.setattr(gen_meta, "count_law_commits", lambda: 0)
    gen_meta.save()


def test_stats_has_classifications_scalars(tmp_path: Path, monkeypatch):
    _run_save(monkeypatch)
    stats = json.loads((tmp_path / "stats.json").read_text())
    c = stats["classifications"]
    assert c["child_only_count"] == 0
    assert c["failed_count"] == 0
    assert c["search_miss_count"] == 0
    assert c["quarantined_stale_count"] == 0


def test_child_only_dir_counted(tmp_path: Path, monkeypatch):
    kr_dir = tmp_path / "kr"
    child_file = kr_dir / "foo" / "시행령.md"
    child_file.parent.mkdir(parents=True, exist_ok=True)
    child_file.write_text(MINIMAL_FRONTMATTER, encoding="utf-8")

    _run_save(monkeypatch)

    stats = json.loads((tmp_path / "stats.json").read_text())
    assert stats["classifications"]["child_only_count"] == 1

    anomalies = json.loads((tmp_path / "anomalies.json").read_text())
    assert anomalies["child_only_dirs"] == ["kr/foo"]


def test_parent_present_not_counted(tmp_path: Path, monkeypatch):
    kr_dir = tmp_path / "kr"
    parent_file = kr_dir / "foo" / "법률.md"
    parent_file.parent.mkdir(parents=True, exist_ok=True)
    parent_file.write_text(MINIMAL_FRONTMATTER.replace("999", "1000"), encoding="utf-8")
    child_file = kr_dir / "foo" / "시행령.md"
    child_file.write_text(MINIMAL_FRONTMATTER, encoding="utf-8")

    _run_save(monkeypatch)

    stats = json.loads((tmp_path / "stats.json").read_text())
    assert stats["classifications"]["child_only_count"] == 0


def test_hidden_stale_files_ignored_in_child_only_check(tmp_path: Path, monkeypatch):
    kr_dir = tmp_path / "kr"
    law_dir = kr_dir / "foo"
    law_dir.mkdir(parents=True, exist_ok=True)
    # Hidden stale — should NOT count as parent markdown
    (law_dir / ".법률.md.stale").write_text(MINIMAL_FRONTMATTER, encoding="utf-8")
    # Child-only markdown present
    (law_dir / "시행령.md").write_text(MINIMAL_FRONTMATTER, encoding="utf-8")

    _run_save(monkeypatch)

    stats = json.loads((tmp_path / "stats.json").read_text())
    assert stats["classifications"]["child_only_count"] == 1
    assert stats["classifications"]["quarantined_stale_count"] == 1

    anomalies = json.loads((tmp_path / "anomalies.json").read_text())
    assert anomalies["quarantined_stale"] == ["kr/foo/.법률.md.stale"]


def test_anomalies_file_written(tmp_path: Path, monkeypatch):
    _run_save(monkeypatch)

    assert (tmp_path / "anomalies.json").exists()
    anomalies = json.loads((tmp_path / "anomalies.json").read_text())
    for key in ("child_only_dirs", "failed_msts", "search_misses", "quarantined_stale"):
        assert key in anomalies
        assert isinstance(anomalies[key], list)


def test_failed_msts_surface_in_anomalies(tmp_path: Path, monkeypatch):
    import laws.failures as failures_mod

    failures_mod.mark_failed("42", "api_error", detail="test error", law_name="테스트법")

    _run_save(monkeypatch)

    anomalies = json.loads((tmp_path / "anomalies.json").read_text())
    assert len(anomalies["failed_msts"]) == 1
    assert anomalies["failed_msts"][0]["mst"] == "42"
    assert anomalies["failed_msts"][0]["reason"] == "api_error"

    stats = json.loads((tmp_path / "stats.json").read_text())
    assert stats["classifications"]["failed_count"] == 1


def test_search_misses_surface_in_anomalies(tmp_path: Path, monkeypatch):
    import laws.failures as failures_mod

    failures_mod.mark_search_miss("foo")

    _run_save(monkeypatch)

    anomalies = json.loads((tmp_path / "anomalies.json").read_text())
    assert len(anomalies["search_misses"]) == 1
    assert anomalies["search_misses"][0]["name"] == "foo"

    stats = json.loads((tmp_path / "stats.json").read_text())
    assert stats["classifications"]["search_miss_count"] == 1
