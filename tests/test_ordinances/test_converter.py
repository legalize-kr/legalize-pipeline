import json
import datetime
from pathlib import Path

import pytest
import yaml

from ordinances import converter


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<자치법규>
  <자치법규ID>2000111</자치법규ID>
  <자치법규일련번호>12345</자치법규일련번호>
  <자치법규명>서울특별시 테스트 조례</자치법규명>
  <자치법규종류>조례</자치법규종류>
  <지자체기관명>서울특별시</지자체기관명>
  <공포일자>20210930</공포일자>
  <공포번호>7825</공포번호>
  <시행일자>20210930</시행일자>
  <제개정구분명>일부개정</제개정구분명>
  <자치법규분야명>일반공공행정</자치법규분야명>
  <담당부서명>법무담당관</담당부서명>
  <조문단위>
    <조문번호>1</조문번호>
    <조문제목>목적</조문제목>
    <조문내용>제1조(목적) 이 조례는 테스트를 목적으로 한다.</조문내용>
  </조문단위>
</자치법규>
"""


def _frontmatter(markdown: str) -> dict:
    _, yaml_text, _ = markdown.split("---", 2)
    return yaml.safe_load(yaml_text)


def test_xml_to_markdown_builds_depth_five_path_and_frontmatter():
    path, markdown = converter.xml_to_markdown(SAMPLE_XML)

    assert path == "서울특별시/_본청/조례/서울특별시 테스트 조례/본문.md"
    fm = _frontmatter(markdown)
    assert fm["자치법규ID"] == "2000111"
    assert fm["자치법규종류"] == "조례"
    assert fm["지자체구분"] == {"광역": "서울특별시", "기초": "_본청"}
    assert fm["본문출처"] == "api-text"
    assert "source_url" not in fm
    assert "# 서울특별시 테스트 조례" in markdown
    assert "##### 제1조 (목적)" in markdown


def test_xml_to_markdown_quotes_yaml_sensitive_name():
    xml = SAMPLE_XML.replace(
        "서울특별시 테스트 조례",
        "서울특별시 옥외행사 안전관리에\n등에 관한 조례",
    )
    _, markdown = converter.xml_to_markdown(xml)
    fm = _frontmatter(markdown)
    assert fm["자치법규명"] == "서울특별시 옥외행사 안전관리에 등에 관한 조례"


def test_xml_to_markdown_handles_real_ordinance_article_tags():
    xml = SAMPLE_XML.replace(
        """<조문단위>
    <조문번호>1</조문번호>
    <조문제목>목적</조문제목>
    <조문내용>제1조(목적) 이 조례는 테스트를 목적으로 한다.</조문내용>
  </조문단위>""",
        """<조문>
    <조>
      <조문번호>000100</조문번호>
      <조문여부>Y</조문여부>
      <조제목>목적</조제목>
      <조내용>제1조(목적) 이 조례는 테스트를 목적으로 한다.</조내용>
    </조>
  </조문>""",
    )

    path, markdown = converter.xml_to_markdown(xml)

    assert path == "서울특별시/_본청/조례/서울특별시 테스트 조례/본문.md"
    assert "##### 제1조 (목적)" in markdown
    assert "이 조례는 테스트를 목적으로 한다." in markdown


def test_xml_to_markdown_uses_addenda_when_articles_are_empty():
    xml = SAMPLE_XML.replace(
        """<조문단위>
    <조문번호>1</조문번호>
    <조문제목>목적</조문제목>
    <조문내용>제1조(목적) 이 조례는 테스트를 목적으로 한다.</조문내용>
  </조문단위>""",
        """<부칙>
    <부칙공포일자>20210930</부칙공포일자>
    <부칙공포번호>7825</부칙공포번호>
    <부칙내용>이 조례는 공포한 날부터 시행한다.</부칙내용>
  </부칙>""",
    )

    _, markdown = converter.xml_to_markdown(xml)

    assert "본문출처: 'api-text'" in markdown
    assert "## 부칙" in markdown
    assert "이 조례는 공포한 날부터 시행한다." in markdown


def test_xml_to_markdown_adds_attachment_links():
    xml = SAMPLE_XML.replace(
        "</자치법규>",
        """<별표>
    <별표단위 별표키="1">
      <별표번호>0001</별표번호>
      <별표가지번호>00</별표가지번호>
      <별표구분>서식</별표구분>
      <별표제목><![CDATA[[별지 제1호서식] 신청서]]></별표제목>
      <별표첨부파일구분>hwp</별표첨부파일구분>
      <별표첨부파일명><![CDATA[http://www.law.go.kr/flDownload.do?gubun=ELIS&flSeq=1&flNm=test]]></별표첨부파일명>
    </별표단위>
  </별표>
</자치법규>""",
    )

    _, markdown = converter.xml_to_markdown(xml)

    fm = _frontmatter(markdown)
    assert fm["첨부파일"] == [
        {
            "별표번호": "0001",
            "별표가지번호": "00",
            "별표구분": "서식",
            "제목": "[별지 제1호서식] 신청서",
            "파일형식": "hwp",
            "파일링크": "http://www.law.go.kr/flDownload.do?gubun=ELIS&flSeq=1&flNm=test",
        }
    ]


def test_xml_to_markdown_preserves_invalid_promulgation_date():
    xml = SAMPLE_XML.replace("<공포일자>20210930</공포일자>", "<공포일자>20240231</공포일자>")

    _, markdown = converter.xml_to_markdown(xml)

    fm = _frontmatter(markdown)
    assert fm["공포일자"] == datetime.date(1970, 1, 1)
    assert fm["공포일자보정"] is True


def test_xml_to_markdown_uses_neutral_stub_when_body_empty():
    xml = SAMPLE_XML.replace(
        """<조문단위>
    <조문번호>1</조문번호>
    <조문제목>목적</조문제목>
    <조문내용>제1조(목적) 이 조례는 테스트를 목적으로 한다.</조문내용>
  </조문단위>""",
        """<별표>
    <별표단위>
      <별표첨부파일구분>pdf</별표첨부파일구분>
      <별표첨부파일명>https://example.test/file.pdf</별표첨부파일명>
    </별표단위>
  </별표>""",
    )

    _, markdown = converter.xml_to_markdown(xml)

    assert "본문은 첨부파일 또는 원문을 참조하세요." in markdown
    assert "첨부파일(HWP)" not in markdown


def test_normalizes_additional_official_type_codes():
    assert converter.normalize_ordinance_type("C0010") == "고시"
    assert converter.normalize_ordinance_type("C0011") == "의회규칙"


def test_compute_path_replaces_slashes():
    converter.reset_path_registry()
    path = converter.compute_path({
        "자치법규종류": "규칙",
        "지자체기관명": "서울특별시 강남구",
        "자치법규명": 'A/B: "<규칙>"',
    })
    assert path == "서울특별시/강남구/규칙/A B 규칙/본문.md"


def test_compute_path_suffixes_collisions():
    converter.reset_path_registry()
    base = {
        "자치법규종류": "조례",
        "지자체기관명": "서울특별시",
        "자치법규명": "같은 이름 조례",
    }
    path1 = converter.compute_path({**base, "자치법규ID": "1", "공포번호": "100"}, use_registry=True)
    path2 = converter.compute_path({**base, "자치법규ID": "2", "공포번호": "101"}, use_registry=True)
    assert path1 == "서울특별시/_본청/조례/같은 이름 조례/본문.md"
    assert path2 == "서울특별시/_본청/조례/같은 이름 조례_101/본문.md"


def test_compute_path_reuses_path_for_same_ordinance_id_revisions():
    converter.reset_path_registry()
    base = {
        "자치법규종류": "조례",
        "지자체기관명": "서울특별시",
        "자치법규명": "같은 이름 조례",
        "자치법규ID": "1",
    }
    path1 = converter.compute_path({**base, "공포번호": "100"}, use_registry=True)
    path2 = converter.compute_path({**base, "공포번호": "101"}, use_registry=True)
    assert path1 == "서울특별시/_본청/조례/같은 이름 조례/본문.md"
    assert path2 == path1


def test_compute_path_collision_empty_prom_no_matches_compiler_suffix():
    converter.reset_path_registry()
    base = {
        "자치법규종류": "조례",
        "지자체기관명": "서울특별시",
        "자치법규명": "같은 이름 조례",
        "공포번호": "",
    }
    path1 = converter.compute_path({**base, "자치법규ID": "1"}, use_registry=True)
    path2 = converter.compute_path({**base, "자치법규ID": "2"}, use_registry=True)
    assert path1 == "서울특별시/_본청/조례/같은 이름 조례/본문.md"
    assert path2 == "서울특별시/_본청/조례/같은 이름 조례__/본문.md"


def test_quarantines_unsupported_type(tmp_path: Path, monkeypatch):
    failure_path = tmp_path / "failures.jsonl"
    monkeypatch.setattr(converter, "quarantine_type", lambda oid, typ: failure_path.write_text(json.dumps({"자치법규ID": oid, "자치법규종류": typ, "reason": "type_quarantined"}, ensure_ascii=False), encoding="utf-8"))

    detail = converter.parse_ordinance_xml(SAMPLE_XML.replace("<자치법규종류>조례</자치법규종류>", "<자치법규종류>기타</자치법규종류>"))
    with pytest.raises(converter.UnsupportedOrdinanceType):
        converter.ordinance_to_markdown(detail)

    assert "type_quarantined" in failure_path.read_text(encoding="utf-8")
