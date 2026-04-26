"""Composite filename grammar tests for precedents/converter.py.

Covers `compose_filename_stem`, `cap_caseno_slot`, the SEP runtime guard, and
property-based invariants (NFC idempotence, regex shape, determinism).
"""

import re
import unicodedata

import pytest
from hypothesis import given, settings, strategies as st

import precedents.converter as conv


# ---------------------------------------------------------------------------
# Reset shared registry per test (mirrors test_converter.py guard).
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_assigned_paths(monkeypatch):
    monkeypatch.setattr(conv, "_assigned_paths", {})
    yield
    monkeypatch.setattr(conv, "_assigned_paths", {})


# ---------------------------------------------------------------------------
# compose_filename_stem — happy path
# ---------------------------------------------------------------------------

def test_compose_happy_supreme():
    stem = conv.compose_filename_stem(
        court_name="대법원",
        judgment_date="2023-12-01",
        case_no="2023다12345",
        serial="123456",
    )
    assert stem == f"대법원{conv.SEP}2023-12-01{conv.SEP}2023다12345"


def test_compose_court_abbreviation_is_expanded():
    stem = conv.compose_filename_stem(
        court_name="서울고법",
        judgment_date="2022-06-01",
        case_no="2022누9999",
        serial="111111",
    )
    assert stem == f"서울고등법원{conv.SEP}2022-06-01{conv.SEP}2022누9999"


def test_compose_merged_case_number_preserves_underscore():
    """병합/분리: comma → single `_`; must not collide with the chosen SEP."""
    stem = conv.compose_filename_stem(
        court_name="대법원",
        judgment_date="2000-01-01",
        case_no="2000나10828, 10835(병합)",
        serial="222222",
    )
    parts = stem.split(conv.SEP)
    assert len(parts) == 3, f"grammar must split into exactly 3 slots: {stem!r}"
    assert parts[0] == "대법원"
    assert parts[1] == "2000-01-01"
    assert parts[2] == "2000나10828_10835_병합"


# ---------------------------------------------------------------------------
# Missing-field policy
# ---------------------------------------------------------------------------

def test_compose_missing_date_uses_sentinel():
    stem = conv.compose_filename_stem(
        court_name="대법원",
        judgment_date=None,
        case_no="2023다12345",
        serial="333333",
    )
    assert stem == f"대법원{conv.SEP}{conv.MISSING_DATE_SENTINEL}{conv.SEP}2023다12345"


def test_compose_missing_court_falls_back_to_serial_in_caseno_slot():
    stem = conv.compose_filename_stem(
        court_name="",
        judgment_date="2023-12-01",
        case_no="2023다12345",  # ignored when court is missing
        serial="444444",
    )
    parts = stem.split(conv.SEP)
    assert parts == [conv.MISSING_COURT_SENTINEL, "2023-12-01", "444444"]


def test_compose_missing_case_no_falls_back_to_serial():
    stem = conv.compose_filename_stem(
        court_name="대법원",
        judgment_date="2023-12-01",
        case_no="",
        serial="555555",
    )
    parts = stem.split(conv.SEP)
    assert parts == ["대법원", "2023-12-01", "555555"]


def test_compose_whitespace_only_court_treated_as_missing():
    stem = conv.compose_filename_stem(
        court_name="   ",
        judgment_date="2023-12-01",
        case_no="2023다12345",
        serial="666666",
    )
    parts = stem.split(conv.SEP)
    assert parts[0] == conv.MISSING_COURT_SENTINEL
    assert parts[2] == "666666"


# ---------------------------------------------------------------------------
# Cap policy — only CASENO slot is truncated; SEP slots survive.
# ---------------------------------------------------------------------------

def test_compose_long_caseno_caps_caseno_slot_only():
    huge_caseno = ", ".join(f"2011고합{n}" for n in range(700, 1000))
    stem = conv.compose_filename_stem(
        court_name="대법원",
        judgment_date="2011-12-31",
        case_no=huge_caseno,
        serial="777777",
    )
    encoded_len = len(stem.encode("utf-8"))
    assert encoded_len <= conv.MAX_FILENAME_STEM_BYTES
    parts = stem.split(conv.SEP)
    assert len(parts) == 3, "grammar must remain 3-slot after cap"
    assert parts[0] == "대법원"
    assert parts[1] == "2011-12-31"
    assert stem.endswith("_777777")


