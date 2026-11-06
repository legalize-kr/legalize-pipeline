"""Shared fixtures for the legalize-pipeline test suite."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Session-scoped guard against shared-cache pollution by tests.
#
# Regression: tests that invoke code paths writing to laws.cache.CACHE_DIR or
# precedents.cache.PREC_CACHE_DIR without monkeypatching those module-level
# constants end up writing to the developer's real `.cache/history/` or
# `.cache/precedent/`. That poisons the next `python -m laws.fetch_cache` run
# (see the `Unallowlisted empty` invariant violation with stems like `법0`,
# `foo법`, etc.), or silently seeds bogus precedent XML files. Each offending
# test must isolate its own cache dir; this guard is the last-line trip wire
# that fails the session if any test slipped through without isolation.
# ---------------------------------------------------------------------------


def _snapshot_dir(directory: Path) -> dict[str, tuple[int, int]]:
    """Return {relative_path: (size, mtime_ns)} for every file under directory.

    Tolerates a missing directory by returning an empty mapping. Uses rglob so
    nested cache layouts (e.g. `.cache/detail/{MST}.xml`) are covered too.
    """
    if not directory.exists():
        return {}
    snap: dict[str, tuple[int, int]] = {}
    for p in directory.rglob("*"):
        if p.is_file():
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            snap[str(p.relative_to(directory))] = (st.st_size, st.st_mtime_ns)
    return snap


@pytest.fixture(scope="session", autouse=True)
def _guard_against_shared_cache_pollution():
    """Fail the session if tests write to the real on-disk caches.

    Any test that triggers `laws.cache.put_history()`, `laws.cache.put_detail()`,
    or `precedents.cache.put_detail()` without first monkeypatching the
    module-level `CACHE_DIR` / `PREC_CACHE_DIR` constant will mutate the
    developer's real `.cache/` — the exact failure mode behind the `법0..법49`
    / `foo법` invariant violation. This fixture snapshots the cache dirs at
    session start and diffs at teardown.
    """
    import core.quota_budget as quota_budget

    import admrules.cache as adm_cache
    import admrules.checkpoint as adm_checkpoint
    import laws.cache as law_cache
    import laws.failures as law_failures
    import ordinances.cache as ord_cache
    import ordinances.checkpoint as ord_checkpoint
    import precedents.cache as prec_cache

    guarded: list[tuple[str, Path]] = [
        ("laws.cache.CACHE_DIR/history", law_cache.CACHE_DIR / "history"),
        ("laws.cache.CACHE_DIR/detail", law_cache.CACHE_DIR / "detail"),
        ("precedents.cache.PREC_CACHE_DIR", prec_cache.PREC_CACHE_DIR),
        ("admrules.cache.CACHE_DIR", adm_cache.CACHE_DIR),
        ("ordinances.cache.CACHE_DIR", ord_cache.CACHE_DIR),
    ]
    # Checkpoints are single files rather than directories, and are the kind of
    # shared state that silently leaks between tests: a test that skips
    # isolating them reads (or overwrites) the developer's live crawl state.
    guarded_files: list[tuple[str, Path]] = [
        ("admrules.checkpoint.CHECKPOINT_FILE", adm_checkpoint.CHECKPOINT_FILE),
        ("ordinances.checkpoint.CHECKPOINT_FILE", ord_checkpoint.CHECKPOINT_FILE),
        # 테스트가 실제 쿼터 원장에 허위 소비를 기록하면 그날의 수집이
        # 가드레일에 막힐 수 있다.
        ("core.quota_budget.STATE_FILE", quota_budget.STATE_FILE),
        # 실패 원장은 CI 델타 게이트의 입력이다. 테스트가 남긴 항목은
        # 다음 수집에서 신규 실패로 오보된다.
        ("laws.failures.FAILED_FILE", law_failures.FAILED_FILE),
    ]

    def _snapshot_file(path: Path) -> tuple[int, int] | None:
        try:
            st = path.stat()
        except OSError:
            return None
        return (st.st_size, st.st_mtime_ns)

    snapshots = [(label, d, _snapshot_dir(d)) for label, d in guarded]
    file_snapshots = [(label, p, _snapshot_file(p)) for label, p in guarded_files]

    yield

    violations: list[str] = []
    for label, directory, before in snapshots:
        after = _snapshot_dir(directory)
        added = sorted(set(after) - set(before))
        changed = sorted(k for k in set(after) & set(before) if after[k] != before[k])
        if added or changed:
            preview = (added + changed)[:10]
            violations.append(
                f"{label} ({directory}): added={len(added)} changed={len(changed)}; "
                f"examples={preview}"
            )
    for label, path, before in file_snapshots:
        if _snapshot_file(path) != before:
            violations.append(f"{label} ({path}): mutated")

    if violations:
        raise AssertionError(
            "Tests mutated shared on-disk caches — each test that exercises "
            "cache-writing code paths must monkeypatch the relevant CACHE_DIR "
            "to a tmp_path. Details:\n  - " + "\n  - ".join(violations)
        )


@pytest.fixture(autouse=True)
def _isolate_shared_ledgers(tmp_path, monkeypatch):
    """Keep the shared ledgers out of every test's reach.

    Both are reached indirectly from many code paths, so relying on each test to
    stub them lets one omission corrupt developer state: a phantom day's
    consumption blocks that day's fetch on the headroom guardrail, and a stray
    failure entry is reported as a new regression by the CI delta gate.
    """
    import core.quota_budget as quota_budget
    import laws.failures as law_failures

    monkeypatch.setattr(quota_budget, "STATE_FILE", tmp_path / "quota.json")
    monkeypatch.setattr(law_failures, "FAILED_FILE", tmp_path / "failed_msts.json")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def search_response_xml() -> bytes:
    return (FIXTURES_DIR / "search_response.xml").read_bytes()


@pytest.fixture
def detail_response_xml() -> bytes:
    return (FIXTURES_DIR / "detail_response.xml").read_bytes()


@pytest.fixture
def error_response_xml() -> bytes:
    return (FIXTURES_DIR / "error_response.xml").read_bytes()


@pytest.fixture
def history_response_html() -> str:
    return (FIXTURES_DIR / "history_response.html").read_text(encoding="utf-8")


@pytest.fixture
def prec_search_response_xml() -> bytes:
    return (FIXTURES_DIR / "prec_search_response.xml").read_bytes()


@pytest.fixture
def prec_detail_response_xml() -> bytes:
    return (FIXTURES_DIR / "prec_detail_response.xml").read_bytes()


@pytest.fixture
def prec_error_response_xml() -> bytes:
    return (FIXTURES_DIR / "prec_error_response.xml").read_bytes()


@pytest.fixture
def sample_law_detail() -> dict:
    """Complete law detail dict matching the structure returned by get_law_detail."""
    return {
        "metadata": {
            "법령명한글": "민법",
            "법령MST": "253527",
            "법령ID": "001234",
            "법령구분": "법률",
            "법령구분코드": "법률",
            "소관부처명": "법무부",
            "소관부처코드": "1170000",
            "공포일자": "20240101",
            "공포번호": "20000",
            "시행일자": "20240101",
            "제개정구분": "일부개정",
            "법령분야": "민사",
        },
        "articles": [
            {
                "조문번호": "1",
                "조문제목": "통칙",
                "조문내용": "제1조(통칙) 이 법은 대한민국 민사에 관하여 규정한다.",
                "항": [
                    {
                        "항번호": "1",
                        "항내용": "①이 법은 민사에 관한 일반법이다.",
                        "호": [
                            {
                                "호번호": "1.",
                                "호내용": "1. 첫 번째 호",
                                "목": [
                                    {"목번호": "가.", "목내용": "가. 첫 번째 목"}
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "addenda": [
            {
                "부칙공포일자": "20240101",
                "부칙공포번호": "20000",
                "부칙내용": "  이 법은 공포한 날부터 시행한다.",
            }
        ],
        "raw_xml": b"<law/>",
    }


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    """A tmp_path-based workspace root with kr/ subdirectory."""
    kr_dir = tmp_path / "kr"
    kr_dir.mkdir()
    return tmp_path
