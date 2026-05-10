"""Convert ordinance XML to Markdown with YAML frontmatter."""

import datetime
import re
import unicodedata
from xml.etree import ElementTree

import yaml

from laws.converter import articles_to_markdown

from .config import STORAGE_TYPES, TYPE_CODES
from .failures import quarantine_type
from .jurisdictions import split_jurisdiction


class UnsupportedOrdinanceType(ValueError):
    """Raised when an API type should not be written to the git tree."""


class _QuotedStr(str):
    """str subclass that forces single-quoted YAML output."""


class _OrdinanceDumper(yaml.Dumper):
    """Custom YAML dumper that single-quotes string values."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


_OrdinanceDumper.add_representer(
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


CODE_TO_TYPE = {code: label for label, code in TYPE_CODES.items()}
_INVALID_PATH_CHARS_RE = re.compile(r"[\x00-\x1f\\/:\0\"'<>|?*]")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def normalize_ordinance_type(value: str) -> str:
    return CODE_TO_TYPE.get(value, value)


def _normalize_article_number(value: str) -> str:
    raw = (value or "").strip()
    if raw.isdigit():
        number = int(raw)
        if number and number % 100 == 0:
            return str(number // 100)
        return str(number)
    return raw


def _text(root: ElementTree.Element, path: str) -> str:
    return root.findtext(path, "") or ""


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value or "")).strip()


def _to_date(date_str: str) -> datetime.date | str:
    if not date_str:
        return date_str
    try:
        return datetime.date.fromisoformat(date_str)
    except ValueError:
        return date_str


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


def format_date(date_str: str) -> str:
    raw = _compact_date(date_str)
    if not _is_valid_compact_date(raw):
        return str(date_str or "")
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def _promulgation_date(raw_date: str) -> tuple[datetime.date | str, bool]:
    raw = _compact_date(raw_date)
    if len(raw) == 8 and raw.isdigit() and (not _is_valid_compact_date(raw) or raw < "19700101"):
        return datetime.date(1970, 1, 1), True
    return _to_date(format_date(raw_date)), False


def _truncate_utf8(text: str, max_bytes: int) -> tuple[str, bool]:
    truncated = False
    while len(text.encode("utf-8")) > max_bytes:
        text = text[:-1]
        truncated = True
    return text, truncated


def safe_path_part(value: str, *, max_bytes: int = 180, suffix_on_truncate: str = "") -> str:
    text = _INVALID_PATH_CHARS_RE.sub(" ", normalize_text(value)).strip()
    text = re.sub(r"\s+", " ", text)
    text = text.rstrip(" .")
    suffix = ""
    if suffix_on_truncate:
        suffix_part = safe_path_part(suffix_on_truncate, max_bytes=max_bytes)
        if suffix_part != "_":
            suffix = f"_{suffix_part}"
        while suffix and len(suffix.encode("utf-8")) > max_bytes:
            suffix_part = suffix_part[:-1].rstrip(" .")
            suffix = f"_{suffix_part}" if suffix_part else ""
    if suffix and len(text.encode("utf-8")) > max_bytes:
        text, _ = _truncate_utf8(text, max_bytes - len(suffix.encode("utf-8")))
        text = f"{text.rstrip(' .')}{suffix}" if text.rstrip(" .") else suffix
    else:
        text, _ = _truncate_utf8(text, max_bytes)
        text = text.rstrip(" .")
    if not text:
        return "_"
    stem = text.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        text = f"_{text}"
    return text or "_"


_assigned_paths: dict[str, str] = {}


def reset_path_registry() -> None:
    _assigned_paths.clear()


def build_source_url(ordinance_id: str, name: str) -> str:
    compact_name = name.replace(" ", "")
    return f"https://www.law.go.kr/자치법규/{compact_name}" if compact_name else ""


def _attachment_nodes(root: ElementTree.Element) -> list[dict]:
    attachments = []
    for node in root.findall(".//별표단위"):
        file_link = (node.findtext("별표첨부파일명", "") or "").strip()
        if not file_link:
            continue
        attachments.append({
            "별표번호": (node.findtext("별표번호", "") or "").strip(),
            "별표가지번호": (node.findtext("별표가지번호", "") or "").strip(),
            "별표구분": normalize_text(node.findtext("별표구분", "")) or "별표",
            "제목": normalize_text(node.findtext("별표제목", "")),
            "파일형식": normalize_text(node.findtext("별표첨부파일구분", "")).lower(),
            "파일링크": file_link,
        })
    return attachments


def parse_ordinance_xml(raw_xml: bytes | str) -> dict:
    root = ElementTree.fromstring(raw_xml)
    metadata = {
        "자치법규ID": _text(root, ".//자치법규ID"),
        "자치법규일련번호": _text(root, ".//자치법규일련번호"),
        "자치법규명": normalize_text(_text(root, ".//자치법규명")),
        "자치법규종류": normalize_ordinance_type(_text(root, ".//자치법규종류")),
        "지자체기관명": normalize_text(_text(root, ".//지자체기관명")),
        "공포일자": _text(root, ".//공포일자"),
        "공포번호": _text(root, ".//공포번호"),
        "시행일자": _text(root, ".//시행일자"),
        "제개정구분": normalize_text(_text(root, ".//제개정구분명") or _text(root, ".//제개정구분")),
        "자치법규분야": normalize_text(_text(root, ".//자치법규분야명")),
        "담당부서": normalize_text(_text(root, ".//담당부서명")),
    }
    articles = []
    for jo in [*root.findall(".//조문단위"), *root.findall(".//조")]:
        articles.append({
            "조문번호": _normalize_article_number(jo.findtext("조문번호", "")),
            "조문가지번호": jo.findtext("조문가지번호", ""),
            "조문여부": jo.findtext("조문여부", ""),
            "조문제목": jo.findtext("조문제목", "") or jo.findtext("조제목", ""),
            "조문내용": jo.findtext("조문내용", "") or jo.findtext("조내용", ""),
            "항": [],
        })
    addenda_nodes = root.findall(".//부칙단위") or root.findall(".//부칙")
    addenda = [
        {
            "부칙공포일자": item.findtext("부칙공포일자", ""),
            "부칙공포번호": item.findtext("부칙공포번호", ""),
            "부칙내용": item.findtext("부칙내용", ""),
        }
        for item in addenda_nodes
        if (item.findtext("부칙내용", "") or "").strip()
    ]
    return {
        "metadata": metadata,
        "articles": articles,
        "addenda": addenda,
        "attachments": _attachment_nodes(root),
        "raw_xml": raw_xml,
    }


def build_frontmatter(metadata: dict, attachments: list[dict] | None = None) -> dict:
    ordinance_id = str(metadata.get("자치법규ID", ""))
    ordinance_type = metadata.get("자치법규종류", "")
    if ordinance_type not in STORAGE_TYPES:
        quarantine_type(ordinance_id, ordinance_type)
        raise UnsupportedOrdinanceType(ordinance_type)

    gwangyeok, gicho = split_jurisdiction(metadata.get("지자체기관명", ""))
    prom_date, prom_date_corrected = _promulgation_date(metadata.get("공포일자", ""))
    fm = {
        "자치법규ID": ordinance_id,
        "자치법규일련번호": str(metadata.get("자치법규일련번호", "")),
        "자치법규명": metadata.get("자치법규명", ""),
        "자치법규종류": ordinance_type,
        "지자체기관명": metadata.get("지자체기관명", ""),
        "지자체구분": {"광역": gwangyeok, "기초": gicho},
        "공포일자": prom_date,
        "공포번호": str(metadata.get("공포번호", "")),
        "시행일자": format_date(metadata.get("시행일자", "")),
        "제개정구분": metadata.get("제개정구분", ""),
        "자치법규분야": metadata.get("자치법규분야", ""),
        "담당부서": metadata.get("담당부서", ""),
        "본문출처": metadata.get("body_source", "api-text"),
        "출처": build_source_url(ordinance_id, metadata.get("자치법규명", "")),
        "첨부파일": attachments or [],
        "공포일자보정": prom_date_corrected,
        "공포일자원문": metadata.get("공포일자", ""),
    }
    return fm


def compute_path(metadata: dict, *, use_registry: bool = False) -> str:
    ordinance_type = metadata.get("자치법규종류", "")
    if ordinance_type not in STORAGE_TYPES:
        raise UnsupportedOrdinanceType(ordinance_type)
    gwangyeok, gicho = split_jurisdiction(metadata.get("지자체기관명", ""))
    ordinance_id = safe_path_part(str(metadata.get("자치법규ID", "")))
    name = safe_path_part(metadata.get("자치법규명", ""), suffix_on_truncate=ordinance_id)
    base = f"{safe_path_part(gwangyeok)}/{safe_path_part(gicho)}/{ordinance_type}/{name}/본문.md"
    if not use_registry:
        return base
    existing = _assigned_paths.get(base)
    if existing is None or existing == ordinance_id:
        _assigned_paths[base] = ordinance_id
        return base

    prom_no = safe_path_part(str(metadata.get("공포번호", "")))
    for suffix in (prom_no, ordinance_id, safe_path_part(f"{prom_no}_{ordinance_id}")):
        path = f"{safe_path_part(gwangyeok)}/{safe_path_part(gicho)}/{ordinance_type}/{name}_{suffix}/본문.md"
        existing = _assigned_paths.get(path)
        if existing is None or existing == ordinance_id:
            _assigned_paths[path] = ordinance_id
            return path

    idx = 2
    while True:
        path = f"{safe_path_part(gwangyeok)}/{safe_path_part(gicho)}/{ordinance_type}/{name}_{ordinance_id}_{idx}/본문.md"
        existing = _assigned_paths.get(path)
        if existing is None or existing == ordinance_id:
            _assigned_paths[path] = ordinance_id
            return path
        idx += 1


def ordinance_to_markdown(detail: dict) -> str:
    metadata = detail["metadata"]
    articles_md = articles_to_markdown(detail.get("articles", []))
    has_addenda = any((item.get("부칙내용") or "").strip() for item in detail.get("addenda", []))
    if articles_md.strip() or has_addenda:
        metadata["body_source"] = "api-text"
    else:
        metadata["body_source"] = "parsing-failed"
    fm = build_frontmatter(metadata, detail.get("attachments", []))
    yaml_str = yaml.dump(
        _quote_yaml_strings(fm),
        Dumper=_OrdinanceDumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    name = metadata.get("자치법규명", "")
    body_parts = [f"# {name}", ""]
    if articles_md.strip():
        body_parts.append(articles_md)
    for item in detail.get("addenda", []):
        content = (item.get("부칙내용") or "").strip()
        if content:
            if "## 부칙" not in body_parts:
                body_parts.extend(["## 부칙", ""])
            body_parts.extend([content, ""])
    if len(body_parts) == 2:
        body_parts.append("본문은 첨부파일 또는 원문을 참조하세요.")
    body = "\n".join(body_parts).rstrip()
    return f"---\n{yaml_str}---\n\n{body}\n"


def xml_to_markdown(raw_xml: bytes | str, *, use_registry: bool = False) -> tuple[str, str]:
    detail = parse_ordinance_xml(raw_xml)
    return compute_path(detail["metadata"], use_registry=use_registry), ordinance_to_markdown(detail)
