from datetime import date
from xml.etree import ElementTree

from ordinances import detail_failure_allowlist


def test_known_detail_failure_is_expiring_and_error_specific():
    detail_failure_allowlist.load_allowlist.cache_clear()
    error = RuntimeError("invalid 자치법규일련번호=<missing>")

    assert detail_failure_allowlist.is_listed("1164395", today=date(2026, 7, 11))
    assert detail_failure_allowlist.accepted_entry("1164395", error, today=date(2026, 7, 11))
    assert detail_failure_allowlist.is_listed("886588", today=date(2026, 7, 12))
    assert detail_failure_allowlist.accepted_entry("886588", error, today=date(2026, 7, 12))
    assert not detail_failure_allowlist.is_listed("1164395", today=date(2026, 10, 31))


def test_known_http_500_details_are_expiring_and_error_specific():
    detail_failure_allowlist.load_allowlist.cache_clear()
    error = RuntimeError("500 Server Error: Internal Server Error")

    for serial in ("740452", "1079638", "1083571"):
        entry = detail_failure_allowlist.accepted_entry(serial, error, today=date(2026, 7, 12))
        assert entry is not None
        assert entry["reason"] == "upstream_http_500"
        assert detail_failure_allowlist.accepted_entry(
            serial, RuntimeError("404 Client Error"), today=date(2026, 7, 12)
        ) is None


def test_repeated_upstream_failures_are_grouped_and_expiring():
    detail_failure_allowlist.load_allowlist.cache_clear()

    malformed = detail_failure_allowlist.accepted_entry(
        "478868",
        ElementTree.ParseError("not well-formed (invalid token): line 1, column 1"),
        today=date(2026, 7, 18),
    )
    missing = detail_failure_allowlist.accepted_entry(
        "813696",
        RuntimeError("invalid 자치법규일련번호=<missing>"),
        today=date(2026, 7, 18),
    )
    upstream_500 = detail_failure_allowlist.accepted_entry(
        "899529",
        RuntimeError("500 Server Error: Internal Server Error"),
        today=date(2026, 7, 18),
    )

    assert malformed is not None and malformed["reason"] == "upstream_malformed_xml"
    assert missing is not None and missing["reason"] == "upstream_missing_serial"
    assert upstream_500 is not None and upstream_500["reason"] == "upstream_http_500"
    assert not detail_failure_allowlist.is_listed("1124911", today=date(2026, 7, 18))
    assert not detail_failure_allowlist.is_listed("478868", today=date(2026, 10, 31))


def test_latest_repeated_upstream_failures_are_quarantined():
    detail_failure_allowlist.load_allowlist.cache_clear()
    missing_error = RuntimeError("invalid 자치법규일련번호=<missing>")

    for serial in ("884951", "884952", "888578", "890062", "949968", "1177584"):
        entry = detail_failure_allowlist.accepted_entry(
            serial, missing_error, today=date(2026, 7, 20)
        )
        assert entry is not None
        assert entry["reason"] == "upstream_missing_serial"

    upstream_500 = detail_failure_allowlist.accepted_entry(
        "1037286",
        RuntimeError("500 Server Error: Internal Server Error"),
        today=date(2026, 7, 20),
    )
    assert upstream_500 is not None
    assert upstream_500["reason"] == "upstream_http_500"
