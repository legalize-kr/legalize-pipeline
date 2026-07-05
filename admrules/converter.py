"""Convert administrative rule XML to Markdown with YAML frontmatter."""

import datetime
import re
import unicodedata
from pathlib import Path
from xml.etree import ElementTree

import yaml

from core.markdown import escape_accidental_markdown_links

from .config import VALID_ADMRULE_TYPES

_MAX_STEM_BYTES = 180
_INVALID_PATH_CHARS_RE = re.compile(r"[\x00-\x1f\\/:\0\"'<>|?*]")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_ORG_AUTHORITY_PATH = Path(__file__).parent / "data" / "organization_authority.yaml"


def _load_org_authority() -> dict:
    raw = yaml.safe_load(_ORG_AUTHORITY_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"invalid organization authority: {_ORG_AUTHORITY_PATH}")
    return raw


_ORG_AUTHORITY = _load_org_authority()
_MISSING_ORG_TOKENS = {str(value).lower() for value in _ORG_AUTHORITY["missing_tokens"]}
_MINISTRY_RENAME_MAP = {
    str(key): str(value) for key, value in _ORG_AUTHORITY["aliases"].items()
}
_HISTORICAL_ROOT_MINISTRY_SUCCESSORS = {
    str(key): frozenset(str(item) for item in value)
    for key, value in _ORG_AUTHORITY["historical_root_successors"].items()
}
_LEGAL_PARENT_MAP = {
    str(key): str(value) for key, value in _ORG_AUTHORITY["parents"].items()
}
_ROOT_LEVEL_AGENCIES = set(str(value) for value in _ORG_AUTHORITY["roots"]) | set(_LEGAL_PARENT_MAP)
_RULE_TYPE_ROOT_MAP = {
    str(key): str(value) for key, value in _ORG_AUTHORITY["rule_type_roots"].items()
}
_DEPARTMENT_ROOT_OVERRIDES = {
    (str(item["top"]), str(item["department_agency"]))
    for item in _ORG_AUTHORITY["department_root_overrides"]
}
_STALE_DEPARTMENT_ROOTS = {
    (str(item["top"]), str(item["agency"]), str(item["department_agency"]))
    for item in _ORG_AUTHORITY["stale_department_roots"]
}


class _QuotedStr(str):
    """str subclass that forces single-quoted YAML output."""


class _AdmruleDumper(yaml.Dumper):
    """Custom YAML dumper that single-quotes selected string values."""


_AdmruleDumper.add_representer(
    _QuotedStr,
    lambda dumper, value: dumper.represent_scalar(
        "tag:yaml.org,2002:str", value, style="'"
    ),
)


def _quote_yaml_strings(value):
    if isinstance(value, str) and not isinstance(value, _QuotedStr):
        return _QuotedStr(value)
    if isinstance(value, list):
        return [_quote_yaml_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _quote_yaml_strings(item) for key, item in value.items()}
    return value


def normalize_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def _is_missing_org_token(text: str) -> bool:
    return not text or text.lower() in _MISSING_ORG_TOKENS


def format_date(date_str: str) -> str:
    """Convert YYYYMMDD to YYYY-MM-DD format."""
    if not date_str:
        return ""
    raw = _compact_date(date_str)
    if not _is_valid_compact_date(raw):
        return str(date_str)
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def _compact_date(date_str: str) -> str:
    return str(date_str or "").strip().replace(".", "").replace("-", "")


def _is_valid_compact_date(date_str: str) -> bool:
    if len(date_str) != 8 or not date_str.isdigit():
        return False
    try:
        datetime.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
    except ValueError:
        return False
    return True


def _to_date(date_str: str) -> datetime.date | str:
    formatted = format_date(date_str)
    if not formatted:
        return ""
    try:
        return datetime.date.fromisoformat(formatted)
    except ValueError:
        return formatted


