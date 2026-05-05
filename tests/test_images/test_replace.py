"""Tests for images/replace.py — approve_images and replace_images."""

from pathlib import Path

import pytest

import images.config as cfg
import images.replace as replace_mod
from images.manifest import ImageEntry, Manifest
from images.replace import approve_images, replace_images


@pytest.fixture(autouse=True)
def patch_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(cfg, "KR_DIR", tmp_path / "kr")


def _entry(image_id: str, doc_path: str, line: int, tag: str, status: str = "converted", text: str = "") -> ImageEntry:
    return ImageEntry(
        doc_path=doc_path,
        image_id=image_id,
        image_url=f"https://www.law.go.kr/LSW/flDownload.do?flSeq={image_id}",
        tag_format="src",
        original_tag=tag,
        line_number=line,
        status=status,
        converted_text=text,
    )


# ---------------------------------------------------------------------------
# approve_images
# ---------------------------------------------------------------------------

def test_approve_by_ids():
    entries = [
        _entry("111", "kr/a.md", 1, "<img id=111>", status="converted"),
        _entry("222", "kr/a.md", 2, "<img id=222>", status="converted"),
        _entry("333", "kr/a.md", 3, "<img id=333>", status="converted"),
    ]
    Manifest(entries=entries).save()

    approve_images(image_ids=["111", "333"])

    from images.manifest import load_manifest
    m = load_manifest()
    by_id = {e.image_id: e for e in m.entries}
    assert by_id["111"].status == "approved"
    assert by_id["222"].status == "converted"  # not approved
    assert by_id["333"].status == "approved"


def test_approve_by_doc_path_glob():
    entries = [
        _entry("1", "kr/민법/법률.md", 1, "<img>", status="converted"),
        _entry("2", "kr/민법/시행령.md", 1, "<img>", status="converted"),
        _entry("3", "kr/형법/법률.md", 1, "<img>", status="converted"),
    ]
    Manifest(entries=entries).save()

    approve_images(doc_path="kr/민법/*")

    from images.manifest import load_manifest
    m = load_manifest()
    by_id = {e.image_id: e for e in m.entries}
    assert by_id["1"].status == "approved"
    assert by_id["2"].status == "approved"
    assert by_id["3"].status == "converted"  # different path


def test_approve_skips_non_converted():
    entries = [
        _entry("111", "kr/a.md", 1, "<img>", status="downloaded"),
        _entry("222", "kr/a.md", 2, "<img>", status="converted"),
    ]
    Manifest(entries=entries).save()

    approve_images(image_ids=["111", "222"])

    from images.manifest import load_manifest
    m = load_manifest()
    by_id = {e.image_id: e for e in m.entries}
    assert by_id["111"].status == "downloaded"  # unchanged — not converted
    assert by_id["222"].status == "approved"


# ---------------------------------------------------------------------------
# replace_images
# ---------------------------------------------------------------------------

def test_replace_images_writes_file(tmp_path):
    tag = '<img src="https://www.law.go.kr/LSW/flDownload.do?flSeq=100">'
    doc_path = "kr/민법/법률.md"
    md_file = tmp_path / doc_path
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text(f"앞내용\n{tag}\n뒷내용\n", encoding="utf-8")

    entry = _entry("100", doc_path, 2, tag, status="approved", text="[이미지: 한자]")
    Manifest(entries=[entry]).save()

    replace_images()

    content = md_file.read_text(encoding="utf-8")
    assert "[이미지: 한자]" in content
    assert tag not in content


def test_replace_images_updates_status(tmp_path):
    tag = '<img id="200">'
    doc_path = "kr/a.md"
    md_file = tmp_path / doc_path
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text(f"{tag}\n", encoding="utf-8")

    entry = _entry("200", doc_path, 1, tag, status="approved", text="텍스트")
    Manifest(entries=[entry]).save()

    replace_images()

    from images.manifest import load_manifest
    m = load_manifest()
    assert m.entries[0].status == "replaced"


def test_replace_images_dry_run_does_not_modify(tmp_path):
    tag = '<img id="300">'
    doc_path = "kr/b.md"
    md_file = tmp_path / doc_path
    md_file.parent.mkdir(parents=True, exist_ok=True)
    original = f"{tag}\n"
    md_file.write_text(original, encoding="utf-8")

    entry = _entry("300", doc_path, 1, tag, status="approved", text="변환됨")
    Manifest(entries=[entry]).save()

    replace_images(dry_run=True)

    # File must not be modified
    assert md_file.read_text(encoding="utf-8") == original

    # Status must not be updated
    from images.manifest import load_manifest
    m = load_manifest()
    assert m.entries[0].status == "approved"


def test_replace_images_skips_tag_not_at_expected_line(tmp_path):
    tag = '<img id="400">'
    doc_path = "kr/c.md"
    md_file = tmp_path / doc_path
    md_file.parent.mkdir(parents=True, exist_ok=True)
    # tag is on line 3 in file, but entry says line 1
    md_file.write_text(f"line1\nline2\n{tag}\n", encoding="utf-8")

    entry = _entry("400", doc_path, 1, tag, status="approved", text="X")
    Manifest(entries=[entry]).save()

    replace_images()

    # Tag not replaced since line mismatch
    assert tag in md_file.read_text(encoding="utf-8")


def test_replace_images_skips_missing_file(tmp_path):
    entry = _entry("500", "kr/missing.md", 1, "<img>", status="approved", text="X")
    Manifest(entries=[entry]).save()

    # Should not raise
    replace_images()
