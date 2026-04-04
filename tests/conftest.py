"""Shared fixtures for the legalize-pipeline test suite."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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