def _clamp_issue_date(raw_date: str) -> tuple[datetime.date | str, bool]:
    raw = _compact_date(raw_date)
    if len(raw) == 8 and raw.isdigit() and not _is_valid_compact_date(raw):
        return datetime.date(1970, 1, 1), True
    value = _to_date(raw_date)
    if not isinstance(value, datetime.date):
        return value, False
    if value < datetime.date(1970, 1, 1):
        return datetime.date(1970, 1, 1), True
    return value, False


def _truncate_utf8(text: str, max_bytes: int = _MAX_STEM_BYTES) -> tuple[str, bool]:
    value = text
    truncated = False
    while len(value.encode("utf-8")) > max_bytes:
        value = value[:-1]
        truncated = True
    return value.rstrip(), truncated


def safe_path_part(text: str, *, suffix_on_truncate: str = "") -> str:
    """Normalize a path component while preserving Korean readability."""
    normalized = normalize_nfc(_INVALID_PATH_CHARS_RE.sub(" ", text)).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.rstrip(" .")
    suffix = ""
    if suffix_on_truncate:
        suffix_part = safe_path_part(suffix_on_truncate)
        if suffix_part != "_":
            suffix = f"_{suffix_part}"
        while suffix and len(suffix.encode("utf-8")) > _MAX_STEM_BYTES:
            suffix_part = suffix_part[:-1].rstrip(" .")
            suffix = f"_{suffix_part}" if suffix_part else ""
    if suffix and len(normalized.encode("utf-8")) > _MAX_STEM_BYTES:
        normalized, _ = _truncate_utf8(normalized, _MAX_STEM_BYTES - len(suffix.encode("utf-8")))
        normalized = f"{normalized.rstrip(' .')}{suffix}" if normalized.rstrip(" .") else suffix
    else:
        normalized, _ = _truncate_utf8(normalized)
        normalized = normalized.rstrip(" .")
    if not normalized:
        return "_"
    stem = normalized.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        normalized = f"_{normalized}"
    return normalized


def _normalize_ministry_text(text: str, fallback: str = "") -> str:
    normalized = normalize_nfc(text).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized) or _is_missing_org_token(normalized):
        normalized = normalize_nfc(fallback).strip()
    normalized = normalized.replace("10.29이태원", "10·29이태원")
    normalized = re.sub(r"\s+", " ", normalized)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized) or _is_missing_org_token(normalized):
        return ""
    return normalized


def normalize_ministry_name(text: str, fallback: str = "") -> str:
    """Normalize observed ministry-name spelling drift for path stability."""
    normalized = _normalize_ministry_text(text, fallback)
    if not normalized:
        return ""
    return _MINISTRY_RENAME_MAP.get(normalized, normalized)


def _split_department_org_name(text: str) -> tuple[str, str]:
    normalized = normalize_nfc(text).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    if "(" not in normalized:
        return normalize_ministry_name(normalized), ""
    outer, inner = normalized.split("(", 1)
    inner = inner[:-1] if inner.endswith(")") else inner
    return normalize_ministry_name(outer), normalize_ministry_name(inner)


def _split_parent_agency_chain(parent: str, agency: str) -> tuple[str, str] | None:
    if not agency or parent == agency or not parent.endswith(agency):
        return None
    prefix = parent[: -len(agency)].strip()
    if not prefix:
        return None
    return normalize_ministry_name(prefix), agency


