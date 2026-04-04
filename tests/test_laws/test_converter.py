"""Tests for laws/converter.py — pure logic, no external dependencies."""

from pathlib import Path

import pytest

from laws.converter import (
    _dedent_content,
    articles_to_markdown,
    build_frontmatter,
    format_date,
    get_group_and_filename,
    get_law_path,
    normalize_law_name,
    parse_departments,
    reset_path_registry,
)


# ---------------------------------------------------------------------------
# Unicode normalization
# ---------------------------------------------------------------------------

def test_normalize_middle_dot_u00b7():
    assert normalize_law_name("법\u00B7령") == "법\u318D령"


def test_normalize_katakana_dot_u30fb():
    assert normalize_law_name("법\u30FB령") == "법\u318D령"


def test_normalize_halfwidth_dot_uff65():
    assert normalize_law_name("법\uFF65령") == "법\u318D령"


def test_normalize_already_canonical():
    assert normalize_law_name("법\u318D령") == "법\u318D령"


# ---------------------------------------------------------------------------
# parse_departments
# ---------------------------------------------------------------------------

def test_parse_departments_single():
    assert parse_departments("법무부") == ["법무부"]


def test_parse_departments_multi():
    assert parse_departments("법무부, 행안부") == ["법무부", "행안부"]


def test_parse_departments_empty():
    assert parse_departments("") == []


def test_parse_departments_whitespace_only():
    assert parse_departments("  ,  ") == []


# ---------------------------------------------------------------------------
# format_date
# ---------------------------------------------------------------------------

def test_format_date_normal():
    assert format_date("20240101") == "2024-01-01"


def test_format_date_empty():
    assert format_date("") == ""


def test_format_date_short():
    assert format_date("2024") == "2024"


def test_format_date_none_like_empty():
    # format_date only checks falsiness; empty string returns empty
    assert format_date("") == ""


def test_format_date_eight_digit():
    assert format_date("19580222") == "1958-02-22"


# ---------------------------------------------------------------------------
# get_group_and_filename
# ---------------------------------------------------------------------------

def test_base_law():
    group, fname = get_group_and_filename("민법", "법률")
    assert group == "민법"
    assert fname == "법률"


def test_enforcement_decree():
    group, fname = get_group_and_filename("민법 시행령", "대통령령")
    assert group == "민법"
    assert fname == "시행령"


def test_enforcement_rule():
    group, fname = get_group_and_filename("민법 시행규칙", "부령")
    assert group == "민법"
    assert fname == "시행규칙"


def test_independent_decree():
    """Law name without suffix maps to its type."""
    group, fname = get_group_and_filename("검사인사규정", "대통령령")
    assert group == "검사인사규정"
    assert fname == "대통령령"


def test_unicode_dot_in_name():
    """Middle dot variants in law name are normalized before suffix matching."""
    # 법\u00B7령 시행령 → group should be 법\u318D령
    group, fname = get_group_and_filename("법\u00B7령 시행령", "대통령령")
    assert group == "법\u318D령"
    assert fname == "시행령"


def test_spaces_stripped_in_group():
    """Spaces inside the group name are removed."""
    group, _ = get_group_and_filename("특정 경제범죄 처벌법 시행령", "대통령령")
    assert " " not in group


# ---------------------------------------------------------------------------
# get_law_path + collision
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_registry():
    """Reset path registry before every test in this module."""
    reset_path_registry()
    yield
    reset_path_registry()


def test_law_path_basic():
    path = get_law_path("민법", "법률")
    assert path == "kr/민법/법률.md"


def test_law_path_enforcement_decree():
    path = get_law_path("민법 시행령", "대통령령")
    assert path == "kr/민법/시행령.md"


def test_law_path_collision():
    """Two different laws mapping to the same base path get a type qualifier."""
    # First registration occupies the base path
    path1 = get_law_path("민법 시행규칙", "총리령")
    # Second registration (different type) collides → qualified
    path2 = get_law_path("민법 시행규칙", "부령")
    assert path1 == "kr/민법/시행규칙.md"
    assert "(부령)" in path2 or "(총리령)" in path2


def test_law_path_same_law_same_path():
    """Same (law_name, law_type) pair always returns the same path."""
    path1 = get_law_path("민법", "법률")
    path2 = get_law_path("민법", "법률")
    assert path1 == path2


def test_reset_path_registry():
    get_law_path("민법", "법률")
    reset_path_registry()
    # After reset, the same registration should work without collision
    path = get_law_path("민법", "법률")
    assert path == "kr/민법/법률.md"


def test_law_path_preexisting_qualified(tmp_path: Path, monkeypatch):
    """If a qualified file already exists on disk, use it."""
    import laws.converter as conv

    # Create the qualified file on disk
    kr_dir = tmp_path / "kr"
    qualified_dir = kr_dir / "민법"
    qualified_dir.mkdir(parents=True)
    (qualified_dir / "시행규칙(부령).md").touch()

    # Monkeypatch KR_DIR so the converter looks in tmp_path
    monkeypatch.setattr(conv, "_assigned_paths", {})
    # We need KR_DIR.parent == tmp_path
    import laws.config as lconf
    monkeypatch.setattr(lconf, "KR_DIR", kr_dir)

    # Re-import get_law_path so it picks up patched KR_DIR
    from laws.converter import get_law_path as glp
    # The function reads KR_DIR from laws.config at import time via the module attribute
    # We patch the module-level reference inside converter
    import laws.converter as lconv
    monkeypatch.setattr(lconv, "KR_DIR", kr_dir, raising=False)

    # Mock the path check: qualified path should exist
    # We use monkeypatch on Path.exists — simpler approach: just call with real fs
    path = glp("민법 시행규칙", "부령")
    assert "부령" in path


