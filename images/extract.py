"""Scan all *.md files under KR_DIR and extract <img> tags into a manifest.

Two tag formats are handled:
  - src-format:  <img src="http(s)://www.law.go.kr/[LSW/]flDownload.do?flSeq=123" ...>
  - id-only:     <img id="123">

Usage:
    python -m images.extract
"""

import logging
import re
from datetime import date
from pathlib import Path

from . import config
from .config import IMAGE_DOWNLOAD_URL
from .manifest import ImageEntry, Manifest, load_manifest

logger = logging.getLogger(__name__)

# Matches src-format: captures flSeq value and the full tag string.
# Handles http/https, with or without /LSW/, any attribute order, optional </img>.
_SRC_RE = re.compile(
    r'(<img\b[^>]*\bsrc=["\']https?://www\.law\.go\.kr/(?:LSW/)?flDownload\.do\?flSeq=(\d+)[^>]*>(?:</img>)?)',
    re.IGNORECASE,
)

# Matches id-only: <img id="123"> with no src attribute.
_ID_ONLY_RE = re.compile(
    r'(<img\s+id=["\'](\d+)["\'][^>]*>(?:</img>)?)',
    re.IGNORECASE,
)

# YAML frontmatter date field
_DATE_RE = re.compile(r'^공포일자:\s*["\']?(\d{4}-\d{2}-\d{2})["\']?', re.MULTILINE)


def _parse_priority(text: str) -> int:
    """Return days since promulgation date (lower = more recent). 9999 if not found."""
    m = _DATE_RE.search(text)
    if not m:
        return 9999
    try:
        d = date.fromisoformat(m.group(1))
        return (date.today() - d).days
    except ValueError:
        return 9999


def _extract_from_file(md_file: Path, repo_root: Path) -> list[ImageEntry]:
    """Extract all image entries from a single markdown file."""
    try:
        text = md_file.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Cannot read {md_file}: {e}")
        return []

    doc_path = str(md_file.relative_to(repo_root))
    priority = _parse_priority(text)
    entries: list[ImageEntry] = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in _SRC_RE.finditer(line):
            original_tag, image_id = m.group(1), m.group(2)
            entries.append(ImageEntry(
                doc_path=doc_path,
                image_id=image_id,
                image_url=f"{IMAGE_DOWNLOAD_URL}?flSeq={image_id}",
                tag_format="src",
                original_tag=original_tag,
                line_number=lineno,
                priority=priority,
            ))

        for m in _ID_ONLY_RE.finditer(line):
            original_tag, image_id = m.group(1), m.group(2)
            # Skip if there's a src attribute — already caught above
            if "src=" in original_tag.lower():
                continue
            entries.append(ImageEntry(
                doc_path=doc_path,
                image_id=image_id,
                image_url=f"{IMAGE_DOWNLOAD_URL}?flSeq={image_id}",
                tag_format="id-only",
                original_tag=original_tag,
                line_number=lineno,
                priority=priority,
            ))

    return entries


def extract(kr_dir: Path | None = None) -> Manifest:
    """Scan all *.md files and build a manifest of image references.

    Returns the Manifest (also saves it to MANIFEST_PATH).
    """
    kr_dir = kr_dir or config.KR_DIR
    repo_root = kr_dir.parent
    md_files = sorted(kr_dir.rglob("*.md"))
    total = len(md_files)
    logger.info(f"Scanning {total} markdown files under {kr_dir}")

    all_entries: list[ImageEntry] = []
    for i, md_file in enumerate(md_files, start=1):
        all_entries.extend(_extract_from_file(md_file, repo_root))
        if i % 1000 == 0:
            logger.info(f"Progress: {i}/{total} files scanned, {len(all_entries)} images found so far")

    logger.info(f"Scan complete: {total} files, {len(all_entries)} image references found")

    # Merge with existing manifest to preserve download/approve/replace progress
    existing = load_manifest()
    if existing.entries:
        existing_keys = {
            (e.doc_path, e.image_id, e.line_number) for e in existing.entries
        }
        new_only = [
            e for e in all_entries
            if (e.doc_path, e.image_id, e.line_number) not in existing_keys
        ]
        logger.info(
            f"Merging: {len(existing.entries)} existing + {len(new_only)} new entries"
        )
        manifest = Manifest(entries=existing.entries + new_only)
    else:
        manifest = Manifest(entries=all_entries)

    manifest.save()
    return manifest


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    extract()


if __name__ == "__main__":
    main()