def resolve_ministry_names(
    ministry: str,
    parent: str = "",
    department_org: str = "",
    rule_type: str = "",
) -> tuple[str, str]:
    """Return ``(top-level ministry, issuing agency)`` for path/frontmatter use."""
    original_agency = _normalize_ministry_text(ministry, parent)
    agency = normalize_ministry_name(ministry, parent)
    normalized_parent = normalize_ministry_name(parent)
    department_agency, department_unit = _split_department_org_name(department_org)
    root_from_rule_type = _RULE_TYPE_ROOT_MAP.get(normalize_ministry_name(rule_type) or rule_type)
    top = normalized_parent or agency

    if _should_use_current_department_root_for_stale_ministry(
        top, agency, department_agency
    ):
        agency = top
    elif agency == top and _should_use_department_root(top, department_agency):
        top = department_agency
        agency = department_agency
    elif _should_collapse_historical_root_ministry(top, original_agency or agency):
        agency = top
    elif parent_chain := _split_parent_agency_chain(normalized_parent, department_agency):
        top, chain_agency = parent_chain
        if not agency or agency in {department_unit, normalized_parent}:
            agency = chain_agency
    elif agency == department_agency and agency in _ROOT_LEVEL_AGENCIES:
        top = agency
    elif agency == department_unit and department_agency:
        agency = department_agency

    if not top:
        top = agency or root_from_rule_type or ""
    if not agency:
        agency = top or root_from_rule_type or ""
    return top, agency


def _should_collapse_historical_root_ministry(top: str, agency: str) -> bool:
    return top in _HISTORICAL_ROOT_MINISTRY_SUCCESSORS.get(agency, frozenset())


def _should_use_current_department_root_for_stale_ministry(
    top: str, agency: str, department_agency: str
) -> bool:
    return (top, agency, department_agency) in _STALE_DEPARTMENT_ROOTS


def _should_use_department_root(top: str, department_agency: str) -> bool:
    if not department_agency or department_agency not in _ROOT_LEVEL_AGENCIES:
        return False
    return top not in _ROOT_LEVEL_AGENCIES or (top, department_agency) in _DEPARTMENT_ROOT_OVERRIDES


def _build_legal_org_path(agency: str) -> list[str]:
    normalized = normalize_ministry_name(agency)
    if not normalized:
        return []
    parent = _LEGAL_PARENT_MAP.get(normalized)
    if not parent:
        return [normalized]
    path = _build_legal_org_path(parent)
    if normalized not in path:
        path.append(normalized)
    return path


def resolve_org_path(top: str, agency: str) -> list[str]:
    """Return the legal organization path used before rule type/name components."""
    top = normalize_ministry_name(top)
    agency = normalize_ministry_name(agency)
    if not agency:
        return _build_legal_org_path(top)

    parent = _LEGAL_PARENT_MAP.get(agency)
    if parent and top not in {agency, parent} and agency in _ROOT_LEVEL_AGENCIES:
        return _build_legal_org_path(agency)

    path = _build_legal_org_path(top)
    if agency != top and agency not in path:
        path.append(agency)
    return path


_assigned_paths: dict[str, str] = {}


def admrule_identity(metadata: dict) -> str:
    """Return the revision identity used for path continuity."""
    return str(metadata.get("행정규칙ID") or metadata.get("행정규칙일련번호") or "").strip()


def is_repeal_revision(metadata: dict) -> bool:
    """Return whether this revision repeals the administrative rule."""
    return "폐지" in str(metadata.get("제개정구분", ""))


def reset_path_registry() -> None:
    _assigned_paths.clear()


