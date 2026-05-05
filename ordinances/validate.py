"""Lightweight validators for ordinance repository trees."""

import sys
import unicodedata
from pathlib import Path

import yaml

from .config import STORAGE_TYPES
from .converter import compute_path
from .jurisdictions import GWANGYEOK


def validate_markdown_file(path: Path, *, repo_root: Path) -> list[str]:
    errors = []
    rel = path.relative_to(repo_root)
    if unicodedata.normalize("NFC", str(rel)) != str(rel):
        errors.append(f"NFD path: {rel}")
    if len(rel.parts) != 5 or rel.name != "본문.md":
        errors.append(f"invalid depth: {rel}")

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return [*errors, f"missing frontmatter: {rel}"]
    try:
        yaml_text, body = text[4:].split("\n---\n", 1)
    except ValueError:
        return [*errors, f"unterminated frontmatter: {rel}"]
    try:
        fm = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as e:
        return [*errors, f"invalid YAML: {rel}: {e}"]
    ordinance_type = fm.get("자치법규종류", fm.get("ordinance_type"))
    if ordinance_type not in STORAGE_TYPES:
        errors.append(f"invalid 자치법규종류: {rel}")
    split = fm.get("지자체구분") or fm.get("jurisdiction_split") or {}
    if split.get("광역") not in GWANGYEOK or not split.get("기초"):
        errors.append(f"invalid 지자체구분: {rel}")
    body_source = fm.get("본문출처", fm.get("body_source"))
    if body_source not in {"api-text", "parsed-from-hwp", "parsing-failed"}:
        errors.append(f"invalid 본문출처: {rel}")
    expected = compute_path(
        {
            "자치법규종류": ordinance_type or "",
            "지자체기관명": fm.get("지자체기관명", fm.get("jurisdiction", "")),
            "자치법규명": fm.get("자치법규명", ""),
            "공포번호": fm.get("공포번호", ""),
            "자치법규ID": fm.get("자치법규ID", ""),
        }
    )
    if str(rel) != expected and not _is_collision_path(rel, Path(expected), fm):
        errors.append(f"path mismatch: {rel} != {expected}")
    for idx, attachment in enumerate(fm.get("첨부파일") or fm.get("attachments") or []):
        if not isinstance(attachment, dict):
            errors.append(f"첨부파일[{idx}] must be a dict: {rel}")
            continue
        if not (attachment.get("파일링크") or attachment.get("source_url")):
            errors.append(f"첨부파일[{idx}] missing 파일링크: {rel}")
    if body_source == "api-text" and not body.strip():
        errors.append(f"empty body: {rel}")
    return errors


def _is_collision_path(rel: Path, expected: Path, fm: dict) -> bool:
    if len(rel.parts) != 5 or len(expected.parts) != 5:
        return False
    if rel.parts[:3] != expected.parts[:3] or rel.name != expected.name:
        return False
    base_name = expected.parts[3]
    actual_name = rel.parts[3]
    suffixes = [
        str(fm.get("공포번호", "")),
        str(fm.get("자치법규ID", "")),
        f"{fm.get('공포번호', '')}_{fm.get('자치법규ID', '')}",
    ]
    return any(suffix and actual_name == f"{base_name}_{suffix}" for suffix in suffixes) or (
        actual_name.startswith(f"{base_name}_{fm.get('자치법규ID', '')}_")
    )


def main() -> None:
    repo_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    errors = []
    for md_file in sorted(repo_root.rglob("*.md")):
        rel_parts = md_file.relative_to(repo_root).parts
        if ".git" in md_file.parts or md_file.name == "README.md" or rel_parts[0] == "pipeline":
            continue
        errors.extend(validate_markdown_file(md_file, repo_root=repo_root))
    for error in errors:
        print(error, file=sys.stderr)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
