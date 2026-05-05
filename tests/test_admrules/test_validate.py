"""Tests for admrules/validate.py."""

from pathlib import Path

from admrules.validate import validate_frontmatter, validate_no_binary_files


def test_validate_frontmatter_accepts_valid_markdown(tmp_path: Path):
    path = tmp_path / "본문.md"
    path.write_text(
        """---
행정규칙ID: 'ABC'
행정규칙일련번호: '123'
행정규칙명: 공공데이터 관리지침
행정규칙종류: 고시
상위기관명: 행정안전부
소관부처명: 행정안전부
기관코드: null
발령일자: 2024-05-04
본문출처: api-text
출처: https://www.law.go.kr/행정규칙/공공데이터관리지침
첨부파일: []
발령일자보정: false
---

제1조 목적
""",
        encoding="utf-8",
    )
    assert validate_frontmatter(path) == []


def test_validate_frontmatter_rejects_invalid_type(tmp_path: Path):
    path = tmp_path / "본문.md"
    path.write_text(
        """---
행정규칙ID: 'ABC'
행정규칙일련번호: '123'
행정규칙명: 공공데이터 관리지침
행정규칙종류: 법률
상위기관명: 행정안전부
소관부처명: 행정안전부
발령일자: 2024-05-04
본문출처: api-text
출처: https://www.law.go.kr/행정규칙/공공데이터관리지침
---

본문
""",
        encoding="utf-8",
    )
    assert any("Invalid 행정규칙종류" in error for error in validate_frontmatter(path))


def test_validate_frontmatter_allows_link_only_attachment_metadata(tmp_path: Path):
    path = tmp_path / "본문.md"
    path.write_text(
        """---
행정규칙ID: 'ABC'
행정규칙일련번호: '123'
행정규칙명: 공공데이터 관리지침
행정규칙종류: 고시
상위기관명: 행정안전부
소관부처명: 행정안전부
발령일자: 2024-05-04
본문출처: api-text
출처: https://www.law.go.kr/행정규칙/공공데이터관리지침
첨부파일:
  - 별표구분: 별표
    제목: 수수료 --- 기준
    파일링크: https://www.law.go.kr/file.hwp
---

본문
""",
        encoding="utf-8",
    )
    assert validate_frontmatter(path) == []


def test_validate_no_binary_files_rejects_hwp(tmp_path: Path):
    (tmp_path / "file.hwp").write_bytes(b"binary")
    assert validate_no_binary_files(tmp_path)


def test_validate_frontmatter_rejects_bad_source_url(tmp_path: Path):
    path = tmp_path / "본문.md"
    path.write_text(
        """---
행정규칙ID: 'ABC'
행정규칙일련번호: '123'
행정규칙명: 공공데이터 관리지침
행정규칙종류: 고시
상위기관명: 행정안전부
소관부처명: 행정안전부
발령일자: 2024-05-04
본문출처: api-text
출처: https://example.com/admrule
---

본문
""",
        encoding="utf-8",
    )
    assert any("law.go.kr URL" in error for error in validate_frontmatter(path))


def test_validate_frontmatter_rejects_legacy_english_fields(tmp_path: Path):
    path = tmp_path / "본문.md"
    path.write_text(
        """---
행정규칙ID: 'ABC'
행정규칙일련번호: '123'
행정규칙명: 공공데이터 관리지침
행정규칙종류: 고시
상위기관명: 행정안전부
소관부처명: 행정안전부
발령일자: 2024-05-04
본문출처: api-text
출처: https://www.law.go.kr/행정규칙/공공데이터관리지침
첨부파일: []
source_url: ''
body_source: api-text
hwp_sha256: null
attachments_hwp: false
epoch_clamped: false
발령일자_raw: '20240504'
---

본문
""",
        encoding="utf-8",
    )
    errors = validate_frontmatter(path)
    assert any("Forbidden legacy field: source_url" in error for error in errors)
    assert any("Forbidden legacy field: body_source" in error for error in errors)
    assert any("Forbidden legacy field: hwp_sha256" in error for error in errors)
    assert any("Forbidden legacy field: attachments_hwp" in error for error in errors)
    assert any("Forbidden legacy field: epoch_clamped" in error for error in errors)
    assert any("Forbidden legacy field: 발령일자_raw" in error for error in errors)


def test_validate_frontmatter_allows_clamped_pre_1970(tmp_path: Path):
    path = tmp_path / "본문.md"
    path.write_text(
        """---
행정규칙ID: 'ABC'
행정규칙일련번호: '123'
행정규칙명: 옛 규칙
행정규칙종류: 훈령
상위기관명: 총무처
소관부처명: 총무처
발령일자: 1970-01-01
본문출처: parsing-failed
출처: https://www.law.go.kr/행정규칙/옛규칙
첨부파일: []
발령일자보정: true
발령일자원문: '19650101'
---

본문은 국가법령정보센터 원문 또는 첨부파일을 참조하세요.
""",
        encoding="utf-8",
    )
    assert validate_frontmatter(path) == []