def get_admrule_path(metadata: dict) -> str:
    """Return ``{상위기관}/{소관기관}/{종류}/{행정규칙명}/본문.md``."""
    top, agency = resolve_ministry_names(
        metadata.get("소관부처명", ""),
        metadata.get("상위기관명") or metadata.get("상위부처명", ""),
        metadata.get("담당부서기관명", ""),
        metadata.get("행정규칙종류", ""),
    )
    org_path = metadata.get("기관경로") or resolve_org_path(top, agency)
    org_parts = [safe_path_part(part) for part in org_path]
    if not org_parts:
        org_parts = [safe_path_part(top or agency or "_미분류")]
    if len(org_parts) == 1 and agency == top:
        org_parts.append("_본부")
    serial = str(metadata.get("행정규칙일련번호", ""))
    identity = admrule_identity(metadata) or serial
    rule_type = safe_path_part(metadata.get("행정규칙종류", ""))
    name = safe_path_part(metadata.get("행정규칙명", ""), suffix_on_truncate=serial)
    org_prefix = "/".join(org_parts)
    base = f"{org_prefix}/{rule_type}/{name}/본문.md"
    existing = _assigned_paths.get(base)
    if existing is None or existing == identity:
        _assigned_paths[base] = identity
        return base

    issue_no = str(metadata.get("발령번호", ""))
    first_suffix = safe_path_part(issue_no or serial)
    for suffix in (
        first_suffix,
        safe_path_part(serial),
        safe_path_part(f"{issue_no}_{serial}"),
    ):
        path = f"{org_prefix}/{rule_type}/{name}_{suffix}/본문.md"
        existing = _assigned_paths.get(path)
        if existing is None or existing == identity:
            _assigned_paths[path] = identity
            return path

    idx = 2
    while True:
        path = f"{org_prefix}/{rule_type}/{name}_{safe_path_part(serial)}_{idx}/본문.md"
        existing = _assigned_paths.get(path)
        if existing is None or existing == identity:
            _assigned_paths[path] = identity
            return path
        idx += 1


def _find_first(root: ElementTree.Element, names: tuple[str, ...]) -> str:
    for name in names:
        value = root.findtext(f".//{name}")
        if value:
            return value.strip()
    return ""


def _absolute_law_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("/"):
        return f"https://www.law.go.kr{value}"
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"https://www.law.go.kr/{value}"


def _metadata_from_xml(root: ElementTree.Element) -> dict:
    rule_type = _find_first(root, ("행정규칙종류", "행정규칙종류명"))
    raw_ministry = normalize_nfc(_find_first(root, ("소관부처명",)))
    raw_parent = normalize_nfc(_find_first(root, ("상위부처명",)))
    raw_department_org = normalize_nfc(_find_first(root, ("담당부서기관명",)))
    raw_top_ministry, raw_resolved_ministry = resolve_ministry_names(
        raw_ministry,
        raw_parent,
        raw_department_org,
        rule_type,
    )
    org_path = resolve_org_path(raw_top_ministry, raw_resolved_ministry)
    top_ministry = org_path[0] if org_path else raw_top_ministry
    ministry = org_path[-1] if org_path else raw_resolved_ministry
    if not top_ministry and not ministry:
        top_ministry = "_미분류"
        ministry = "_미분류"
        org_path = ["_미분류"]
    metadata = {
        "행정규칙ID": _find_first(root, ("행정규칙ID",)),
        "행정규칙일련번호": _find_first(root, ("행정규칙일련번호", "admrulSeq", "ID")),
        "행정규칙명": normalize_nfc(_find_first(root, ("행정규칙명", "행정규칙명_한글"))),
        "행정규칙종류": normalize_nfc(rule_type),
        "상위기관명": top_ministry,
        "소관부처명": ministry,
        "기관경로": org_path,
        "기관코드": _find_first(root, ("기관코드", "소관부처코드")),
        "발령번호": _find_first(root, ("발령번호",)),
        "발령일자": _find_first(root, ("발령일자",)),
        "시행일자": _find_first(root, ("시행일자",)),
        "제개정구분": _find_first(root, ("제개정구분명",)),
        "제개정구분코드": _find_first(root, ("제개정구분코드",)),
        "현행연혁구분": _find_first(root, ("현행연혁구분",)),
        "현행여부": _find_first(root, ("현행여부",)),
    }
    if raw_ministry and not _is_missing_org_token(raw_ministry.strip()) and raw_ministry != ministry:
        metadata["소관부처명_원문"] = raw_ministry
    return metadata


