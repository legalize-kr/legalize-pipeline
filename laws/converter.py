"""Convert law data to Markdown with YAML frontmatter."""

import re

import yaml

from .config import CHILD_SUFFIXES, KR_DIR, TYPE_TO_FILENAME

# Unicode normalization map for middle dots
_DOT_NORMALIZE = str.maketrans({
    "\u00B7": "\u318D",  # Middle Dot -> Hangul Letter Araea
    "\u30FB": "\u318D",  # Katakana Middle Dot -> Hangul Letter Araea
    "\uFF65": "\u318D",  # Halfwidth Katakana Middle Dot -> Hangul Letter Araea
})


def normalize_law_name(name: str) -> str:
    """Normalize Unicode dot variants in law names to canonical U+318D."""
    return name.translate(_DOT_NORMALIZE)


def parse_departments(raw: str) -> list[str]:
    """Parse multi-department string into a list."""
    if not raw:
        return []
    return [dept.strip() for dept in raw.split(",") if dept.strip()]


def format_date(date_str: str) -> str:
    """Convert YYYYMMDD to YYYY-MM-DD format."""
    if not date_str or len(date_str) != 8:
        return date_str
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def get_group_and_filename(law_name: str, law_type: str) -> tuple[str, str]:
    """Determine directory group name and filename for a law.

    Returns: (group_name, filename_without_ext)

    Examples:
        ("민법", "법률")           -> ("민법", "법률")
        ("민법 시행령", "대통령령") -> ("민법", "시행령")
        ("검사인사규정", "대통령령") -> ("검사인사규정", "대통령령")
    """
    normalized = normalize_law_name(law_name)

    for suffix, filename in CHILD_SUFFIXES:
        if normalized.endswith(suffix):
            group = normalized[:-len(suffix)].replace(" ", "")
            return group, filename

    filename = TYPE_TO_FILENAME.get(law_type, law_type)
    return normalized.replace(" ", ""), filename


# Tracks assigned paths during an import session to detect collisions.
# Maps path -> (law_name, law_type)
_assigned_paths: dict[str, tuple[str, str]] = {}


def reset_path_registry():
    """Clear the collision registry (call before each import run)."""
    _assigned_paths.clear()


def get_law_path(law_name: str, law_type: str) -> str:
    """Get the relative file path for a law (e.g., kr/민법/법률.md).

    Handles collisions: if two laws map to the same path (e.g., multiple
    시행규칙 from different ministries), appends a type qualifier like
    시행규칙(총리령).md / 시행규칙(부령).md.

    Also checks the filesystem for pre-existing qualified paths from
    previous import sessions (e.g., rebuild), so incremental updates
    write to the correct file.
    """
    group, filename = get_group_and_filename(law_name, law_type)
    qualified = f"kr/{group}/{filename}({law_type}).md"

    # If a qualified path already exists on disk, use it
    if (KR_DIR.parent / qualified).exists():
        _assigned_paths[qualified] = (law_name, law_type)
        return qualified

    path = f"kr/{group}/{filename}.md"

    existing = _assigned_paths.get(path)
    if existing is not None and existing != (law_name, law_type):
        _assigned_paths[qualified] = (law_name, law_type)
        return qualified

    _assigned_paths[path] = (law_name, law_type)
    return path


def build_frontmatter(metadata: dict) -> dict:
    """Build YAML frontmatter dict from metadata."""
    raw_name = metadata.get("법령명한글", "")
    normalized_name = normalize_law_name(raw_name)

    fm = {
        "제목": normalized_name,
        "법령MST": int(metadata.get("법령MST", 0)) if metadata.get("법령MST", "").isdigit() else metadata.get("법령MST", ""),
        "법령ID": metadata.get("법령ID", ""),
        "법령구분": metadata.get("법령구분", ""),
        "법령구분코드": metadata.get("법령구분코드", ""),
        "소관부처": parse_departments(metadata.get("소관부처명", "")),
        "공포일자": format_date(metadata.get("공포일자", "")),
        "공포번호": metadata.get("공포번호", ""),
        "시행일자": format_date(metadata.get("시행일자", "")),
        "법령분야": metadata.get("법령분야", ""),
        "상태": "시행",
        "출처": f"https://www.law.go.kr/법령/{normalized_name.replace(' ', '')}",
    }

    if normalized_name != raw_name:
        fm["원본제목"] = raw_name

    return fm


# Regex to detect structural headings (편/장/절/관) and capture the type
_STRUCTURE_RE = re.compile(
    r"^제\d+(?:의\d+)?(편|장|절|관)\s*"
)

