"""Tests for laws/converter.py — pure logic, no external dependencies."""

import datetime
from pathlib import Path

import pytest

from laws.converter import (
    _dedent_content,
    articles_to_markdown,
    build_frontmatter,
    format_date,
    get_group_and_filename,
    get_law_path,
    law_to_markdown,
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


def test_law_path_collision_different_law_id():
    """Two genuinely different laws at the same structural path get a type qualifier."""
    path1 = get_law_path("민법 시행규칙", "총리령", "001111")
    path2 = get_law_path("민법 시행규칙", "부령", "002222")
    assert path1 == "kr/민법/시행규칙.md"
    assert "(부령)" in path2


def test_law_path_same_law_id_no_collision():
    """Same law_id with different ministry names (rename) resolves to the same path."""
    path1 = get_law_path("민법 시행규칙", "안전행정부령", "001111")
    path2 = get_law_path("민법 시행규칙", "행정안전부령", "001111")
    assert path1 == path2 == "kr/민법/시행규칙.md"


def test_law_path_same_law_same_path():
    """Same (law_name, law_type, law_id) always returns the same path."""
    path1 = get_law_path("민법", "법률", "000001")
    path2 = get_law_path("민법", "법률", "000001")
    assert path1 == path2


def test_reset_path_registry():
    get_law_path("민법", "법률")
    reset_path_registry()
    # After reset, the same registration should work without collision
    path = get_law_path("민법", "법률")
    assert path == "kr/민법/법률.md"


def test_law_path_unknown_id_no_collision():
    """When law_id is unknown (empty), paths do not collide with each other."""
    path1 = get_law_path("민법 시행규칙", "총리령", "")
    path2 = get_law_path("민법 시행규칙", "부령", "")
    # Both have empty id — treat as same logical law, no collision
    assert path1 == path2 == "kr/민법/시행규칙.md"


def test_law_path_genuine_collision_different_id():
    """Different law_ids at same structural path: second gets a law_type qualifier."""
    path1 = get_law_path("민법 시행규칙", "총리령", "AAA")
    path2 = get_law_path("민법 시행규칙", "부령", "BBB")
    assert path1 == "kr/민법/시행규칙.md"
    assert path2 == "kr/민법/시행규칙(부령).md"


def test_law_path_no_disk_check():
    """get_law_path does not consult the filesystem — collision is ID-based only."""
    # Even if hypothetically a qualified file existed on disk, same law_id → canonical path
    path = get_law_path("민법 시행규칙", "부령", "001111")
    assert path == "kr/민법/시행규칙.md"
    assert "(" not in path


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
    assert fm["공포일자"] == datetime.date(2024, 1, 1)
    assert fm["시행일자"] == datetime.date(2024, 1, 1)
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


def test_branch_numbers_render_for_jo_hang_ho_mok():
    """Regression for legalize-pipeline#2: 조/항/호/목 가지번호를 `의N` 접미사로 렌더링."""
    articles = [
        {
            "조문번호": "4",
            "조문가지번호": "2",
            "조문제목": "가지조",
            "조문내용": "제4조의2 (가지조) 본문",
            "항": [
                {
                    "항번호": "①",
                    "항가지번호": "3",
                    "항내용": "①가지항",
                    "호": [
                        {
                            "호번호": "1.",
                            "호가지번호": "2",
                            "호내용": "1의2. 가지호",
                            "목": [
                                {
                                    "목번호": "가.",
                                    "목가지번호": "4",
                                    "목내용": "가의4. 가지목",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    md = articles_to_markdown(articles)
    assert "##### 제4조의2 (가지조)" in md
    assert "**①의3**" in md
    assert "  1의2\\. 가지호" in md
    assert "    가의4\\. 가지목" in md


def test_branch_numbers_absent_preserves_plain_format():
    """가지번호가 없을 때는 `의N` 접미사를 붙이지 않는다 (회귀 방지)."""
    articles = [
        {
            "조문번호": "1",
            "조문가지번호": "",
            "조문제목": "",
            "조문내용": "",
            "항": [
                {
                    "항번호": "1",
                    "항가지번호": "",
                    "항내용": "①본문",
                    "호": [
                        {
                            "호번호": "1.",
                            "호가지번호": "",
                            "호내용": "1. 호",
                            "목": [
                                {"목번호": "가.", "목가지번호": "", "목내용": "가. 목"}
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    md = articles_to_markdown(articles)
    assert "**1**" in md
    assert "**1의" not in md
    assert "  1\\. 호" in md
    assert "    가\\. 목" in md


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


# ---------------------------------------------------------------------------
# law_to_markdown — empty body checks (P1)
# ---------------------------------------------------------------------------

def _minimal_detail(articles=None, addenda=None):
    """Build a minimal detail dict for law_to_markdown tests."""
    return {
        "metadata": {
            "법령명한글": "테스트법",
            "법령MST": "1",
            "법령ID": "",
            "법령구분": "법률",
            "법령구분코드": "",
            "소관부처명": "",
            "공포일자": "",
            "공포번호": "",
            "시행일자": "",
            "법령분야": "",
        },
        "articles": articles if articles is not None else [],
        "addenda": addenda if addenda is not None else [],
    }


def test_law_to_markdown_raises_on_empty_body():
    detail = _minimal_detail(articles=[], addenda=[])
    with pytest.raises(ValueError, match="empty_body"):
        law_to_markdown(detail)


def test_law_to_markdown_raises_when_addenda_all_empty():
    detail = _minimal_detail(
        articles=[],
        addenda=[{"부칙내용": ""}, {"부칙내용": "   "}],
    )
    with pytest.raises(ValueError, match="empty_body"):
        law_to_markdown(detail)


def test_law_to_markdown_addenda_only_passes():
    detail = _minimal_detail(
        articles=[],
        addenda=[{"부칙내용": "이 법은 공포일부터 시행한다."}],
    )
    result = law_to_markdown(detail)
    assert "## 부칙" in result
    assert "이 법은 공포일부터 시행한다." in result


def test_law_to_markdown_articles_only_passes(sample_law_detail):
    detail = {**sample_law_detail, "addenda": []}
    result = law_to_markdown(detail)
    assert result  # non-empty markdown string
