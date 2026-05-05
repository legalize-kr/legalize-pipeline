"""Tests for admrules/analyze_cache.py."""

from admrules.analyze_cache import analyze


def test_analyze_cache_counts_shape(tmp_path):
    (tmp_path / "1.xml").write_text(
        "<A><행정규칙종류>고시</행정규칙종류><소관부처명>행정안전부</소관부처명><발령일자>20240504</발령일자><조문내용>본문</조문내용></A>",
        encoding="utf-8",
    )
    result = analyze(tmp_path)
    assert result["total"] == 1
    assert result["by_type"] == {"고시": 1}
    assert result["body_sources"] == {"api-text": 1}