def test_cap_caseno_slot_preserves_utf8_boundary():
    stem = conv.cap_caseno_slot(
        court="대법원",
        date="2023-12-01",
        caseno="가" * 200,  # 600 bytes
        serial="888888",
    )
    stem.encode("utf-8")  # decode/encode round-trip — would raise on broken codepoint
    assert len(stem.encode("utf-8")) <= conv.MAX_FILENAME_STEM_BYTES
    parts = stem.split(conv.SEP)
    assert len(parts) == 3
    assert stem.endswith("_888888")


def test_cap_caseno_slot_no_truncation_when_fits():
    stem = conv.cap_caseno_slot(
        court="대법원",
        date="2023-12-01",
        caseno="2023다1",
        serial="99",
    )
    assert stem == f"대법원{conv.SEP}2023-12-01{conv.SEP}2023다1"


# ---------------------------------------------------------------------------
# NFC normalization
# ---------------------------------------------------------------------------

def test_compose_emits_nfc_for_court_and_caseno():
    # NFD form of "가" is U+1100 + U+1161 (2 codepoints, 6 bytes UTF-8).
    nfd_court = unicodedata.normalize("NFD", "서울고등법원")
    nfd_case = unicodedata.normalize("NFD", "2023다12345")
    assert nfd_court != "서울고등법원"  # sanity: input really is NFD
    stem = conv.compose_filename_stem(
        court_name=nfd_court,
        judgment_date="2023-12-01",
        case_no=nfd_case,
        serial="100001",
    )
    assert stem == unicodedata.normalize("NFC", stem)
    assert stem == f"서울고등법원{conv.SEP}2023-12-01{conv.SEP}2023다12345"


def test_sanitize_case_number_emits_nfc():
    nfd_input = unicodedata.normalize("NFD", "2024가합1")
    out = conv.sanitize_case_number(nfd_input)
    assert out == unicodedata.normalize("NFC", out)


# ---------------------------------------------------------------------------
# SEP runtime guard
# ---------------------------------------------------------------------------

def test_sanitize_case_number_assert_blocks_sep_collision(monkeypatch):
    """If raw input ever contains the literal SEP, sanitize must fail-loud."""
    # Synthesize a worst-case raw caseno containing the literal SEP.
    raw = f"2023다1{conv.SEP}2"
    with pytest.raises(AssertionError, match="SEP-collision"):
        conv.sanitize_case_number(raw)


# ---------------------------------------------------------------------------
# get_precedent_path — composite key dedup
# ---------------------------------------------------------------------------

def test_get_precedent_path_unique_composite_keys_no_suffix():
    """Same caseno but different court+date must NOT collide."""
    d1 = {
        "판례정보일련번호": "10001",
        "사건번호": "2020다1234",
        "법원명": "대법원",
        "법원종류코드": "400201",
        "사건종류명": "민사",
        "선고일자": "20200101",
    }
    d2 = {
        "판례정보일련번호": "10002",
        "사건번호": "2020다1234",  # same caseno
        "법원명": "서울고법",       # different court → composite key differs
        "법원종류코드": "400202",
        "사건종류명": "민사",
        "선고일자": "20200615",
    }
    p1 = conv.get_precedent_path(d1)
    p2 = conv.get_precedent_path(d2)
    assert p1 != p2
    assert "_10001.md" not in p1, "no serial suffix should be required"
    assert "_10002.md" not in p2


def test_get_precedent_path_true_collision_appends_serial():
    d = {
        "판례정보일련번호": "20001",
        "사건번호": "2020다1234",
        "법원명": "대법원",
        "법원종류코드": "400201",
        "사건종류명": "민사",
        "선고일자": "20200101",
    }
    d2 = dict(d, **{"판례정보일련번호": "20002"})
    p1 = conv.get_precedent_path(d)
    p2 = conv.get_precedent_path(d2)
    assert p1 != p2
    assert p2.endswith("_20002.md")


