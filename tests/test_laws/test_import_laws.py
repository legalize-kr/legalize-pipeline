"""Tests for laws/import_laws.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import laws.import_laws as import_laws
from laws.converter import reset_path_registry

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(autouse=True)
def patch_dirs(tmp_path: Path, monkeypatch):
    kr_dir = tmp_path / "kr"
    kr_dir.mkdir()
    monkeypatch.setattr(import_laws, "KR_DIR", kr_dir)
    import laws.converter as conv
    monkeypatch.setattr(conv, "KR_DIR", kr_dir)
    import laws.config as lconf
    monkeypatch.setattr(lconf, "KR_DIR", kr_dir)
    reset_path_registry()
    yield
    reset_path_registry()


# ---------------------------------------------------------------------------
# build_commit_msg
# ---------------------------------------------------------------------------

def test_build_commit_msg_format():
    meta = {
        "소관부처명": "법무부",
        "공포일자": "20240101",
        "공포번호": "20000",
        "법령분야": "민사",
        "제개정구분": "일부개정",
    }
    msg = import_laws.build_commit_msg("민법", "법률", "253527", meta)
    assert "법률: 민법" in msg
    assert "일부개정" in msg
    assert "law.go.kr" in msg
    assert "법령MST: 253527" in msg
    assert "공포일자: 2024-01-01" in msg
    assert "소관부처: 법무부" in msg


def test_build_commit_msg_missing_fields():
    meta = {}
    # Should not raise even when fields are missing
    msg = import_laws.build_commit_msg("민법", "법률", "253527", meta)
    assert "법령MST: 253527" in msg
    assert "미상" in msg  # default department


def test_build_commit_msg_no_prom_num():
    meta = {"소관부처명": "법무부", "공포일자": "20240101", "공포번호": ""}
    msg = import_laws.build_commit_msg("민법", "법률", "1", meta)
    # URL for revision should be omitted when no prom_num
    assert "제개정문" not in msg


# ---------------------------------------------------------------------------
# parse_csv
# ---------------------------------------------------------------------------

def test_parse_csv():
    csv_path = FIXTURES_DIR / "sample.csv"
    laws = import_laws.parse_csv(csv_path)
    assert len(laws) == 2
    assert laws[0]["법령MST"] == "253527"
    assert laws[0]["법령명"] == "민법"
    assert laws[0]["법령구분명"] == "법률"
    assert laws[1]["법령명"] == "민법 시행령"


# ---------------------------------------------------------------------------
# build_csv_markdown
# ---------------------------------------------------------------------------

def test_build_csv_markdown():
    law = {
        "법령명": "민법",
        "법령MST": "253527",
        "소관부처명": "법무부",
        "법령ID": "001234",
        "법령구분명": "법률",
        "법령구분코드": "법률",
        "공포일자": "20240101",
        "공포번호": "20000",
        "시행일자": "20240101",
        "법령분야명": "민사",
    }
    md = import_laws.build_csv_markdown(law)
    assert md.startswith("---\n")
    assert "추후 추가 예정" in md
    assert "law.go.kr" in md
    assert "# 민법" in md


def test_build_csv_markdown_list_department():
    law = {
        "법령명": "민법",
        "법령MST": "1",
        "소관부처명": "법무부, 행안부",
        "법령ID": "",
        "법령구분명": "법률",
        "법령구분코드": "",
        "공포일자": "20240101",
        "공포번호": "",
        "시행일자": "",
        "법령분야명": "",
    }
    md = import_laws.build_csv_markdown(law)
    import yaml
    # Extract frontmatter
    end = md.index("---", 3)
    fm = yaml.safe_load(md[3:end])
    assert isinstance(fm["소관부처"], list)
    assert "법무부" in fm["소관부처"]


# ---------------------------------------------------------------------------
# import_law_with_history (dry-run)
# ---------------------------------------------------------------------------

def test_import_law_with_history_dry_run(tmp_path: Path):
    history = [
        {"법령일련번호": "100001", "법령명한글": "민법", "제개정구분명": "제정", "공포일자": "19580222"},
    ]
    detail = {
        "metadata": {
            "법령명한글": "민법", "법령MST": "100001", "법령ID": "001234",
            "법령구분": "법률", "법령구분코드": "법률", "소관부처명": "법무부",
            "공포일자": "19580222", "공포번호": "471", "시행일자": "19600101",
            "제개정구분": "제정", "법령분야": "민사",
        },
        "articles": [], "addenda": [], "raw_xml": b"<law/>",
    }

    with patch("laws.import_laws.get_law_history", return_value=history), \
         patch("laws.import_laws.get_law_detail", return_value=detail), \
         patch("laws.import_laws.get_processed_msts", return_value=set()), \
         patch("laws.import_laws.commit_law") as mock_commit:
        count = import_laws.import_law_with_history("민법", dry_run=True)

    # In dry-run, no commits and no files written
    mock_commit.assert_not_called()
    assert count == 0


def test_import_law_with_history_skips_processed(tmp_path: Path):
    history = [
        {"법령일련번호": "100001", "법령명한글": "민법", "제개정구분명": "제정", "공포일자": "19580222"},
    ]

    with patch("laws.import_laws.get_law_history", return_value=history), \
         patch("laws.import_laws.get_processed_msts", return_value={"100001"}), \
         patch("laws.import_laws.get_law_detail") as mock_detail, \
         patch("laws.import_laws.commit_law") as mock_commit:
        count = import_laws.import_law_with_history("민법")

    mock_detail.assert_not_called()
    mock_commit.assert_not_called()
    assert count == 0


# ---------------------------------------------------------------------------
# import_from_cache flow
# ---------------------------------------------------------------------------

def test_import_from_cache_flow(tmp_path: Path):
    detail = {
        "metadata": {
            "법령명한글": "민법", "법령MST": "253527", "법령ID": "001234",
            "법령구분": "법률", "법령구분코드": "법률", "소관부처명": "법무부",
            "공포일자": "20240101", "공포번호": "20000", "시행일자": "20240101",
            "제개정구분": "일부개정", "법령분야": "민사",
        },
        "articles": [], "addenda": [], "raw_xml": b"<law/>",
    }

    with patch("laws.import_laws.cache") as mock_cache, \
         patch("laws.import_laws.get_law_detail", return_value=detail), \
         patch("laws.import_laws.get_processed_msts", return_value=set()), \
         patch("laws.import_laws.mark_processed"), \
         patch("laws.import_laws.commit_law", return_value="abc1234"):
        mock_cache.list_cached_msts.return_value = ["253527"]
        count = import_laws.import_from_cache()

    assert count == 1