def _attachment_nodes(root: ElementTree.Element) -> list[dict]:
    attachments = []
    nodes = []
    for bylaw in root.findall(".//별표"):
        units = bylaw.findall(".//별표단위")
        nodes.extend(units or [bylaw])
    if not nodes:
        nodes.extend(root.findall(".//별표단위"))

    for idx, node in enumerate(nodes, start=1):
        file_link = _absolute_law_url(_find_first(node, ("별표서식파일링크", "별표파일링크")))
        pdf_link = _absolute_law_url(_find_first(node, ("별표서식PDF파일링크", "별표PDF파일링크")))
        if not file_link and not pdf_link:
            continue
        attachment = {
            "별표번호": _find_first(node, ("별표번호",)) or f"별표 {idx}",
            "별표가지번호": _find_first(node, ("별표가지번호",)),
            "별표구분": _find_first(node, ("별표구분",)) or "별표",
            "제목": normalize_nfc(_find_first(node, ("별표제목", "별표명"))),
        }
        if file_link:
            attachment["파일링크"] = file_link
        if pdf_link:
            attachment["PDF링크"] = pdf_link
        attachments.append(attachment)
    return attachments


def build_frontmatter(metadata: dict, attachments: list[dict] | None = None) -> dict:
    issue_date, clamped = _clamp_issue_date(metadata.get("발령일자", ""))
    title = normalize_nfc(metadata.get("행정규칙명", ""))
    rule_type = normalize_nfc(metadata.get("행정규칙종류", ""))
    if rule_type not in VALID_ADMRULE_TYPES:
        rule_type = metadata.get("행정규칙종류", "")

    source_url = metadata.get("source_url") or (
        f"https://www.law.go.kr/행정규칙/{title.replace(' ', '')}" if title else ""
    )

    fm = {
        "행정규칙ID": _QuotedStr(str(metadata.get("행정규칙ID", ""))),
        "행정규칙일련번호": _QuotedStr(str(metadata.get("행정규칙일련번호", ""))),
        "행정규칙명": title,
        "행정규칙종류": rule_type,
        "상위기관명": normalize_nfc(metadata.get("상위기관명", "")),
        "소관부처명": normalize_nfc(metadata.get("소관부처명", "")),
        "기관경로": [normalize_nfc(part) for part in metadata.get("기관경로", [])],
        **(
            {"소관부처명_원문": normalize_nfc(metadata["소관부처명_원문"])}
            if metadata.get("소관부처명_원문")
            else {}
        ),
        "기관코드": metadata.get("기관코드") or None,
        "발령번호": _QuotedStr(str(metadata.get("발령번호", ""))),
        "발령일자": issue_date,
        "시행일자": _to_date(metadata.get("시행일자", "")),
        "제개정구분": metadata.get("제개정구분", ""),
        "제개정구분코드": _QuotedStr(str(metadata.get("제개정구분코드", ""))),
        "현행연혁구분": metadata.get("현행연혁구분", ""),
        "현행여부": _QuotedStr(str(metadata.get("현행여부", ""))),
        "본문출처": metadata.get("body_source") or "api-text",
        "출처": source_url,
        "첨부파일": attachments or [],
        "발령일자보정": clamped,
        "발령일자원문": str(metadata.get("발령일자", "")),
    }
    return fm


def _plain_text(root: ElementTree.Element) -> str:
    parts = []
    for tag in ("조문내용", "본문", "내용"):
        for node in root.findall(f".//{tag}"):
            if node.text and node.text.strip():
                parts.append(normalize_nfc(node.text.strip()))
    return escape_accidental_markdown_links("\n\n".join(parts))


def xml_to_markdown(raw_xml: bytes | str, attachment_metadata: list[dict] | None = None) -> str:
    root = ElementTree.fromstring(raw_xml)
    metadata = _metadata_from_xml(root)
    attachments = attachment_metadata if attachment_metadata is not None else _attachment_nodes(root)
    body = _plain_text(root)
    if not body:
        metadata["body_source"] = "parsing-failed"
        body = "본문은 국가법령정보센터 원문 또는 첨부파일을 참조하세요."

    frontmatter = build_frontmatter(metadata, attachments)
    yaml_text = yaml.dump(
        _quote_yaml_strings(frontmatter),
        Dumper=_AdmruleDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{yaml_text}\n---\n\n{body.strip()}\n"
