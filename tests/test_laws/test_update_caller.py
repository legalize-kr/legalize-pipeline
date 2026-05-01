"""Tests for update.py caller site — empty-body quarantine via mark_failed_and_quarantine."""

import json

import pytest


def test_find_existing_path_for_law_id(tmp_path, monkeypatch):
    """Existing on-disk file with matching 법령ID is reused as the write path.

    Regression: update.py runs with a fresh PathRegistry and would otherwise
    pick a different canonical path than the previously written file when
    the 법령구분 changes (e.g. 기획재정부령 → 재정경제부령) or when an
    earlier rebuild qualified the path due to a collision (법률(법률).md).
    Reusing the existing path prevents orphan files that crash
    laws.validate.
    """
    import laws.update as update_mod
    import laws.converter as conv

    kr_dir = tmp_path / "kr"
    kr_dir.mkdir()
    monkeypatch.setattr(update_mod, "KR_DIR", kr_dir)
    monkeypatch.setattr(update_mod, "LAW_API_KEY", "test-key")
    monkeypatch.setattr(conv, "KR_DIR", kr_dir, raising=False)

    # Old-ministry file already on disk
    law_dir = kr_dir / "공기업ㆍ준정부기관계약사무규칙"
    law_dir.mkdir()
    old_file = law_dir / "기획재정부령.md"
    old_file.write_text(
        "---\n법령ID: '010568'\n법령MST: 285569\n---\n# x\n",
        encoding="utf-8",
    )

    # Current API says law_type is 재정경제부령 — would normally write to
    # 재정경제부령.md, but the helper should reuse 기획재정부령.md
    found = update_mod._find_existing_path_for_law_id(
        law_name="공기업ㆍ준정부기관 계약사무규칙",
        law_type="재정경제부령",
        law_id="010568",
    )
    assert found == "kr/공기업ㆍ준정부기관계약사무규칙/기획재정부령.md"


def test_find_existing_path_for_law_id_across_renamed_group(tmp_path, monkeypatch):
    import laws.update as update_mod
    import laws.converter as conv

    kr_dir = tmp_path / "kr"
    kr_dir.mkdir()
    monkeypatch.setattr(update_mod, "KR_DIR", kr_dir)
    monkeypatch.setattr(update_mod, "LAW_API_KEY", "test-key")
    monkeypatch.setattr(conv, "KR_DIR", kr_dir, raising=False)

    old_dir = kr_dir / "헌법재판소참고인비용지급에관한규칙"
    old_dir.mkdir()
    old_file = old_dir / "헌법재판소규칙.md"
    old_file.write_text(
        "---\n법령ID: '006104'\n법령MST: 285845\n---\n# x\n",
        encoding="utf-8",
    )

    found = update_mod._find_existing_path_for_law_id(
        law_name="헌법재판소 참고인 등 비용지급에 관한 규칙",
        law_type="헌법재판소규칙",
        law_id="006104",
    )
    assert found == "kr/헌법재판소참고인비용지급에관한규칙/헌법재판소규칙.md"


def test_find_existing_path_no_match_returns_none(tmp_path, monkeypatch):
    import laws.update as update_mod
    import laws.converter as conv

    kr_dir = tmp_path / "kr"
    kr_dir.mkdir()
    monkeypatch.setattr(update_mod, "KR_DIR", kr_dir)
    monkeypatch.setattr(conv, "KR_DIR", kr_dir, raising=False)

    # Empty / missing dir
    assert update_mod._find_existing_path_for_law_id("foo법", "법률", "999999") is None

    # Existing file with different law_id
    law_dir = kr_dir / "foo법"
    law_dir.mkdir()
    (law_dir / "법률.md").write_text(
        "---\n법령ID: '111111'\n법령MST: 1\n---\n",
        encoding="utf-8",
    )
    assert update_mod._find_existing_path_for_law_id("foo법", "법률", "999999") is None


def test_empty_body_in_update_quarantines_existing_markdown(tmp_path, monkeypatch):
    """Empty-body ValueError from law_to_markdown causes quarantine of existing markdown."""
    import laws.update as update_mod
    import laws.failures as failures
    import laws.converter as conv
    import laws.checkpoint as checkpoint_mod
    import laws.cache as law_cache

    # Point workspace roots
    kr_dir = tmp_path / "kr"
    kr_dir.mkdir()
    monkeypatch.setattr(update_mod, "KR_DIR", kr_dir)
    monkeypatch.setattr(update_mod, "LAW_API_KEY", "test-key")
    monkeypatch.setattr(conv, "KR_DIR", kr_dir, raising=False)
    monkeypatch.setattr(failures, "FAILED_FILE", tmp_path / ".failed_msts.json")
    # Prevent the augment_history path from writing `foo법.json` (empty) into
    # the shared .cache/history/ on disk and also from hitting the real API.
    monkeypatch.setattr(law_cache, "CACHE_DIR", tmp_path / ".cache")
    monkeypatch.setattr(update_mod, "get_law_history", lambda name, refresh=False: [])

    # Seed existing stale markdown file
    law_dir = kr_dir / "foo법"
    law_dir.mkdir()
    existing_md = law_dir / "법률.md"
    existing_md.write_text("stale", encoding="utf-8")

    # Stub search_laws to return one entry
    monkeypatch.setattr(update_mod, "search_laws", lambda **kw: {
        "laws": [{"법령일련번호": "123", "법령명한글": "foo법", "공포일자": "20240101", "제개정구분명": "일부개정", "공포번호": "1"}],
        "totalCnt": 1,
    })

    # Stub get_law_detail
    monkeypatch.setattr(update_mod, "get_law_detail", lambda mst: {
        "metadata": {
            "법령명한글": "foo법",
            "법령MST": "123",
            "법령ID": "",
            "법령구분": "법률",
            "법령구분코드": "",
            "소관부처명": "",
            "소관부처코드": "",
            "공포일자": "20240101",
            "공포번호": "1",
            "시행일자": "",
            "제개정구분": "",
            "법령분야": "",
        },
        "articles": [],
        "addenda": [],
        "raw_xml": b"<law/>",
    })

    # Stub law_to_markdown to raise ValueError (empty body)
    monkeypatch.setattr(update_mod, "law_to_markdown", lambda detail: (_ for _ in ()).throw(
        ValueError("empty_body: seeded")
    ))

    # Stub checkpoint helpers
    monkeypatch.setattr(update_mod, "get_last_update", lambda: None)
    monkeypatch.setattr(update_mod, "get_processed_msts", lambda: set())
    monkeypatch.setattr(update_mod, "mark_processed", lambda mst: None)
    monkeypatch.setattr(update_mod, "set_last_update", lambda d: None)

    # Stub commit_law (no git)
    monkeypatch.setattr(update_mod, "commit_law", lambda *a, **kw: False)

    # Stub reset_path_registry
    monkeypatch.setattr(update_mod, "reset_path_registry", lambda: None)

    # Stub get_law_path to return predictable path
    monkeypatch.setattr(update_mod, "get_law_path", lambda name, law_type, law_id="": f"kr/{name}/법률.md")

    update_mod.update(days=1, dry_run=False)

    # Stale file should exist
    stale_path = law_dir / ".법률.md.stale"
    assert stale_path.exists(), f"Expected stale file at {stale_path}"

    # Original should be gone
    assert not existing_md.exists(), "Original markdown should have been renamed"

    # .failed_msts.json should record reason=empty_body
    failed_data = json.loads((tmp_path / ".failed_msts.json").read_text(encoding="utf-8"))
    assert failed_data["failed_msts"]["123"]["reason"] == "empty_body"
