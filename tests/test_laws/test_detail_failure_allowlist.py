from datetime import date
from pathlib import Path

import pytest
import yaml

import laws.detail_failure_allowlist as allowlist
from laws.detail_failure_allowlist import DetailFailureAllowlistSchemaError


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
    mst: str = "123",
    expected_error: str = "mismatched tag",
    expires_on: str = "2099-01-01",
) -> dict:
    return {
        "mst": mst,
        "law_name": "테스트법",
        "reason": "upstream_malformed_xml",
        "expected_error": expected_error,
        "expires_on": expires_on,
    }


def test_is_accepted_requires_unexpired_matching_error(tmp_path: Path, monkeypatch):
    path = _write_allowlist(tmp_path, [_entry()])
    monkeypatch.setattr(allowlist, "_DEFAULT_PATH", path)
    allowlist.load_allowlist.cache_clear()

    assert allowlist.is_accepted("123", "mismatched tag: line 1", today=date(2026, 6, 24))
    assert not allowlist.is_accepted("123", "500 Server Error", today=date(2026, 6, 24))
    assert not allowlist.is_accepted("123", "mismatched tag: line 1", today=date(2100, 1, 1))


def test_active_entry_requires_only_unexpired_mst(tmp_path: Path, monkeypatch):
    path = _write_allowlist(tmp_path, [_entry()])
    monkeypatch.setattr(allowlist, "_DEFAULT_PATH", path)
    allowlist.load_allowlist.cache_clear()

    assert allowlist.active_entry("123", today=date(2026, 6, 24)) is not None
    assert allowlist.active_entry("456", today=date(2026, 6, 24)) is None
    assert allowlist.active_entry("123", today=date(2100, 1, 1)) is None


def test_load_allowlist_rejects_duplicate_mst(tmp_path: Path):
    path = _write_allowlist(tmp_path, [_entry(), _entry()])
    allowlist.load_allowlist.cache_clear()

    with pytest.raises(DetailFailureAllowlistSchemaError, match="duplicate mst"):
        allowlist.load_allowlist(path)


def test_load_allowlist_rejects_missing_required_field(tmp_path: Path):
    bad = _entry()
    bad.pop("expected_error")
    path = _write_allowlist(tmp_path, [bad])
    allowlist.load_allowlist.cache_clear()

    with pytest.raises(DetailFailureAllowlistSchemaError, match="expected_error"):
        allowlist.load_allowlist(path)
