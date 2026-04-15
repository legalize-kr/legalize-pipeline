"""Tests for precedents/converter.py — pure logic, no external dependencies."""

import pytest
import yaml

import precedents.converter as conv


# ---------------------------------------------------------------------------
# Sample XML (defined as str, encoded to bytes at module load)
# ---------------------------------------------------------------------------

VALID_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PrecService>
  <판례정보일련번호>123456</판례정보일련번호>
  <사건명><![CDATA[손해배상(기)]]></사건명>
  <사건번호>2023다12345</사건번호>
  <선고일자>20231201</선고일자>
  <선고>선고</선고>
  <법원명>대법원</법원명>
  <법원종류코드>400201</법원종류코드>
  <사건종류명>민사</사건종류명>
  <사건종류코드>400101</사건종류코드>
  <판결유형>판결</판결유형>
  <판시사항><![CDATA[원고의 청구를 인용한다.]]></판시사항>
  <판결요지><![CDATA[원심판결을 파기한다.]]></판결요지>
  <참조조문><![CDATA[민법 제750조]]></참조조문>
  <참조판례><![CDATA[대법원 2020다12345]]></참조판례>
  <판례내용><![CDATA[주문<br/>1. 원심판결을 파기한다.]]></판례내용>
</PrecService>
""".encode("utf-8")

ERROR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Law>
  <result>실패</result>
  <msg>Not found</msg>
</Law>
""".encode("utf-8")

MISSING_FIELDS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PrecService>
  <판례정보일련번호>789012</판례정보일련번호>
  <사건번호>2020가합1234</사건번호>
</PrecService>
""".encode("utf-8")

EMPTY_SECTIONS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PrecService>
  <판례정보일련번호>111111</판례정보일련번호>
  <사건명><![CDATA[행정처분취소]]></사건명>
  <사건번호>2022누9999</사건번호>
  <선고일자>20220601</선고일자>
  <선고>선고</선고>
  <법원명>서울고등법원</법원명>
  <법원종류코드>400202</법원종류코드>
  <사건종류명>일반행정</사건종류명>
  <사건종류코드>400107</사건종류코드>
  <판결유형>판결</판결유형>
  <판시사항><![CDATA[]]></판시사항>
  <판결요지><![CDATA[]]></판결요지>
  <참조조문><![CDATA[]]></참조조문>
  <참조판례><![CDATA[]]></참조판례>
  <판례내용><![CDATA[주문<br/>청구 기각]]></판례내용>
</PrecService>
""".encode("utf-8")


# ---------------------------------------------------------------------------
# parse_precedent_xml
# ---------------------------------------------------------------------------

def test_parse_precedent_xml_valid_returns_all_fields():
    result = conv.parse_precedent_xml(VALID_XML)
    assert result is not None
    assert result["판례정보일련번호"] == "123456"
    assert result["사건명"] == "손해배상(기)"
    assert result["사건번호"] == "2023다12345"
    assert result["선고일자"] == "20231201"
    assert result["선고"] == "선고"
    assert result["법원명"] == "대법원"
    assert result["법원종류코드"] == "400201"
    assert result["사건종류명"] == "민사"
    assert result["사건종류코드"] == "400101"
    assert result["판결유형"] == "판결"
    assert result["판시사항"] == "원고의 청구를 인용한다."
    assert result["판결요지"] == "원심판결을 파기한다."
    assert result["참조조문"] == "민법 제750조"
    assert result["참조판례"] == "대법원 2020다12345"
    assert "판례내용" in result


def test_parse_precedent_xml_error_root_returns_none():
    result = conv.parse_precedent_xml(ERROR_XML)
    assert result is None


def test_parse_precedent_xml_missing_fields_returns_empty_strings():
    result = conv.parse_precedent_xml(MISSING_FIELDS_XML)
    assert result is not None
    assert result["판례정보일련번호"] == "789012"
    assert result["사건번호"] == "2020가합1234"
    assert result["판시사항"] == ""
    assert result["판결요지"] == ""
    assert result["판례내용"] == ""


# ---------------------------------------------------------------------------
# normalize_court_name
# ---------------------------------------------------------------------------

def test_normalize_court_name_seoul_high():
    assert conv.normalize_court_name("서울고법") == "서울고등법원"


def test_normalize_court_name_daegu_district():
    assert conv.normalize_court_name("대구지법") == "대구지방법원"


