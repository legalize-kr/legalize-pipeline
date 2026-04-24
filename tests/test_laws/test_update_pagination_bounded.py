"""Tests for bounded pagination in laws/update.py.

Cases
-----
K. mocked totalCnt=50 on page 1 -> normal exit (no exception)
L. mocked infinite pagination -> raises at page 50 with diagnostic message
L2. --max-pages 500 -> raises at page 500
M. empty page immediately -> normal exit
"""

from unittest.mock import patch

import pytest

import laws.cache as law_cache
import laws.update as update_mod


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Prevent these tests from writing fixture law names (법0..법49, etc.)
    into the shared .cache/history/ directory, where they would poison
    fetch_cache's empty-history invariant on the developer's machine."""
    monkeypatch.setattr(law_cache, "CACHE_DIR", tmp_path / ".cache")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_search(page_responses: dict):
    """Return a search_laws stub that returns canned responses keyed by page number.

    The stub matches the update.py call signature:
        search_laws(query="", page=N, display=100, date_from=..., date_to=...)
    """
    def _search(*, query, page, display, date_from=None, date_to=None):
        if page in page_responses:
            return page_responses[page]
        # Default: return an empty page with the same totalCnt as page 1
        first = page_responses.get(1, {"laws": [], "totalCnt": 0})
        return {"laws": [], "totalCnt": first["totalCnt"]}
    return _search


def _run_update(search_stub, max_pages=50, **kwargs):
    """Call update.update() with all side-effect stubs patched in."""
    with (
        patch.object(update_mod, "search_laws", search_stub),
        patch.object(update_mod, "get_law_history", return_value=[]),
        patch.object(update_mod, "get_last_update", return_value=None),
        patch.object(update_mod, "get_processed_msts", return_value=set()),
        patch.object(update_mod, "mark_processed", return_value=None),
        patch.object(update_mod, "set_last_update", return_value=None),
        patch.object(update_mod, "reset_path_registry", return_value=None),
        patch.object(update_mod, "LAW_API_KEY", "fake-key"),
    ):
        return update_mod.update(days=7, dry_run=True, max_pages=max_pages, **kwargs)


# ---------------------------------------------------------------------------
# K. totalCnt=50 on page 1 -> all results fit in one page, normal exit
# ---------------------------------------------------------------------------

def test_k_total_fits_single_page_no_exception():
    laws = [
        {"법령일련번호": str(i), "법령명한글": f"법{i}", "공포일자": "20240101"}
        for i in range(50)
    ]
    search = _stub_search({1: {"laws": laws, "totalCnt": 50}})
    # Should complete without raising
    _run_update(search)


# ---------------------------------------------------------------------------
# L. infinite pagination -> raises at page 50 with diagnostic
# ---------------------------------------------------------------------------

def test_l_infinite_pagination_raises_at_page_50():
    """If every page returns totalCnt > collected, pagination never terminates."""
    # Each page returns 1 item but totalCnt always claims 10000 → never exits
    def _infinite_search(*, query, page, display, date_from=None, date_to=None):
        return {"laws": [{"법령일련번호": str(page), "법령명한글": f"법{page}", "공포일자": "20240101"}],
                "totalCnt": 10000}

    with pytest.raises(RuntimeError) as exc:
        _run_update(_infinite_search, max_pages=50)

    msg = str(exc.value)
    assert "max_pages=50" in msg
    assert "totalCnt=10000" in msg


# ---------------------------------------------------------------------------
# L2. --max-pages 500 -> raises at page 500
# ---------------------------------------------------------------------------

def test_l2_custom_max_pages_raises_at_correct_limit():
    def _infinite_search(*, query, page, display, date_from=None, date_to=None):
        return {"laws": [{"법령일련번호": str(page), "법령명한글": f"법{page}", "공포일자": "20240101"}],
                "totalCnt": 999999}

    with pytest.raises(RuntimeError) as exc:
        _run_update(_infinite_search, max_pages=500)

    msg = str(exc.value)
    assert "max_pages=500" in msg


# ---------------------------------------------------------------------------
# M. empty page immediately -> normal exit
# ---------------------------------------------------------------------------

def test_m_empty_first_page_exits_normally():
    search = _stub_search({1: {"laws": [], "totalCnt": 0}})
    # Should complete without raising; returns 0 committed (dry_run)
    result = _run_update(search)
    assert result == 0
