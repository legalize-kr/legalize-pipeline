"""Tests for images/config.py — runtime path overrides."""

import pytest
import images.config as cfg
from core.config import CACHE_ROOT, LEGALIZE_KR_REPO


@pytest.fixture(autouse=True)
def restore_config():
    """Restore images.config globals after each test."""
    orig_cache = cfg.IMAGE_CACHE_DIR
    orig_manifest = cfg.MANIFEST_PATH
    orig_checksums = cfg.CHECKSUMS_PATH
    orig_kr = cfg.KR_DIR
    yield
    cfg.IMAGE_CACHE_DIR = orig_cache
    cfg.MANIFEST_PATH = orig_manifest
    cfg.CHECKSUMS_PATH = orig_checksums
    cfg.KR_DIR = orig_kr


def test_default_paths():
    assert cfg.IMAGE_CACHE_DIR == CACHE_ROOT / "images"
    assert cfg.MANIFEST_PATH == cfg.IMAGE_CACHE_DIR / "manifest.json"
    assert cfg.CHECKSUMS_PATH == cfg.IMAGE_CACHE_DIR / "checksums.json"
    assert cfg.KR_DIR == LEGALIZE_KR_REPO / "kr"


def test_set_cache_dir(tmp_path):
    new_dir = tmp_path / "custom-cache"
    cfg.set_cache_dir(new_dir)
    assert cfg.IMAGE_CACHE_DIR == new_dir
    assert cfg.MANIFEST_PATH == new_dir / "manifest.json"
    assert cfg.CHECKSUMS_PATH == new_dir / "checksums.json"


def test_set_cache_dir_updates_all_derived_paths(tmp_path):
    cfg.set_cache_dir(tmp_path / "a")
    cfg.set_cache_dir(tmp_path / "b")
    assert cfg.IMAGE_CACHE_DIR == tmp_path / "b"
    assert cfg.MANIFEST_PATH == tmp_path / "b" / "manifest.json"
    assert cfg.CHECKSUMS_PATH == tmp_path / "b" / "checksums.json"


def test_set_kr_dir(tmp_path):
    new_dir = tmp_path / "my-kr"
    cfg.set_kr_dir(new_dir)
    assert cfg.KR_DIR == new_dir


def test_set_kr_dir_does_not_affect_cache_paths(tmp_path):
    original_cache = cfg.IMAGE_CACHE_DIR
    cfg.set_kr_dir(tmp_path / "custom-kr")
    assert cfg.IMAGE_CACHE_DIR == original_cache