def test_get_precedent_path_grammar_regex():
    d = {
        "판례정보일련번호": "30001",
        "사건번호": "2023다12345",
        "법원명": "대법원",
        "법원종류코드": "400201",
        "사건종류명": "민사",
        "선고일자": "20231201",
    }
    p = conv.get_precedent_path(d)
    leaf = p.rsplit("/", 1)[-1]
    pattern = (
        r"^[^/]+"
        + re.escape(conv.SEP)
        + r"\d{4}-\d{2}-\d{2}"
        + re.escape(conv.SEP)
        + r"[^/]+\.md$"
    )
    assert re.match(pattern, leaf), f"leaf does not match grammar: {leaf!r}"


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis)
# ---------------------------------------------------------------------------

# Korean Hangul + ASCII letters/digits + a few separators that real case
# numbers contain. Excludes the SEP literal so the assert never fires
# spuriously inside the strategy.
_caseno_alphabet = st.characters(
    whitelist_categories=("Lu", "Ll", "Lo", "Nd"),
    whitelist_characters="-_().,가나다라마바사아자차카타파하",
)
_court_alphabet = st.characters(
    whitelist_categories=("Lu", "Ll", "Lo", "Nd"),
    whitelist_characters="가나다라마바사아자차카타파하 ",
)


@given(
    court_name=st.text(alphabet=_court_alphabet, min_size=1, max_size=20),
    case_no=st.text(alphabet=_caseno_alphabet, min_size=1, max_size=40),
    year=st.integers(min_value=1900, max_value=2099),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    serial=st.integers(min_value=1, max_value=10**8).map(str),
)
@settings(max_examples=200, deadline=None)
def test_property_compose_grammar_is_3_slot(court_name, case_no, year, month, day, serial):
    """Any reasonable input yields exactly 3 SEP-delimited slots."""
    date = f"{year:04d}-{month:02d}-{day:02d}"
    # Skip inputs that would fail the SEP assert by construction.
    if conv.SEP in case_no:
        return
    stem = conv.compose_filename_stem(court_name, date, case_no, serial)
    parts = stem.split(conv.SEP)
    assert len(parts) == 3, f"grammar broken: {stem!r}"


@given(
    court_name=st.text(alphabet=_court_alphabet, min_size=1, max_size=20),
    case_no=st.text(alphabet=_caseno_alphabet, min_size=1, max_size=40),
    serial=st.integers(min_value=1, max_value=10**8).map(str),
)
@settings(max_examples=200, deadline=None)
def test_property_compose_is_nfc_idempotent(court_name, case_no, serial):
    if conv.SEP in case_no:
        return
    stem = conv.compose_filename_stem(court_name, "2023-01-01", case_no, serial)
    assert stem == unicodedata.normalize("NFC", stem)


@given(
    court_name=st.text(alphabet=_court_alphabet, min_size=1, max_size=20),
    case_no=st.text(alphabet=_caseno_alphabet, min_size=1, max_size=40),
    serial=st.integers(min_value=1, max_value=10**8).map(str),
)
@settings(max_examples=200, deadline=None)
def test_property_compose_is_deterministic(court_name, case_no, serial):
    if conv.SEP in case_no:
        return
    s1 = conv.compose_filename_stem(court_name, "2023-01-01", case_no, serial)
    s2 = conv.compose_filename_stem(court_name, "2023-01-01", case_no, serial)
    assert s1 == s2


@given(
    court_name=st.text(alphabet=_court_alphabet, min_size=1, max_size=20),
    case_no=st.text(alphabet=_caseno_alphabet, min_size=1, max_size=400),
    serial=st.integers(min_value=1, max_value=10**8).map(str),
)
@settings(max_examples=200, deadline=None)
def test_property_compose_byte_length_capped(court_name, case_no, serial):
    if conv.SEP in case_no:
        return
    stem = conv.compose_filename_stem(court_name, "2023-01-01", case_no, serial)
    assert len(stem.encode("utf-8")) <= conv.MAX_FILENAME_STEM_BYTES
