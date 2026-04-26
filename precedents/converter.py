"""Convert precedent XML data to Markdown with YAML frontmatter."""

import html
import re
import unicodedata
from xml.etree import ElementTree

import yaml

from .config import COURT_TIER_MAP, KNOWN_CASE_TYPES

# Filename grammar slot separator. Composite key:
#   {NFC(법원명)}{SEP}{선고일자|0000-00-00}{SEP}{sanitize(사건번호)|serial}.md
# Decided by `preflight_filename_audit` measurement (7) on the full cache:
#   - `__` intrudes in 18 records (e.g. "2008나56_본소__제주2008나63_반소"),
#   - `~` intrudes in 2 records,
#   - `--` intrudes in 0 records → CHOSEN.
# Mirrored in compiler-for-precedent/src/render.rs and cli-tools (lockstep PR).
SEP = "--"

# Sentinel for missing 선고일자. Keeps grammar (3 slots, ISO date shape) intact.
MISSING_DATE_SENTINEL = "0000-00-00"
# Sentinel for missing 법원명. Triggers serial fallback in CASENO slot.
MISSING_COURT_SENTINEL = "미상법원"

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
_MULTI_SPACE_RE = re.compile(r"[ \u00A0]{3,}")

# Dangi era → Gregorian offset (CE = Dangi − 2333).
# Older upstream precedents (e.g. 1956) arrive with 4-digit 단기 years (42890525)
# instead of 서기 (19560525); normalize once at parse time so sorting, commit
# timestamps, and frontmatter all agree on Gregorian.
_DANGI_EPOCH_OFFSET = 2333
_DANGI_YEAR_MIN = 4200  # ≈ 1867 CE, conservative floor for realistic legal records
_DANGI_YEAR_MAX = 4330  # ≈ 1997 CE; newer upstream records are always Gregorian

# Tracks assigned paths within an import session to detect collisions.
# Maps path -> 판례정보일련번호
_assigned_paths: dict[str, str] = {}


def reset_path_registry() -> None:
    """Clear the collision registry (call before each import run)."""
    _assigned_paths.clear()


def normalize_dangi_yyyymmdd(date: str) -> str:
    """Convert a 단기(Dangi) YYYYMMDD year to 서기(Gregorian); pass through otherwise."""
    if len(date) != 8 or not date.isdigit():
        return date
    year = int(date[:4])
    if not (_DANGI_YEAR_MIN <= year <= _DANGI_YEAR_MAX):
        return date
    return f"{year - _DANGI_EPOCH_OFFSET:04d}{date[4:]}"


def parse_precedent_xml(raw_xml: bytes) -> dict | None:
    """Parse PrecService XML. Returns None if root tag is not PrecService."""
    root = ElementTree.fromstring(raw_xml)
    if root.tag != "PrecService":
        return None
    parsed = {field: (root.findtext(field) or "") for field in _15_FIELDS}
    parsed["선고일자"] = normalize_dangi_yyyymmdd(parsed["선고일자"])
    return parsed


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


def _unguarded_sanitize(case_no: str) -> str:
    """Sanitize without the SEP-collision assert.

    Used by `preflight_filename_audit` to *measure* SEP intrusion in raw data
    (the assert would defeat the measurement). All production paths must call
    `sanitize_case_number` instead.
    """
    s = case_no.strip()
    s = _LEADING_PARENS_RE.sub("", s)
    s = s.replace(", ", "_").replace(",", "_")
    s = _REMAINING_PARENS_RE.sub(r"_\1", s)
    return unicodedata.normalize("NFC", s)


def sanitize_case_number(case_no: str) -> str:
    """Sanitize a case number for use as a filesystem path component.

    - Strips leading/trailing whitespace
    - Removes parenthetical court-location prefixes, e.g. (창원)
    - Replaces ", " and "," with "_"
    - Converts remaining parenthetical suffixes to _content, e.g. (참가) → _참가
    - NFC-normalizes the result.
    - Runtime guard: SEP must not occur in the output (would break the slot
      separator grammar in `compose_filename_stem`). If raw input ever produces
      a SEP-collision, fail-loud here so we swap SEP via preflight gate.
    """
    s = _unguarded_sanitize(case_no)
    assert SEP not in s, (
        f"sanitize_case_number produced SEP-collision: {s!r}; "
        f"swap SEP via preflight gate (Plan §1.1.1)"
    )
    return s


# Max UTF-8 byte length for a filename stem. Leaves headroom for ".md" and the
# collision "_{serial}" suffix inside the 255-byte NAME_MAX limit on APFS/ext4.
MAX_FILENAME_STEM_BYTES = 180


def cap_caseno_slot(court: str, date: str, caseno: str, serial: str) -> str:
    """Cap the composite stem by truncating only the CASENO slot.

    The composite grammar is `{COURT}{SEP}{DATE}{SEP}{CASENO}`. When the stem
    exceeds `MAX_FILENAME_STEM_BYTES`, only the CASENO slot is truncated so the
    SEP-delimited grammar always parses (court+date stay intact).

    On truncation, append `_{serial}` to the truncated CASENO so the result
    remains globally unique and traceable. Truncation respects UTF-8 character
    boundaries.
    """
    prefix = f"{court}{SEP}{date}{SEP}"
    suffix = f"_{serial}"
    available = (
        MAX_FILENAME_STEM_BYTES
        - len(prefix.encode("utf-8"))
        - len(suffix.encode("utf-8"))
    )
    encoded_caseno = caseno.encode("utf-8")
    if available <= 0:
        # Pathological: court+date alone exceed the budget. Fall back to serial.
        return f"{prefix}{serial}"
    if len(encoded_caseno) <= available:
        return f"{prefix}{caseno}"
    truncated = encoded_caseno[:available].decode("utf-8", errors="ignore")
    return f"{prefix}{truncated}{suffix}"