def test_normalize_court_name_seoul_admin():
    assert conv.normalize_court_name("서울행법") == "서울행정법원"


def test_normalize_court_name_supreme_unchanged():
    assert conv.normalize_court_name("대법원") == "대법원"


# ---------------------------------------------------------------------------
# get_court_tier
# ---------------------------------------------------------------------------

def test_get_court_tier_supreme():
    assert conv.get_court_tier("400201") == "대법원"


def test_get_court_tier_lower():
    assert conv.get_court_tier("400202") == "하급심"


def test_get_court_tier_empty():
    assert conv.get_court_tier("") == "미분류"


# ---------------------------------------------------------------------------
# normalize_case_type
# ---------------------------------------------------------------------------

def test_normalize_case_type_known_passes_through():
    assert conv.normalize_case_type("민사") == "민사"


def test_normalize_case_type_empty_becomes_gita():
    assert conv.normalize_case_type("") == "기타"


def test_normalize_case_type_multiple_joined_with_dot():
    assert conv.normalize_case_type("선거,특별") == "선거·특별"


# ---------------------------------------------------------------------------
# sanitize_case_number
# ---------------------------------------------------------------------------

def test_sanitize_case_number_comma():
    assert conv.sanitize_case_number("2006허1803, 1827") == "2006허1803_1827"


def test_sanitize_case_number_parenthetical_prefix():
    assert conv.sanitize_case_number("(창원)2012노368") == "2012노368"


def test_sanitize_case_number_parenthetical_suffix():
    assert conv.sanitize_case_number("94다53587(참가)") == "94다53587_참가"


# ---------------------------------------------------------------------------
# html_to_markdown
# ---------------------------------------------------------------------------

def test_html_to_markdown_br_becomes_newline():
    result = conv.html_to_markdown("첫째줄<br/>둘째줄")
    assert "첫째줄" in result
    assert "둘째줄" in result
    assert "<br" not in result
    assert len(result.splitlines()) >= 2


def test_html_to_markdown_strips_tags():
    result = conv.html_to_markdown("<b>굵은</b> 텍스트")
    assert "굵은" in result
    assert "텍스트" in result
    assert "<b>" not in result
    assert "</b>" not in result


def test_html_to_markdown_collapses_blank_lines():
    # 3 br tags → 3 newlines; collapse so max 1 consecutive blank line
    result = conv.html_to_markdown("첫줄<br/><br/><br/>넷째줄")
    blank_run = 0
    max_blank_run = 0
    for line in result.splitlines():
        if not line.strip():
            blank_run += 1
            max_blank_run = max(max_blank_run, blank_run)
        else:
            blank_run = 0
    assert max_blank_run <= 1


# ---------------------------------------------------------------------------
# format_date
# ---------------------------------------------------------------------------

def test_format_date_valid():
    assert conv.format_date("20040514") == "2004-05-14"


def test_format_date_invalid_zero_year():
    assert conv.format_date("00010101") is None


def test_format_date_empty():
    assert conv.format_date("") is None


# ---------------------------------------------------------------------------
# normalize_dangi_yyyymmdd
# ---------------------------------------------------------------------------

def test_normalize_dangi_converts_in_range():
    assert conv.normalize_dangi_yyyymmdd("42890525") == "19560525"
    assert conv.normalize_dangi_yyyymmdd("42000101") == "18670101"
    assert conv.normalize_dangi_yyyymmdd("43301231") == "19971231"


def test_normalize_dangi_passes_through_gregorian():
    assert conv.normalize_dangi_yyyymmdd("20240101") == "20240101"
    assert conv.normalize_dangi_yyyymmdd("19801231") == "19801231"


def test_normalize_dangi_passes_through_out_of_range():
    assert conv.normalize_dangi_yyyymmdd("41991231") == "41991231"
    assert conv.normalize_dangi_yyyymmdd("43310101") == "43310101"


def test_normalize_dangi_passes_through_invalid_input():
    assert conv.normalize_dangi_yyyymmdd("") == ""
    assert conv.normalize_dangi_yyyymmdd("abcd0101") == "abcd0101"
    assert conv.normalize_dangi_yyyymmdd("2024") == "2024"


