"""Tests for images/extract.py — regex matching, priority, and manifest building."""

from datetime import date
from pathlib import Path

import pytest

import images.config as cfg
from images.extract import _ID_ONLY_RE, _SRC_RE, _parse_priority, extract
from images.manifest import Manifest, ImageEntry, load_manifest


@pytest.fixture(autouse=True)
def patch_paths(tmp_path, monkeypatch):
    """Point KR_DIR and MANIFEST_PATH to tmp_path for all tests."""
    monkeypatch.setattr(cfg, "KR_DIR", tmp_path / "kr")
    monkeypatch.setattr(cfg, "MANIFEST_PATH", tmp_path / "manifest.json")


# ---------------------------------------------------------------------------
# _SRC_RE
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    '<img src="https://www.law.go.kr/LSW/flDownload.do?flSeq=46807799" alt="img">',
    '<img src="http://www.law.go.kr/flDownload.do?flSeq=46807799">',
    '<img src="https://www.law.go.kr/LSW/flDownload.do?flSeq=46807799"></img>',
    '<img alt="x" src="https://www.law.go.kr/LSW/flDownload.do?flSeq=46807799">',
])
def test_src_re_matches(line):
    m = _SRC_RE.search(line)
    assert m is not None
    assert m.group(2) == "46807799"


def test_src_re_no_match_on_plain_img():
    assert _SRC_RE.search('<img id="123">') is None


def test_src_re_no_match_on_other_domain():
    assert _SRC_RE.search('<img src="https://example.com/img.png">') is None


# ---------------------------------------------------------------------------
# _ID_ONLY_RE
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    '<img id="13403924">',
    "<img id='13403924'>",
    '<img id="13403924"></img>',
])
def test_id_only_re_matches(line):
    m = _ID_ONLY_RE.search(line)
    assert m is not None
    assert m.group(2) == "13403924"


def test_id_only_re_no_match_when_src_comes_first():
    # _ID_ONLY_RE requires <img\s+id= immediately — src= before id= prevents match
    line = '<img src="https://www.law.go.kr/LSW/flDownload.do?flSeq=123" id="123">'
    assert _ID_ONLY_RE.search(line) is None


# ---------------------------------------------------------------------------
# _parse_priority
# ---------------------------------------------------------------------------

def test_parse_priority_known_date():
    today = date.today()
    text = f"공포일자: {today.isoformat()}"
    assert _parse_priority(text) == 0


def test_parse_priority_past_date():
    priority = _parse_priority("공포일자: 2000-01-01")
    assert priority > 0


def test_parse_priority_no_date():
    assert _parse_priority("no date here") == 9999


def test_parse_priority_invalid_date():
    assert _parse_priority("공포일자: 9999-99-99") == 9999


# ---------------------------------------------------------------------------
# extract()
# ---------------------------------------------------------------------------

def _write_md(kr_dir: Path, rel_path: str, content: str) -> Path:
    p = kr_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_extract_src_format(tmp_path):
    kr_dir = tmp_path / "kr"
    _write_md(kr_dir, "민법/법률.md", (
        '공포일자: 2024-01-01\n'
        '<img src="https://www.law.go.kr/LSW/flDownload.do?flSeq=111" alt="x">\n'
    ))
    manifest = extract(kr_dir=kr_dir)
    assert len(manifest.entries) == 1
    e = manifest.entries[0]
    assert e.image_id == "111"
    assert e.tag_format == "src"
    assert e.status == "extracted"
    assert e.line_number == 2


def test_extract_id_only_format(tmp_path):
    kr_dir = tmp_path / "kr"
    _write_md(kr_dir, "민법/법률.md", '<img id="222"></img>\n')
    manifest = extract(kr_dir=kr_dir)
    assert len(manifest.entries) == 1
    e = manifest.entries[0]
    assert e.image_id == "222"
    assert e.tag_format == "id-only"


def test_extract_skips_id_only_when_src_present(tmp_path):
    kr_dir = tmp_path / "kr"
    line = '<img src="https://www.law.go.kr/LSW/flDownload.do?flSeq=333" id="333">\n'
    _write_md(kr_dir, "a.md", line)
    manifest = extract(kr_dir=kr_dir)
    # Only one entry — the src-format match; id-only is skipped
    assert len(manifest.entries) == 1
    assert manifest.entries[0].tag_format == "src"


def test_extract_saves_manifest(tmp_path):
    kr_dir = tmp_path / "kr"
    _write_md(kr_dir, "a.md", '<img id="444">\n')
    extract(kr_dir=kr_dir)
    assert cfg.MANIFEST_PATH.exists()


def test_extract_merges_with_existing(tmp_path):
    kr_dir = tmp_path / "kr"
    # Pre-populate manifest with a "downloaded" entry
    existing_entry = ImageEntry(
        doc_path="kr/a.md",
        image_id="100",
        image_url="https://www.law.go.kr/LSW/flDownload.do?flSeq=100",
        tag_format="src",
        original_tag='<img src="...">',
        line_number=1,
        status="downloaded",
    )
    Manifest(entries=[existing_entry]).save()

    # Now add a new file with a different image
    _write_md(kr_dir, "a.md", (
        '<img src="https://www.law.go.kr/LSW/flDownload.do?flSeq=100">\n'
        '<img id="999">\n'
    ))
    manifest = extract(kr_dir=kr_dir)

    # Existing entry (downloaded) preserved; new entry added
    by_id = {e.image_id: e for e in manifest.entries}
    assert by_id["100"].status == "downloaded"  # preserved
    assert by_id["999"].status == "extracted"   # new


def test_extract_no_md_files(tmp_path):
    kr_dir = tmp_path / "empty-kr"
    kr_dir.mkdir()
    manifest = extract(kr_dir=kr_dir)
    assert manifest.entries == []
