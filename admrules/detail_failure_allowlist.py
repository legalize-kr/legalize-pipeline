"""Loader for known upstream administrative-rule detail fetch failures."""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).parent / "data" / "known_detail_failures.yaml"

_REQUIRED_FIELDS = ("serial", "reason", "expected_error", "expires_on")


class DetailFailureAllowlistSchemaError(RuntimeError):
    """Raised when the detail-failure allowlist YAML is malformed."""


def _validate_entry(entry: object, idx: int) -> dict:
    if not isinstance(entry, dict):
        raise DetailFailureAllowlistSchemaError(
            f"entries[{idx}] is not a mapping: {entry!r}"
        )
    for field in _REQUIRED_FIELDS:
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            raise DetailFailureAllowlistSchemaError(
                f"entries[{idx}]: field '{field}' is missing or not a non-empty string"
            )
    if not re.fullmatch(r"\d+", entry["serial"]):
        raise DetailFailureAllowlistSchemaError(
            f"entries[{idx}]: serial {entry['serial']!r} must contain digits only"
        )
    try:
        date.fromisoformat(entry["expires_on"])
    except ValueError as e:
        raise DetailFailureAllowlistSchemaError(
            f"entries[{idx}]: expires_on {entry['expires_on']!r} is not a valid ISO date: {e}"
        ) from e
    return dict(entry)


@lru_cache(maxsize=1)
def load_allowlist(path: Path | None = None) -> dict[str, dict]:
    """Return ``{serial: entry_dict}`` from the detail-failure allowlist YAML."""

    resolved = path if path is not None else _DEFAULT_PATH
    if not resolved.exists():
        return {}

    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise DetailFailureAllowlistSchemaError(f"failed to parse {resolved}: {e}") from e

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DetailFailureAllowlistSchemaError(f"{resolved}: top-level must be a mapping")

    entries = raw.get("entries")
    if entries is None:
        return {}
    if not isinstance(entries, list):
        raise DetailFailureAllowlistSchemaError(f"{resolved}: 'entries' must be a list")

    result: dict[str, dict] = {}
    for idx, entry in enumerate(entries):
        validated = _validate_entry(entry, idx)
        serial = validated["serial"]
        if serial in result:
            raise DetailFailureAllowlistSchemaError(
                f"duplicate serial {serial!r} at entries[{idx}]"
            )
        result[serial] = validated
    return result


def accepted_entry(
    serial: str | int | None,
    error: BaseException | str,
    today: date | None = None,
) -> dict | None:
    """Return the unexpired matching allowlist entry, or ``None``."""

    if serial is None:
        return None
    entry = load_allowlist().get(str(serial))
    if entry is None:
        return None
    today_ = today if today is not None else date.today()
    if date.fromisoformat(entry["expires_on"]) <= today_:
        return None
    if entry["expected_error"] not in str(error):
        return None
    return entry


def is_accepted(
    serial: str | int | None,
    error: BaseException | str,
    today: date | None = None,
) -> bool:
    """Return True iff ``serial`` and ``error`` match an unexpired entry."""

    return accepted_entry(serial, error, today=today) is not None
