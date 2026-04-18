"""Loader for the known-empty-body allowlist (keyed by 법령MST).

When a cached detail XML parses with no articles and no addenda,
``laws/converter.py::law_to_markdown`` raises ``ValueError("empty_body: ...")``
by default. MSTs listed in ``laws/data/known_empty_body.yaml`` are accepted:
the converter emits frontmatter-only Markdown and the importer counts the
entry as ``empty_body_accepted`` in stats.json.

Schema mirrors ``known_empty_history.yaml`` but keyed by MST rather than stem.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).parent / "data" / "known_empty_body.yaml"

_TRACKING_ISSUE_RE = re.compile(r"^[^/]+/[^/]+#\d+$")
_REQUIRED_FIELDS = ("mst", "law_name", "reason", "tracking_issue", "expires_on")


class EmptyBodyAllowlistSchemaError(RuntimeError):
    """Raised when the empty-body allowlist YAML is malformed."""


def _validate_entry(entry: object, idx: int) -> dict:
    if not isinstance(entry, dict):
        raise EmptyBodyAllowlistSchemaError(
            f"entries[{idx}] is not a mapping: {entry!r}"
        )
    for field in _REQUIRED_FIELDS:
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            raise EmptyBodyAllowlistSchemaError(
                f"entries[{idx}]: field '{field}' is missing or not a non-empty string"
            )
    if not _TRACKING_ISSUE_RE.match(entry["tracking_issue"]):
        raise EmptyBodyAllowlistSchemaError(
            f"entries[{idx}]: tracking_issue {entry['tracking_issue']!r} "
            f"does not match 'owner/repo#N'"
        )
    try:
        date.fromisoformat(entry["expires_on"])
    except ValueError as e:
        raise EmptyBodyAllowlistSchemaError(
            f"entries[{idx}]: expires_on {entry['expires_on']!r} is not a valid ISO date: {e}"
        ) from e
    return dict(entry)


@lru_cache(maxsize=1)
def load_allowlist(path: Path | None = None) -> dict[str, dict]:
    """Return ``{mst: entry_dict}`` from the empty-body allowlist YAML.

    A missing file returns ``{}``. Schema violations raise
    :class:`EmptyBodyAllowlistSchemaError`.
    """
    resolved = path if path is not None else _DEFAULT_PATH
    if not resolved.exists():
        return {}

    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise EmptyBodyAllowlistSchemaError(f"failed to parse {resolved}: {e}") from e

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise EmptyBodyAllowlistSchemaError(f"{resolved}: top-level must be a mapping")

    entries = raw.get("entries")
    if entries is None:
        return {}
    if not isinstance(entries, list):
        raise EmptyBodyAllowlistSchemaError(f"{resolved}: 'entries' must be a list")

    result: dict[str, dict] = {}
    for idx, entry in enumerate(entries):
        validated = _validate_entry(entry, idx)
        mst = validated["mst"]
        if mst in result:
            raise EmptyBodyAllowlistSchemaError(
                f"duplicate mst {mst!r} at entries[{idx}]"
            )
        result[mst] = validated
    return result


def is_accepted(mst: str | int | None, today: date | None = None) -> bool:
    """Return True iff ``mst`` is in the allowlist AND not past expiry."""
    if mst is None:
        return False
    key = str(mst)
    entry = load_allowlist().get(key)
    if entry is None:
        return False
    today_ = today if today is not None else date.today()
    return date.fromisoformat(entry["expires_on"]) > today_
