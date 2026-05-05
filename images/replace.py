"""Apply approved image conversions to markdown files."""

from __future__ import annotations

import fnmatch
import logging

from core.atomic_io import atomic_write_text

from . import config
from .manifest import load_manifest

logger = logging.getLogger(__name__)


def replace_images(dry_run: bool = False) -> None:
    """Replace approved image tags in markdown files with converted text.

    Args:
        dry_run: If True, print diffs without writing files or updating manifest.
    """
    manifest = load_manifest()
    approved = [e for e in manifest.entries if e.status == "approved"]

    # Group by doc_path
    by_doc: dict[str, list] = {}
    for entry in approved:
        by_doc.setdefault(entry.doc_path, []).append(entry)

    files_modified = 0
    replacements_made = 0
    tags_not_found = 0

    for doc_path, entries in by_doc.items():
        file_path = config.KR_DIR.parent / doc_path
        if not file_path.exists():
            logger.warning(f"File not found, skipping: {file_path}")
            continue

        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)

        # Process in reverse line order so earlier line numbers stay valid
        entries.sort(key=lambda e: e.line_number, reverse=True)

        for entry in entries:
            idx = entry.line_number - 1
            if idx < 0 or idx >= len(lines) or entry.original_tag not in lines[idx]:
                logger.warning(
                    f"Tag not found in {doc_path}:{entry.line_number} "
                    f"(image_id={entry.image_id}): {entry.original_tag!r}"
                )
                tags_not_found += 1
                continue

            if dry_run:
                print(f"--- {doc_path}:{entry.line_number} [{entry.image_id}]")
                print(f"-  {entry.original_tag}")
                print(f"+  {entry.converted_text}")
            else:
                lines[idx] = lines[idx].replace(entry.original_tag, entry.converted_text, 1)
                entry.status = "replaced"
                replacements_made += 1

        if not dry_run:
            new_content = "".join(lines)
            if new_content != content:
                atomic_write_text(file_path, new_content)
                files_modified += 1

    if not dry_run:
        manifest.save()

    logger.info(
        f"replace_images: files_modified={files_modified}, "
        f"replacements_made={replacements_made}, tags_not_found={tags_not_found}"
        + (" [dry_run]" if dry_run else "")
    )


def approve_images(
    image_ids: list[str] | None = None,
    doc_path: str | None = None,
) -> None:
    """Mark converted entries as approved.

    Args:
        image_ids: Approve entries matching these image IDs.
        doc_path: Approve all converted entries in docs matching this glob pattern.
    """
    manifest = load_manifest()
    approved_count = 0

    for entry in manifest.entries:
        if entry.status != "converted":
            continue

        if image_ids is not None and entry.image_id in image_ids:
            entry.status = "approved"
            approved_count += 1
        elif doc_path is not None and fnmatch.fnmatch(entry.doc_path, doc_path):
            entry.status = "approved"
            approved_count += 1

    manifest.save()
    logger.info(f"approve_images: {approved_count} entries approved")
