"""Tests for ordinances/analyze_cache.py."""

from ordinances.analyze_cache import analyze


def test_analyze_cache_counts_shape(tmp_path):
    (tmp_path / "1.xml").write_text(
        "<O><자치법규종류>C0001</자치법규종류><지자체기관명>서울특별시</지자체기관명><공포일자>20240504</공포일자><조내용>본문</조내용></O>",
        encoding="utf-8",
    )
    result = analyze(tmp_path)
    assert result["total"] == 1
    assert result["by_type"] == {"조례": 1}
    assert result["by_region"] == {"서울특별시": 1}
    assert result["body_sources"] == {"api-text": 1}


def test_analyze_cache_counts_addenda_as_api_text(tmp_path):
    (tmp_path / "1.xml").write_text(
        "<O><자치법규종류>C0001</자치법규종류><지자체기관명>서울특별시</지자체기관명><공포일자>20240504</공포일자><부칙내용>시행한다.</부칙내용></O>",
        encoding="utf-8",
    )
    result = analyze(tmp_path)
    assert result["body_sources"] == {"api-text": 1}