# ---------------------------------------------------------------------------
# build_frontmatter
# ---------------------------------------------------------------------------

def test_build_frontmatter_complete():
    metadata = {
        "법령명한글": "민법",
        "법령MST": "253527",
        "법령ID": "001234",
        "법령구분": "법률",
        "법령구분코드": "법률",
        "소관부처명": "법무부",
        "공포일자": "20240101",
        "공포번호": "20000",
        "시행일자": "20240101",
        "법령분야": "민사",
    }
    fm = build_frontmatter(metadata)
    assert fm["제목"] == "민법"
    assert fm["법령MST"] == 253527
    assert fm["소관부처"] == ["법무부"]
    assert fm["공포일자"] == "2024-01-01"
    assert fm["시행일자"] == "2024-01-01"
    assert fm["상태"] == "시행"
    assert "원본제목" not in fm


def test_build_frontmatter_unicode_rename():
    """원본제목 is added when the name contains non-canonical dots."""
    metadata = {
        "법령명한글": "법\u00B7령",  # non-canonical dot
        "법령MST": "1",
        "법령ID": "",
        "법령구분": "법률",
        "법령구분코드": "",
        "소관부처명": "",
        "공포일자": "",
        "공포번호": "",
        "시행일자": "",
        "법령분야": "",
    }
    fm = build_frontmatter(metadata)
    assert fm["제목"] == "법\u318D령"
    assert fm["원본제목"] == "법\u00B7령"


def test_build_frontmatter_multi_department():
    metadata = {
        "법령명한글": "민법",
        "법령MST": "1",
        "법령ID": "",
        "법령구분": "법률",
        "법령구분코드": "",
        "소관부처명": "법무부, 행안부",
        "공포일자": "",
        "공포번호": "",
        "시행일자": "",
        "법령분야": "",
    }
    fm = build_frontmatter(metadata)
    assert fm["소관부처"] == ["법무부", "행안부"]


# ---------------------------------------------------------------------------
# articles_to_markdown
# ---------------------------------------------------------------------------

def test_article_basic():
    articles = [{"조문번호": "1", "조문제목": "통칙", "조문내용": "", "항": []}]
    md = articles_to_markdown(articles)
    assert "##### 제1조 (통칙)" in md


def test_article_no_title():
    articles = [{"조문번호": "2", "조문제목": "", "조문내용": "", "항": []}]
    md = articles_to_markdown(articles)
    assert "##### 제2조" in md
    assert "()" not in md


def test_structural_heading_jang():
    articles = [{"조문번호": "", "조문제목": "", "조문내용": "제1장 총칙", "항": []}]
    md = articles_to_markdown(articles)
    assert md.startswith("## 제1장 총칙")


def test_structural_heading_pyeon():
    articles = [{"조문번호": "", "조문제목": "", "조문내용": "제1편 총칙", "항": []}]
    md = articles_to_markdown(articles)
    assert md.startswith("# 제1편 총칙")


def test_structural_heading_jeol():
    articles = [{"조문번호": "", "조문제목": "", "조문내용": "제1절 통칙", "항": []}]
    md = articles_to_markdown(articles)
    assert md.startswith("### 제1절 통칙")


def test_structural_heading_gwan():
    articles = [{"조문번호": "", "조문제목": "", "조문내용": "제1관 총칙", "항": []}]
    md = articles_to_markdown(articles)
    assert md.startswith("#### 제1관 총칙")


def test_paragraph_with_ho_and_mok():
    articles = [
        {
            "조문번호": "3",
            "조문제목": "",
            "조문내용": "",
            "항": [
                {
                    "항번호": "1",
                    "항내용": "①본문 내용",
                    "호": [
                        {
                            "호번호": "1.",
                            "호내용": "1. 호 내용",
                            "목": [
                                {"목번호": "가.", "목내용": "가. 목 내용"}
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    md = articles_to_markdown(articles)
    assert "**1**" in md          # 항 bold prefix
    assert "본문 내용" in md
    assert "  1\\." in md        # 호 2-space indent
    assert "호 내용" in md
    assert "    가\\." in md     # 목 4-space indent
    assert "목 내용" in md


def test_unicode_dot_normalization_in_articles():
    """Dots in article content are normalized to U+318D."""
    articles = [
        {
            "조문번호": "1",
            "조문제목": "",
            "조문내용": "법\u00B7령",
            "항": [],
        }
    ]
    md = articles_to_markdown(articles)
    assert "\u318D" in md
    assert "\u00B7" not in md


# ---------------------------------------------------------------------------
# _dedent_content
# ---------------------------------------------------------------------------

def test_addenda_dedent():
    text = "  이 법은 공포한 날부터 시행한다."
    result = _dedent_content(text)
    assert result == "이 법은 공포한 날부터 시행한다."


def test_dedent_content_preserves_relative_indent():
    text = "  첫째줄\n    둘째줄 (더 들여쓰기)"
    result = _dedent_content(text)
    lines = result.splitlines()
    assert lines[0] == "첫째줄"
    assert lines[1].startswith("  ")  # relative indent preserved


def test_dedent_content_no_indent():
    text = "이미 flush된 줄"
    assert _dedent_content(text) == text
