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


def test_analyze_includes_withdrawn_history_and_prefers_active_duplicate(tmp_path):
    archive = tmp_path / "retired"
    archive.mkdir()
    (archive / "1.xml").write_text("<A><행정규칙종류>세칙</행정규칙종류></A>")
    (archive / "2.xml").write_text("<A><행정규칙종류>규정</행정규칙종류></A>")
    (tmp_path / "1.xml").write_text("<A><행정규칙종류>고시</행정규칙종류></A>")
    result = analyze(tmp_path)
    assert result["total"] == 2
    assert result["by_type"] == {"고시": 1, "규정": 1}