def test_parse_precedent_xml_normalizes_dangi():
    dangi_xml = """<?xml version="1.0" encoding="UTF-8"?>
<PrecService>
  <판례정보일련번호>232199</판례정보일련번호>
  <사건번호><![CDATA[4289행5]]></사건번호>
  <선고일자>42890525</선고일자>
  <법원명>서울고법</법원명>
  <법원종류코드>400202</법원종류코드>
  <사건종류명>일반행정</사건종류명>
</PrecService>""".encode("utf-8")
    result = conv.parse_precedent_xml(dangi_xml)
    assert result is not None
    assert result["선고일자"] == "19560525"
    assert result["사건번호"] == "4289행5"


# ---------------------------------------------------------------------------
# precedent_to_markdown
# ---------------------------------------------------------------------------

def test_precedent_to_markdown_has_valid_frontmatter():
    data = conv.parse_precedent_xml(VALID_XML)
    md = conv.precedent_to_markdown(data)
    assert md.startswith("---\n")
    end = md.index("---\n", 4)
    fm = yaml.safe_load(md[4:end])
    assert isinstance(fm, dict)
    assert len(fm) > 0


def test_precedent_to_markdown_omits_empty_sections():
    data = conv.parse_precedent_xml(EMPTY_SECTIONS_XML)
    md = conv.precedent_to_markdown(data)
    lines = md.splitlines()
    section_lines = [l for l in lines if l.startswith("## ") or l.startswith("### ")]
    empty_section_names = {"판시사항", "판결요지", "참조조문", "참조판례"}
    for line in section_lines:
        heading_text = line.lstrip("# ").strip()
        assert heading_text not in empty_section_names, (
            f"Empty section '{heading_text}' should not appear in output"
        )


def test_precedent_to_markdown_includes_content():
    data = conv.parse_precedent_xml(VALID_XML)
    md = conv.precedent_to_markdown(data)
    assert "원심판결을 파기한다" in md


# ---------------------------------------------------------------------------
# get_precedent_path
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_assigned_paths(monkeypatch):
    """Reset _assigned_paths registry before every test."""
    monkeypatch.setattr(conv, "_assigned_paths", {})
    yield
    monkeypatch.setattr(conv, "_assigned_paths", {})


def test_get_precedent_path_normal():
    data = {"판례정보일련번호": "123456", "사건번호": "2023다12345", "법원명": "대법원",
            "법원종류코드": "400201", "사건종류명": "민사"}
    path = conv.get_precedent_path(data)
    assert path.endswith(".md")
    assert "2023다12345" in path or "123456" in path


def test_get_precedent_path_fallback_to_serial_number():
    data = {"판례정보일련번호": "999999", "사건번호": "", "법원명": "대법원",
            "법원종류코드": "400201", "사건종류명": "민사"}
    path = conv.get_precedent_path(data)
    assert "999999" in path
    assert path.endswith(".md")


def test_get_precedent_path_collision_yields_different_paths():
    data1 = {"판례정보일련번호": "111111", "사건번호": "2020다1234",
              "법원종류코드": "400201", "사건종류명": "민사"}
    data2 = {"판례정보일련번호": "222222", "사건번호": "2020다1234",
              "법원종류코드": "400201", "사건종류명": "민사"}
    path1 = conv.get_precedent_path(data1)
    path2 = conv.get_precedent_path(data2)
    assert path1 != path2


def test_get_precedent_path_caps_long_merged_case_numbers():
    """병합/분리 판결의 수백 건 나열 사건번호가 NAME_MAX를 넘지 않도록 capping."""
    many = ", ".join(str(n) for n in range(700, 1000))
    data = {
        "판례정보일련번호": "123456",
        "사건번호": f"2011고합669, {many} (병합) (분리)",
        "법원종류코드": "400202",
        "사건종류명": "형사",
    }
    path = conv.get_precedent_path(data)
    leaf = path.rsplit("/", 1)[-1]
    assert len(leaf.encode("utf-8")) <= 200, (
        f"leaf exceeds NAME_MAX headroom: {len(leaf.encode('utf-8'))} bytes"
    )
    assert leaf.endswith("_123456.md")


def test_cap_filename_bytes_is_noop_for_short_names():
    assert conv.cap_filename_bytes("2024가합1", "100") == "2024가합1"


def test_cap_filename_bytes_preserves_utf8_char_boundary():
    """Truncation must not split a multi-byte UTF-8 character."""
    stem = "가" * 200  # 600 bytes
    out = conv.cap_filename_bytes(stem, "999")
    out.encode("utf-8")  # would raise if split mid-codepoint
    assert out.endswith("_999")
    assert len(out.encode("utf-8")) <= conv.MAX_FILENAME_STEM_BYTES
