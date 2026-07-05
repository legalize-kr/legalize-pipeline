from pathlib import Path

from ordinances.validate import validate_markdown_file


def test_validate_frontmatter_allows_attachment_values_with_dashes(tmp_path: Path):
    rel = Path("충청남도/천안시/규칙/천안시 테스트 규칙/본문.md")
    target = tmp_path / rel
    target.parent.mkdir(parents=True)
    target.write_text(
        """---
자치법규ID: '1'
자치법규명: '천안시 테스트 규칙'
자치법규종류: '규칙'
지자체기관명: '충청남도 천안시'
지자체구분:
  광역: '충청남도'
  기초: '천안시'
본문출처: 'api-text'
첨부파일:
  - 제목: '천안시 (일반,---강습) 회원가입신청서'
    파일링크: 'http://www.law.go.kr/flDownload.do?flNm=a---b'
---

# 천안시 테스트 규칙
""",
        encoding="utf-8",
    )

    assert validate_markdown_file(target, repo_root=tmp_path) == []


def test_validate_frontmatter_uses_unknown_jurisdiction_split(tmp_path: Path):
    rel = Path("_미상/(구)전라남도교육청/규칙/전남광주통합특별시교육청 행정심판위원회 규칙/본문.md")
    target = tmp_path / rel
    target.parent.mkdir(parents=True)
    target.write_text(
        """---
자치법규ID: '3397921'
자치법규명: '전남광주통합특별시교육청 행정심판위원회 규칙'
자치법규종류: '규칙'
지자체기관명: '(구)전라남도교육청'
지자체구분:
  광역: '_미상'
  기초: '(구)전라남도교육청'
본문출처: 'api-text'
첨부파일: []
---

# 전남광주통합특별시교육청 행정심판위원회 규칙
""",
        encoding="utf-8",
    )

    assert validate_markdown_file(target, repo_root=tmp_path) == []
