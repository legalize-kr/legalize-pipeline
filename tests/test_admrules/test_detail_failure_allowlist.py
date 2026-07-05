from datetime import date
from pathlib import Path

import pytest
import yaml

import admrules.detail_failure_allowlist as allowlist
from admrules.detail_failure_allowlist import DetailFailureAllowlistSchemaError


@pytest.fixture(autouse=True)
def clear_allowlist_cache():
    allowlist.load_allowlist.cache_clear()
    yield
    allowlist.load_allowlist.cache_clear()


def _write_allowlist(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "known_detail_failures.yaml"
    path.write_text(yaml.dump({"entries": entries}, allow_unicode=True), encoding="utf-8")
    return path


def _entry(
    serial: str = "2100000000001",
    expected_error: str = "500 Server Error",
    expires_on: str = "2099-01-01",
) -> dict:
    return {
        "serial": serial,
        "reason": "upstream_http_500",
        "expected_error": expected_error,
        "expires_on": expires_on,
    }


def test_is_accepted_requires_unexpired_matching_error(tmp_path: Path, monkeypatch):
    path = _write_allowlist(tmp_path, [_entry()])
    monkeypatch.setattr(allowlist, "_DEFAULT_PATH", path)
    allowlist.load_allowlist.cache_clear()

    assert allowlist.is_accepted("2100000000001", "500 Server Error", today=date(2026, 7, 5))
    assert not allowlist.is_accepted("2100000000001", "not well-formed", today=date(2026, 7, 5))
    assert not allowlist.is_accepted("2100000000001", "500 Server Error", today=date(2100, 1, 1))


def test_load_allowlist_rejects_duplicate_serial(tmp_path: Path):
    path = _write_allowlist(tmp_path, [_entry(), _entry()])
    allowlist.load_allowlist.cache_clear()

    with pytest.raises(DetailFailureAllowlistSchemaError, match="duplicate serial"):
        allowlist.load_allowlist(path)


def test_load_allowlist_rejects_missing_required_field(tmp_path: Path):
    bad = _entry()
    bad.pop("expected_error")
    path = _write_allowlist(tmp_path, [bad])
    allowlist.load_allowlist.cache_clear()

    with pytest.raises(DetailFailureAllowlistSchemaError, match="expected_error"):
        allowlist.load_allowlist(path)
