"""Validate administrative rule Markdown files and invariants."""

import datetime
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .config import BINARY_SUFFIXES, BODY_SOURCES, VALID_ADMRULE_TYPES

REQUIRED_FIELDS = [
    "행정규칙ID",
    "행정규칙일련번호",
    "행정규칙명",
    "행정규칙종류",
    "상위기관명",
    "소관부처명",
    "발령일자",
    "본문출처",
    "출처",
    "첨부파일",
]

FORBIDDEN_FRONTMATTER_FIELDS = {
    "source_url",
    "body_source",
    "hwp_sha256",
    "attachments_hwp",
    "epoch_clamped",
    "발령일자_raw",
}


def _is_law_go_kr_url(url: str) -> bool:
    if url.startswith("/"):
        return True
    host = urlparse(url).hostname or ""
    return host == "law.go.kr" or host.endswith(".law.go.kr")


def _frontmatter_and_body(text: str) -> tuple[dict | None, str, list[str]]:
    if not text.startswith("---"):
        return None, "", ["No YAML frontmatter"]
    try:
        yaml_text, body = text.removeprefix("---\n").split("\n---\n", 1)
    except ValueError:
        return None, "", ["Unterminated YAML frontmatter"]
    try:
        fm = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        return None, "", [f"Invalid YAML: {e}"]
    if not isinstance(fm, dict):
        return None, "", ["Frontmatter is not a dict"]
    return fm, body.strip(), []


def validate_frontmatter(file_path: Path) -> list[str]:
    errors = []
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as e:
        return [f"Cannot read: {e}"]

    if unicodedata.normalize("NFC", str(file_path)) != str(file_path):
        errors.append("Path is not NFC-normalized")

    fm, body, parse_errors = _frontmatter_and_body(text)
    if parse_errors:
        return errors + parse_errors
    assert fm is not None

    for field in REQUIRED_FIELDS:
        if field not in fm:
            errors.append(f"Missing required field: {field}")
    for field in FORBIDDEN_FRONTMATTER_FIELDS:
        if field in fm:
            errors.append(f"Forbidden legacy field: {field}")

    if fm.get("행정규칙명") != unicodedata.normalize("NFC", str(fm.get("행정규칙명", ""))):
        errors.append("행정규칙명 is not NFC-normalized")

    if fm.get("행정규칙종류") not in VALID_ADMRULE_TYPES:
        errors.append(f"Invalid 행정규칙종류: {fm.get('행정규칙종류')}")

    org_code = fm.get("기관코드")
    if org_code and not str(org_code).isalnum():
        errors.append(f"기관코드 must be alphanumeric when present: {org_code}")
    if not org_code and not fm.get("소관부처명"):
        errors.append("Either 기관코드 or 소관부처명 is required")

    issue_date = fm.get("발령일자")
    if not isinstance(issue_date, datetime.date):
        errors.append("발령일자 must be a YAML date")
    else:
        if issue_date < datetime.date(1970, 1, 1):
            errors.append("발령일자 must be clamped to 1970-01-01 or later")
        if issue_date > datetime.date.today() + datetime.timedelta(days=366):
            errors.append("발령일자 cannot be more than one year in the future")

    epoch_clamped = bool(fm.get("발령일자보정", False))
    if epoch_clamped and issue_date != datetime.date(1970, 1, 1):
        errors.append("발령일자보정 true requires 발령일자 1970-01-01")
    if epoch_clamped and not fm.get("발령일자원문"):
        errors.append("발령일자원문 is required when 발령일자보정 is true")

    if fm.get("본문출처") not in BODY_SOURCES:
        errors.append(f"Invalid 본문출처: {fm.get('본문출처')}")

    source = fm.get("출처")
    if not source or not _is_law_go_kr_url(str(source)):
        errors.append("출처 must be a law.go.kr URL")

    attachments = fm.get("첨부파일") or []
    if not isinstance(attachments, list):
        errors.append("첨부파일 must be a YAML list")
        attachments = []
    for idx, attachment in enumerate(attachments):
        if not isinstance(attachment, dict):
            errors.append(f"첨부파일[{idx}] must be a dict")
            continue
        if not attachment.get("파일링크") and not attachment.get("PDF링크"):
            errors.append(f"첨부파일[{idx}] missing required field: 파일링크 or PDF링크")
        for key in ("파일링크", "PDF링크"):
            if attachment.get(key) and not _is_law_go_kr_url(str(attachment[key])):
                errors.append(f"첨부파일[{idx}].{key} must be a law.go.kr URL")

    if fm.get("본문출처") == "api-text" and not body:
        errors.append("본문출처 api-text requires non-empty body")

    return errors


def validate_no_binary_files(root: Path) -> list[str]:
    errors = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in BINARY_SUFFIXES:
            errors.append(f"Binary file found: {path}")
    return errors


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    errors = validate_no_binary_files(root)
    for md_file in sorted(root.rglob("*.md")):
        rel_parts = md_file.relative_to(root).parts
        if ".git" in md_file.parts or md_file.name == "README.md" or rel_parts[0] == "pipeline":
            continue
        for error in validate_frontmatter(md_file):
            errors.append(f"{md_file}: {error}")
    for error in errors:
        print(error, file=sys.stderr)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