# Regex to strip 호 prefix: "1." or "1의2." etc.
_HO_PREFIX_RE = re.compile(r"^\d+(?:의\d+)?\.\s*")

# Regex to strip 목 prefix: "가." or "가의2." etc.
_MOK_PREFIX_RE = re.compile(r"^[가-힣](?:의\d+)?\.\s*")


def _normalize_ws(text: str) -> str:
    """Collapse runs of horizontal whitespace to a single space."""
    return re.sub(r"[ \t]+", " ", text).strip()

# Heading level by structure type
_STRUCTURE_LEVEL = {"편": "#", "장": "##", "절": "###", "관": "####"}


def _dedent_content(text: str) -> str:
    """Remove common leading whitespace, preserving relative indentation.

    Unlike textwrap.dedent, uses the minimum *non-zero* indent so that
    already-flush lines stay flush and deeper lines keep relative depth.
    """
    lines = text.splitlines()
    min_indent = None
    for line in lines:
        stripped = line.lstrip()
        if stripped:
            indent = len(line) - len(stripped)
            if indent > 0 and (min_indent is None or indent < min_indent):
                min_indent = indent
    if not min_indent:
        return text
    result = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped:
            result.append("")
        else:
            indent = len(line) - len(stripped)
            new_indent = max(0, indent - min_indent)
            result.append(" " * new_indent + stripped)
    return "\n".join(result)


def articles_to_markdown(articles: list[dict]) -> str:
    """Convert article list to Markdown text."""
    lines = []
    for article in articles:
        number = article.get("조문번호", "")
        title = article.get("조문제목", "")
        content = (article.get("조문내용") or "").strip().translate(_DOT_NORMALIZE)

        # Detect structural headings (편/장/절/관)
        match = _STRUCTURE_RE.match(content) if not title and content else None
        if match:
            level = _STRUCTURE_LEVEL[match.group(1)]
            lines.append(f"{level} {content}")
            lines.append("")
            continue

        heading = f"##### 제{number}조"
        if title:
            heading += f" ({title})"
        lines.append(heading)
        lines.append("")

        if content:
            # Strip "제N조(제목)" prefix — already in the heading
            cleaned = re.sub(r"^제\d+조(?:의\d+)?\s*(?:\([^)]*\)\s*)?", "", content)
            if cleaned:
                lines.append(cleaned)
                lines.append("")

        for para in article.get("항", []):
            para_num = para.get("항번호", "")
            para_content = para.get("항내용", "").translate(_DOT_NORMALIZE)
            if para_content:
                # Strip leading ①②… — already shown as bold prefix
                stripped = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]\s*", "", para_content.strip())
                prefix = f"**{para_num}**" if para_num else ""
                lines.append(f"{prefix} {stripped}")
                lines.append("")

            for subpara in para.get("호", []):
                sub_num = subpara.get("호번호", "").strip().rstrip(".")
                sub_content = subpara.get("호내용", "").translate(_DOT_NORMALIZE)
                if sub_content:
                    stripped = _HO_PREFIX_RE.sub("", sub_content.strip())
                    stripped = _normalize_ws(stripped)
                    if sub_num:
                        lines.append(f"  {sub_num}\\. {stripped}")
                    else:
                        lines.append(f"  {stripped}")

                for item in subpara.get("목", []):
                    item_num = item.get("목번호", "").strip().rstrip(".")
                    item_content = item.get("목내용", "").translate(_DOT_NORMALIZE)
                    if item_content:
                        stripped = _MOK_PREFIX_RE.sub("", item_content.strip())
                        stripped = _normalize_ws(stripped)
                        if item_num:
                            lines.append(f"    {item_num}\\. {stripped}")
                        else:
                            lines.append(f"    {stripped}")

            if para.get("호"):
                lines.append("")

    return "\n".join(lines)


def law_to_markdown(detail: dict) -> str:
    """Convert a full law detail response to a complete Markdown document."""
    metadata = detail["metadata"]
    frontmatter = build_frontmatter(metadata)

    yaml_str = yaml.dump(
        frontmatter,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )

    normalized_name = normalize_law_name(metadata.get("법령명한글", ""))
    body_parts = [f"# {normalized_name}", ""]

    articles_md = articles_to_markdown(detail.get("articles", []))
    if articles_md:
        body_parts.append(articles_md)

    addenda = detail.get("addenda", [])
    if addenda:
        body_parts.append("## 부칙")
        body_parts.append("")
        for item in addenda:
            content = (item.get("부칙내용") or "").strip()
            if content:
                body_parts.append(_dedent_content(content))
                body_parts.append("")

    body = "\n".join(body_parts)
    return f"---\n{yaml_str}---\n\n{body}\n"
