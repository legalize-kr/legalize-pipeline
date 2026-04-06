"""Convert precedent XML data to Markdown with YAML frontmatter."""

import re
from xml.etree import ElementTree

import yaml

from .config import COURT_TIER_MAP, KNOWN_CASE_TYPES

_15_FIELDS = [
    "판례정보일련번호", "사건명", "사건번호", "선고일자", "선고",
    "법원명", "법원종류코드", "사건종류명", "사건종류코드", "판결유형",
    "판시사항", "판결요지", "참조조문", "참조판례", "판례내용",
]

_COURT_ABBREVS = [
    (re.compile(r"고법$"), "고등법원"),
    (re.compile(r"지법$"), "지방법원"),
    (re.compile(r"행법$"), "행정법원"),
]

_LEADING_PARENS_RE = re.compile(r"^\([^)]+\)")
_REMAINING_PARENS_RE = re.compile(r"\(([^)]+)\)")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

# Tracks assigned paths within an import session to detect collisions.
# Maps path -> 판례정보일련번호
_assigned_paths: dict[str, str] = {}


def reset_path_registry() -> None:
    """Clear the collision registry (call before each import run)."""
    _assigned_paths.clear()


def parse_precedent_xml(raw_xml: bytes) -> dict | None:
    """Parse PrecService XML. Returns None if root tag is not PrecService."""
    root = ElementTree.fromstring(raw_xml)
    if root.tag != "PrecService":
        return None
    return {field: (root.findtext(field) or "") for field in _15_FIELDS}


def normalize_court_name(name: str) -> str:
    """Expand common court abbreviations to their full names."""
    for pattern, replacement in _COURT_ABBREVS:
        name = pattern.sub(replacement, name)
    return name


def get_court_tier(court_code: str, court_name: str = "") -> str:
    """Map court type code to a tier label (대법원 / 하급심 / 미분류)."""
    return COURT_TIER_MAP.get(court_code, "미분류")


def normalize_case_type(case_type: str) -> str:
    """Normalize case type string.

    - Empty → "기타"
    - Comma-separated values → joined with "·"
    - Known types pass through; others → "기타"
    """
    if not case_type:
        return "기타"
    if "," in case_type:
        return case_type.replace(", ", "·").replace(",", "·")
    if case_type in KNOWN_CASE_TYPES:
        return case_type
    return "기타"


def sanitize_case_number(case_no: str) -> str:
    """Sanitize a case number for use as a filesystem path component.

    - Strips leading/trailing whitespace
    - Removes parenthetical court-location prefixes, e.g. (창원)
    - Replaces ", " and "," with "_"
    - Converts remaining parenthetical suffixes to _content, e.g. (참가) → _참가
    """
    s = case_no.strip()
    s = _LEADING_PARENS_RE.sub("", s)
    s = s.replace(", ", "_").replace(",", "_")
    s = _REMAINING_PARENS_RE.sub(r"_\1", s)
    return s


def html_to_markdown(html: str) -> str:
    """Convert HTML snippet to plain Markdown text.

    - Converts <br/> / <br> to newlines
    - Strips all other HTML tags
    - Collapses 3+ consecutive newlines to 2 (max 1 blank line)
    """
    text = _BR_RE.sub("\n", html)
    text = _HTML_TAG_RE.sub("", text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def format_date(date_str: str) -> str | None:
    """Convert YYYYMMDD to YYYY-MM-DD. Returns None for empty or sentinel dates."""
    if not date_str or len(date_str) != 8:
        return None
    if date_str[:4] in ("0000", "0001"):
        return None
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def get_precedent_path(parsed: dict) -> str:
    """Return the relative Markdown file path for a precedent.

    Format: {court_tier}/{case_type}/{sanitized_case_number}.md
    Falls back to 판례정보일련번호 when 사건번호 is empty.
    Handles collisions by appending _{판례정보일련번호}.
    """
    serial = parsed.get("판례정보일련번호", "")
    court_code = parsed.get("법원종류코드", "")
    court_name = parsed.get("법원명", "")
    court_tier = get_court_tier(court_code, court_name)
    case_type = normalize_case_type(parsed.get("사건종류명", ""))

    raw_case_no = parsed.get("사건번호", "").strip()
    filename = sanitize_case_number(raw_case_no) if raw_case_no else serial

    path = f"{case_type}/{court_tier}/{filename}.md"

    existing = _assigned_paths.get(path)
    if existing is not None and existing != serial:
        path = f"{case_type}/{court_tier}/{filename}_{serial}.md"

    _assigned_paths[path] = serial
    return path


def precedent_to_markdown(parsed: dict) -> str:
    """Convert a parsed precedent dict to a complete Markdown document."""
    serial = parsed.get("판례정보일련번호", "")
    case_no = parsed.get("사건번호", "")
    case_name = parsed.get("사건명", "")
    court_name = normalize_court_name(parsed.get("법원명", ""))
    court_code = parsed.get("법원종류코드", "")
    court_tier = get_court_tier(court_code, court_name)
    case_type = normalize_case_type(parsed.get("사건종류명", ""))
    judgment_date = format_date(parsed.get("선고일자", ""))

    fm: dict = {
        "판례일련번호": serial,
        "사건번호": case_no,
        "사건명": case_name,
        "법원명": court_name,
        "법원등급": court_tier,
        "사건종류": case_type,
        "출처": f"https://www.law.go.kr/판례/{serial}",
    }
    if judgment_date is not None:
        fm["선고일자"] = judgment_date

    yaml_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)

    title = case_name or case_no or serial
    body_parts = [f"# {title}", ""]

    sections = [
        ("판시사항", "판시사항"),
        ("판결요지", "판결요지"),
        ("참조조문", "참조조문"),
        ("참조판례", "참조판례"),
        ("판례내용", "판례내용"),
    ]
    for field, heading in sections:
        content = (parsed.get(field) or "").strip()
        if content:
            md_content = html_to_markdown(content)
            if md_content:
                body_parts.extend([f"## {heading}", "", md_content, ""])

    body = "\n".join(body_parts)
    return f"---\n{yaml_str}---\n\n{body}\n"
