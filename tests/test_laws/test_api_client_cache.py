"""Reader self-heal tests for cached amendment history.

When the cache contains a poisoned `[]` entry (e.g. from a past pagination
regression), `get_law_history` must re-fetch instead of returning the empty
list, and must overwrite the cache with the fresh result.
"""

from pathlib import Path

import pytest
import responses as responses_lib

import laws.api_client as api_client
import laws.cache as law_cache

LAW_API_BASE = "http://www.law.go.kr/DRF"


@pytest.fixture(autouse=True)
def patch_cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(law_cache, "CACHE_DIR", tmp_path / ".cache")


@pytest.fixture(autouse=True)
def patch_api_key(monkeypatch):
    monkeypatch.setattr(api_client, "LAW_API_KEY", "testkey")
    from core.throttle import Throttle
    monkeypatch.setattr(api_client, "_throttle", Throttle(delay_seconds=0))


def _row(mst: str, name: str) -> str:
    return (
        f"<tr>"
        f"<td>1</td>"
        f'<td><a href="/lsInfoP.do?MST={mst}">{name}</a></td>'
        f"<td>법무부</td>"
        f"<td>일부개정</td>"
        f"<td>법률</td>"
        f"<td>제 1호</td>"
        f"<td>2020.1.1</td>"
        f"<td>2020.1.1</td>"
        f"<td></td>"
        f"</tr>"
    )


@responses_lib.activate
def test_poisoned_empty_cache_triggers_refetch_and_overwrite():
    # Seed poisoned empty cache entry
    law_cache.put_history("주택법", [])
    cache_path = law_cache._history_path("주택법")
    assert cache_path.exists()

    # Mock lsHistory to return a non-empty page (under-full to stop paging)
    html = "<html><body><table>" + _row("2000", "주택법") + _row("2001", "주택법") + "</table></body></html>"
    responses_lib.add(
        responses_lib.GET, f"{LAW_API_BASE}/lawSearch.do",
        body=html, status=200, content_type="text/html; charset=utf-8",
    )

    result = api_client.get_law_history("주택법")

    # Returned fresh (non-empty) result
    assert result != []
    assert len(result) == 2
    assert all(e["법령명한글"] == "주택법" for e in result)

    # Cache overwritten with non-empty content
    fresh = law_cache.get_history("주택법")
    assert fresh != []
    assert fresh == result
