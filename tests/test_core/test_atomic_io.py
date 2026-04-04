"""Tests for core/atomic_io.py."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.atomic_io import atomic_write_bytes, atomic_write_text


def test_atomic_write_bytes_creates_file(tmp_path: Path):
    target = tmp_path / "output.xml"
    atomic_write_bytes(target, b"hello bytes")
    assert target.exists()
    assert target.read_bytes() == b"hello bytes"


def test_atomic_write_bytes_overwrites(tmp_path: Path):
    target = tmp_path / "output.xml"
    target.write_bytes(b"old content")
    atomic_write_bytes(target, b"new content")
    assert target.read_bytes() == b"new content"


def test_atomic_write_text_utf8(tmp_path: Path):
    target = tmp_path / "output.txt"
    text = "안녕하세요 한글 테스트"
    atomic_write_text(target, text)
    assert target.read_text(encoding="utf-8") == text


def test_atomic_write_bytes_error_cleanup(tmp_path: Path):
    """On write failure the temp file should be cleaned up."""
    target = tmp_path / "output.xml"

    with patch("os.write", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            atomic_write_bytes(target, b"data")

    # Target file must NOT exist and no .tmp files should linger
    assert not target.exists()
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == [], f"Temp files not cleaned up: {tmp_files}"