def compose_filename_stem(
    court_name: str,
    judgment_date: str | None,
    case_no: str,
    serial: str,
) -> str:
    """Compose the unique filename stem from (법원명, 선고일자, 사건번호, serial).

    Inputs:
      - `court_name`: raw 법원명. Empty/whitespace → `미상법원` and CASENO is
        forced to serial (fallback prevents empty grammar slots).
      - `judgment_date`: pre-formatted ISO date (`YYYY-MM-DD`) or None.
        None → `0000-00-00` sentinel.
      - `case_no`: raw 사건번호. Empty → serial. NFC-normalized via
        `sanitize_case_number`.
      - `serial`: 판례정보일련번호 (used for fallback / cap suffix).

    Output: `{COURT}{SEP}{DATE}{SEP}{CASENO}` — UTF-8 byte length capped at
    `MAX_FILENAME_STEM_BYTES` via `cap_caseno_slot` (truncates CASENO only).

    All components are NFC-normalized. Deterministic: same input → same output.
    """
    raw_court = (court_name or "").strip()
    court_missing = not raw_court
    court = MISSING_COURT_SENTINEL if court_missing else normalize_court_name(raw_court)
    court = unicodedata.normalize("NFC", court)

    date = judgment_date or MISSING_DATE_SENTINEL

    raw_caseno = (case_no or "").strip()
    if court_missing or not raw_caseno:
        caseno = serial
    else:
        caseno = sanitize_case_number(raw_caseno) or serial
    caseno = unicodedata.normalize("NFC", caseno)

    stem = f"{court}{SEP}{date}{SEP}{caseno}"
    if len(stem.encode("utf-8")) <= MAX_FILENAME_STEM_BYTES:
        return stem
    return cap_caseno_slot(court, date, caseno, serial)


def cap_filename_bytes(filename: str, serial: str) -> str:
    """Cap a filename stem to MAX_FILENAME_STEM_BYTES bytes (UTF-8).

    병합/분리 형사 판결은 `사건번호` 한 필드에 수십~수백 개의 사건번호가
    쉼표로 나열되어 들어오는 경우가 있어, 그대로 파일명으로 쓰면 macOS/APFS의
    255-byte NAME_MAX 제한을 초과해 `git checkout`이 실패한다. 길이를 넘으면
    UTF-8 문자 경계에서 잘라낸 뒤 `_{serial}`을 붙여 고유성과 추적성을 보존한다.
    """
    encoded = filename.encode("utf-8")
    if len(encoded) <= MAX_FILENAME_STEM_BYTES:
        return filename
    suffix = f"_{serial}"
    keep = MAX_FILENAME_STEM_BYTES - len(suffix.encode("utf-8"))
    truncated = encoded[:keep].decode("utf-8", errors="ignore")
    return f"{truncated}{suffix}"


def normalize_case_name(text: str) -> str:
    """Inline whitespace normalization for 사건명 (frontmatter + H1 title).

    - Converts <br/> / <br> to a single space (keeps the name single-line)
    - Strips all other HTML tags
    - Unescapes HTML entities
    - Collapses runs of 3+ spaces/NBSPs to a single space
    """
    text = _BR_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    return text.strip()


def html_to_markdown(text: str) -> str:
    """Convert HTML snippet to plain Markdown text.

    - Converts <br/> / <br> to newlines
    - Strips all other HTML tags
    - Unescapes HTML entities (e.g. &amp; → &, &nbsp; → NBSP)
    - Collapses 3+ consecutive newlines to 2 (max 1 blank line)
    - Collapses 3+ consecutive spaces/NBSP runs to a single space
    """
    text = _BR_RE.sub("\n", text)
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
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

    Format: {case_type}/{court_tier}/{COURT}{SEP}{DATE}{SEP}{CASENO}.md
    Composite key (court+date+caseno) is unique across the whole dataset, so
    same-stem collisions should be rare. When they do occur (e.g. truly
    duplicated upstream record), `_{판례정보일련번호}` is appended.
    """
    serial = parsed.get("판례정보일련번호", "")
    court_code = parsed.get("법원종류코드", "")
    court_name = parsed.get("법원명", "")
    court_tier = get_court_tier(court_code, court_name)
    case_type = normalize_case_type(parsed.get("사건종류명", ""))
    judgment_date = format_date(parsed.get("선고일자", ""))

    stem = compose_filename_stem(
        court_name=court_name,
        judgment_date=judgment_date,
        case_no=parsed.get("사건번호", ""),
        serial=serial,
    )

    path = unicodedata.normalize("NFC", f"{case_type}/{court_tier}/{stem}.md")

    existing = _assigned_paths.get(path)
    if existing is not None and existing != serial:
        path = unicodedata.normalize(
            "NFC", f"{case_type}/{court_tier}/{stem}_{serial}.md"
        )

    _assigned_paths[path] = serial
    return path


def precedent_to_markdown(parsed: dict) -> str:
    """Convert a parsed precedent dict to a complete Markdown document."""
    serial = parsed.get("판례정보일련번호", "")
    case_no = parsed.get("사건번호", "")
    case_name = normalize_case_name(parsed.get("사건명", ""))
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
        "출처": f"https://www.law.go.kr/LSW/precInfoP.do?precSeq={serial}",
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
