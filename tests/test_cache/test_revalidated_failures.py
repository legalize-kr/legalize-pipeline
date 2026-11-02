"""Replay independently observed errors through the detail fetch tasks."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

from admrules import fetch_cache as admrules
from core.counter import Counter
from ordinances import fetch_cache as ordinances


class ProbeDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 2)


@pytest.mark.parametrize("target,module", [("admrul", admrules), ("ordin", ordinances)])
def test_revalidated_errors_remain_quarantined_and_expire(target, module, monkeypatch):
    evidence = json.loads(
        Path("tests/fixtures/detail_failures_20261102.json").read_text(encoding="utf-8")
    )
    records = [record for record in evidence["records"] if record["target"] == target]
    allowlist = module.detail_failure_allowlist
    allowlist.load_allowlist.cache_clear()
    monkeypatch.setattr(allowlist, "date", ProbeDate)
    monkeypatch.setattr(module.cache, "get_detail", lambda *args, **kwargs: None)
    processed = Mock()
    monkeypatch.setattr(module.checkpoint, "mark_detail_processed", processed)
    if target == "ordin":
        monkeypatch.setattr(module, "append_failure", Mock())
    counter = Counter()
    for record in records:
        serial = record.get("mst", record["id"])
        error = RuntimeError(record["error"])
        if target == "admrul":
            monkeypatch.setattr(module, "get_admrule_detail", Mock(side_effect=error))
            module._fetch_detail_task(serial, counter)
        else:
            monkeypatch.setattr(module, "get_ordinance_detail", Mock(side_effect=error))
            module._fetch_detail_task(record["id"], serial, counter, Mock())
        assert allowlist.accepted_entry(serial, error, today=date(2027, 1, 31)) is None
        assert allowlist.accepted_entry(serial, RuntimeError("new failure")) is None
    assert counter.snapshot_all() == {
        "cached": 0, "fetched": 0, "errors": 0, "known_failures": len(records),
    }
    processed.assert_not_called()


def test_unverified_failures_are_not_extended():
    for module, serial in ((admrules, "2100000027840"), (ordinances, "722942"),
                           (ordinances, "866942")):
        allowlist = module.detail_failure_allowlist
        allowlist.load_allowlist.cache_clear()
        assert allowlist.accepted_entry(
            serial, RuntimeError("invalid 자치법규일련번호=<missing> 500 Server Error"),
            today=date(2026, 11, 2),
        ) is None