def test_validate_frontmatter_rejects_api_text_empty_body(tmp_path: Path):
    path = tmp_path / "본문.md"
    path.write_text(
        """---
행정규칙ID: 'ABC'
행정규칙일련번호: '123'
행정규칙명: 빈 본문
행정규칙종류: 고시
상위기관명: 행정안전부
소관부처명: 행정안전부
발령일자: 2024-05-04
본문출처: api-text
출처: https://www.law.go.kr/행정규칙/빈본문
---

""",
        encoding="utf-8",
    )
    assert any("non-empty body" in error for error in validate_frontmatter(path))


def test_validate_frontmatter_parse_errors(tmp_path: Path):
    no_fm = tmp_path / "no.md"
    no_fm.write_text("본문", encoding="utf-8")
    assert validate_frontmatter(no_fm) == ["No YAML frontmatter"]

    unterminated = tmp_path / "unterminated.md"
    unterminated.write_text("---\n행정규칙ID: ABC\n", encoding="utf-8")
    assert validate_frontmatter(unterminated) == ["Unterminated YAML frontmatter"]

    scalar = tmp_path / "scalar.md"
    scalar.write_text("---\ntext\n---\n", encoding="utf-8")
    assert validate_frontmatter(scalar) == ["Frontmatter is not a dict"]


def test_validate_frontmatter_reports_required_and_field_errors(tmp_path: Path):
    path = tmp_path / "본문.md"
    path.write_text(
        """---
행정규칙ID: 'ABC'
행정규칙일련번호: '123'
행정규칙명: 공공데이터 관리지침
행정규칙종류: 고시
소관부처명: ''
기관코드: ABC-1
발령일자: not-a-date
본문출처: unknown
출처: https://www.law.go.kr/행정규칙/공공데이터관리지침
---

본문
""",
        encoding="utf-8",
    )
    errors = validate_frontmatter(path)
    assert any("기관코드 must be alphanumeric" in error for error in errors)
    assert any("발령일자 must be a YAML date" in error for error in errors)
    assert any("Invalid 본문출처" in error for error in errors)


def test_validate_frontmatter_requires_org_code_or_name(tmp_path: Path):
    path = tmp_path / "본문.md"
    path.write_text(
        """---
행정규칙ID: 'ABC'
행정규칙일련번호: '123'
행정규칙명: 공공데이터 관리지침
행정규칙종류: 고시
소관부처명: ''
발령일자: 2024-05-04
본문출처: api-text
출처: https://www.law.go.kr/행정규칙/공공데이터관리지침
---

본문
""",
        encoding="utf-8",
    )
    assert any("Either 기관코드 or 소관부처명" in error for error in validate_frontmatter(path))


def test_validate_frontmatter_rejects_future_date_and_bad_clamp(tmp_path: Path):
    path = tmp_path / "본문.md"
    path.write_text(
        """---
행정규칙ID: 'ABC'
행정규칙일련번호: '123'
행정규칙명: 미래 규칙
행정규칙종류: 고시
소관부처명: 행정안전부
발령일자: 2999-01-01
본문출처: api-text
출처: https://www.law.go.kr/행정규칙/미래규칙
발령일자보정: true
---

본문
""",
        encoding="utf-8",
    )
    errors = validate_frontmatter(path)
    assert any("more than one year in the future" in error for error in errors)
    assert any("발령일자보정 true requires" in error for error in errors)
    assert any("발령일자원문 is required" in error for error in errors)


def test_validate_frontmatter_rejects_non_dict_and_bad_attachment_url(tmp_path: Path):
    path = tmp_path / "본문.md"
    path.write_text(
        """---
행정규칙ID: 'ABC'
행정규칙일련번호: '123'
행정규칙명: 공공데이터 관리지침
행정규칙종류: 고시
소관부처명: 행정안전부
발령일자: 2024-05-04
본문출처: api-text
출처: https://www.law.go.kr/행정규칙/공공데이터관리지침
첨부파일:
  - raw
  - 별표구분: 별표
    파일링크: https://example.com/file.hwp
---

본문
""",
        encoding="utf-8",
    )
    errors = validate_frontmatter(path)
    assert any("첨부파일[0] must be a dict" in error for error in errors)
    assert any("첨부파일[1].파일링크 must be a law.go.kr URL" in error for error in errors)


def test_validate_frontmatter_accepts_site_relative_attachment_url(tmp_path: Path):
    path = tmp_path / "본문.md"
    path.write_text(
        """---
행정규칙ID: 'ABC'
행정규칙일련번호: '123'
행정규칙명: 공공데이터 관리지침
행정규칙종류: 고시
상위기관명: 행정안전부
소관부처명: 행정안전부
발령일자: 2024-05-04
본문출처: api-text
출처: https://www.law.go.kr/행정규칙/공공데이터관리지침
첨부파일:
  - 별표구분: 별표
    파일링크: /DRF/file.hwp
---

본문
""",
        encoding="utf-8",
    )
    assert validate_frontmatter(path) == []
