"""Tests for laws/validate.py."""

from pathlib import Path

import pytest

import laws.validate as validate_mod
from laws.validate import validate_frontmatter


@pytest.fixture(autouse=True)
def patch_dirs(tmp_path: Path, monkeypatch):
    kr_dir = tmp_path / "kr"
    kr_dir.mkdir()
    monkeypatch.setattr(validate_mod, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(validate_mod, "METADATA_FILE", tmp_path / "metadata.json")
    import laws.config as lconf
    monkeypatch.setattr(lconf, "KR_DIR", kr_dir)


def _write_md(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


VALID_FRONTMATTER = """\
---
제목: 민법
법령MST: 253527
법령구분: 법률
법령구분코드: 법률
소관부처:
  - 법무부
공포일자: 2024-01-01
상태: 시행
---

# 민법
"""


def test_validate_valid_file(tmp_path: Path):
    path = tmp_path / "kr" / "민법" / "법률.md"
    _write_md(path, VALID_FRONTMATTER)
    errors = validate_frontmatter(path)
    assert errors == []


def test_validate_missing_fields(tmp_path: Path):
    content = "---\n제목: 민법\n---\n# 민법\n"
    path = tmp_path / "kr" / "민법" / "법률.md"
    _write_md(path, content)
    errors = validate_frontmatter(path)
    missing = [e for e in errors if "Missing required field" in e]
    assert len(missing) > 0


def test_validate_non_list_department(tmp_path: Path):
    content = """\
---
제목: 민법
법령MST: 253527
법령구분: 법률
법령구분코드: 법률
소관부처: 법무부
공포일자: 2024-01-01
상태: 시행
---
# 민법
"""
    path = tmp_path / "kr" / "민법" / "법률.md"
    _write_md(path, content)
    errors = validate_frontmatter(path)
    assert any("소관부처" in e for e in errors)


def test_validate_unnormalized_unicode(tmp_path: Path):
    """Non-canonical middle dot in 제목 is flagged."""
    content = (
        "---\n"
        "제목: 법\u00B7령\n"  # non-canonical dot
        "법령MST: 1\n"
        "법령구분: 법률\n"
        "법령구분코드: 법률\n"
        "소관부처:\n  - 법무부\n"
        "공포일자: 2024-01-01\n"
        "상태: 시행\n"
        "---\n# 법령\n"
    )
    path = tmp_path / "kr" / "법령" / "법률.md"
    _write_md(path, content)
    errors = validate_frontmatter(path)
    assert any("Unicode" in e or "normalize" in e.lower() or "un-normalized" in e for e in errors)


def test_validate_no_frontmatter(tmp_path: Path):
    path = tmp_path / "kr" / "민법" / "법률.md"
    _write_md(path, "# 민법\n본문만 있음\n")
    errors = validate_frontmatter(path)
    assert any("frontmatter" in e.lower() for e in errors)


def test_validate_unterminated_frontmatter(tmp_path: Path):
    path = tmp_path / "kr" / "민법" / "법률.md"
    _write_md(path, "---\n제목: 민법\n# 닫는 --- 없음\n")
    errors = validate_frontmatter(path)
    assert errors  # should have errors
