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
