"""Tests for precedents/fetch_cache.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import precedents.cache as prec_cache
import precedents.fetch_cache as fetch_cache_mod
from core.counter import Counter


@pytest.fixture(autouse=True)
def patch_prec_cache_dir(tmp_path: Path, monkeypatch):
    prec_dir = tmp_path / "precedent"
    prec_dir.mkdir(parents=True)
    monkeypatch.setattr(prec_cache, "PREC_CACHE_DIR", prec_dir)
    monkeypatch.setattr(fetch_cache_mod, "PREC_CACHE_DIR", prec_dir)
    monkeypatch.setattr(fetch_cache_mod, "_ALL_IDS_PATH", prec_dir / "all_ids.txt")


def _make_search_result(ids: list[str], total: int, page: int = 1) -> dict:
    return {
        "totalCnt": total,
        "page": page,
        "precedents": [{"판례일련번호": pid} for pid in ids],
    }


def test_fetch_all_ids_pagination(tmp_path: Path):
    """fetch_all_ids pages through results and collects all IDs.

    The loop condition is: break when page*100 >= total OR no precedents returned.
    With display=100, a single page of 3 results out of total=3 covers everything.
    """
    page1 = _make_search_result(["1", "2", "3"], total=3)

    with patch("precedents.fetch_cache.search_precedents", return_value=page1):
        ids = fetch_cache_mod.fetch_all_ids()

    assert set(ids) == {"1", "2", "3"}


def test_fetch_all_ids_saves_file(tmp_path: Path):
    """fetch_all_ids writes all_ids.txt."""
    page1 = _make_search_result(["111", "222"], total=2)

    with patch("precedents.fetch_cache.search_precedents", return_value=page1):
        fetch_cache_mod.fetch_all_ids()

    all_ids_path = fetch_cache_mod._ALL_IDS_PATH
    assert all_ids_path.exists()
    content = all_ids_path.read_text(encoding="utf-8")
    assert "111" in content
    assert "222" in content


def test_fetch_detail_task_skip_cached(tmp_path: Path):
    """_fetch_detail_task increments cached counter when already cached."""
    prec_cache.put_detail("123456", b"<prec/>")
    counter = Counter()

    with patch("precedents.fetch_cache.get_precedent_detail") as mock_api:
        fetch_cache_mod._fetch_detail_task("123456", counter)

    mock_api.assert_not_called()
    c, f, e = counter.snapshot()
    assert c == 1
    assert f == 0


def test_fetch_detail_task_fetches_new(tmp_path: Path):
    """_fetch_detail_task increments fetched counter for new IDs."""
    counter = Counter()

    with patch("precedents.fetch_cache.get_precedent_detail", return_value=b"<prec/>"):
        fetch_cache_mod._fetch_detail_task("999999", counter)

    c, f, e = counter.snapshot()
    assert f == 1
    assert c == 0


def test_fetch_detail_task_error_counted(tmp_path: Path):
    """_fetch_detail_task increments errors counter on exception."""
    counter = Counter()

    with patch("precedents.fetch_cache.get_precedent_detail", side_effect=RuntimeError("fail")):
        fetch_cache_mod._fetch_detail_task("bad_id", counter)

    c, f, e = counter.snapshot()
    assert e == 1
