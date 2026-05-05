"""Tests for admrules/converter.py."""

import datetime

import yaml

from admrules.converter import (
    build_frontmatter,
    format_date,
    get_admrule_path,
    normalize_ministry_name,
    reset_path_registry,
    resolve_ministry_names,
    resolve_org_path,
    safe_path_part,
    xml_to_markdown,
)


def test_format_date_compact():
    assert format_date("20240504") == "2024-05-04"


def test_safe_path_part_normalizes_slashes_and_caps_bytes():
    value = safe_path_part('행정/규칙:"<>')
    assert value == "행정 규칙"
    assert len(value.encode("utf-8")) <= 180


def test_get_admrule_path_basic():
    reset_path_registry()
    path = get_admrule_path({
        "소관부처명": "행정안전부",
        "행정규칙종류": "고시",
        "행정규칙명": "공공데이터 관리지침",
        "행정규칙일련번호": "100",
    })
    assert path == "행정안전부/_본부/고시/공공데이터 관리지침/본문.md"


def test_get_admrule_path_groups_subagency_under_parent():
    reset_path_registry()
    path = get_admrule_path({
        "상위기관명": "국토교통부",
        "소관부처명": "제주지방항공청",
        "행정규칙종류": "훈령",
        "행정규칙명": "제주지방항공청 사무분장 규정",
        "행정규칙일련번호": "100",
    })
    assert path == "국토교통부/제주지방항공청/훈령/제주지방항공청 사무분장 규정/본문.md"


def test_get_admrule_path_collision_suffixes_issue_number():
    reset_path_registry()
    base = {
        "소관부처명": "행정안전부",
        "행정규칙종류": "고시",
        "행정규칙명": "같은 이름",
    }
    path1 = get_admrule_path({**base, "행정규칙일련번호": "100", "발령번호": "제1호"})
    path2 = get_admrule_path({**base, "행정규칙일련번호": "200", "발령번호": "제2호"})
    assert path1 == "행정안전부/_본부/고시/같은 이름/본문.md"
    assert path2 == "행정안전부/_본부/고시/같은 이름_제2호/본문.md"


def test_get_admrule_path_collision_falls_back_to_serial_candidates():
    reset_path_registry()
    base = {
        "소관부처명": "행정안전부",
        "행정규칙종류": "고시",
        "행정규칙명": "같은 이름",
        "발령번호": "제1호",
    }
    path1 = get_admrule_path({**base, "행정규칙일련번호": "100"})
    path2 = get_admrule_path({**base, "행정규칙일련번호": "200"})
    path3 = get_admrule_path({**base, "행정규칙일련번호": "300"})
    assert path1 == "행정안전부/_본부/고시/같은 이름/본문.md"
    assert path2 == "행정안전부/_본부/고시/같은 이름_제1호/본문.md"
    assert path3 == "행정안전부/_본부/고시/같은 이름_300/본문.md"


def test_normalize_ministry_name_uses_parent_for_date_value():
    assert normalize_ministry_name("2025-10-01", "기후에너지환경부") == "기후에너지환경부"


def test_normalize_ministry_name_unifies_itaewon_middle_dot():
    assert (
        normalize_ministry_name("10.29이태원참사진상규명과재발방지를위한특별조사위원회")
        == "10·29이태원참사진상규명과재발방지를위한특별조사위원회"
    )


def test_normalize_ministry_name_maps_safe_ministry_renames():
    assert normalize_ministry_name("문화재청") == "국가유산청"
    assert normalize_ministry_name("통계청") == "국가데이터처"
    assert normalize_ministry_name("특허청") == "지식재산처"
    assert normalize_ministry_name("국립환경인력개발원") == "국립환경인재개발원"
    assert normalize_ministry_name("행정자치부") == "행정안전부"
    assert normalize_ministry_name("기획재정부") == "재정경제부"
    assert normalize_ministry_name("평생교육진흥원") == "국가평생교육진흥원"
    assert normalize_ministry_name("방송통신사무소") == "방송미디어통신사무소"


def test_resolve_ministry_names_uses_canonical_parent_for_path_grouping():
    assert resolve_ministry_names("원주지방환경청", "환경부") == (
        "기후에너지환경부",
        "원주지방환경청",
    )
    assert resolve_ministry_names("환경부", "환경부") == (
        "기후에너지환경부",
        "기후에너지환경부",
    )


def test_resolve_ministry_names_splits_compound_parent_with_department_agency():
    assert resolve_ministry_names(
        "환경보건정책과",
        "기후에너지환경부 국립환경과학원",
        "국립환경과학원(환경보건정책과)",
    ) == ("기후에너지환경부", "국립환경과학원")


def test_get_admrule_path_uses_current_top_level_agency_for_split_ministry():
    reset_path_registry()
    path = get_admrule_path({
        "상위부처명": "국토해양부",
        "소관부처명": "국토해양부",
        "담당부서기관명": "해양수산부(해양영토과)",
        "행정규칙종류": "고시",
        "행정규칙명": "무인도서 관리유형 재지정(변경) 고시",
        "행정규칙일련번호": "100",
    })
    assert path == "해양수산부/_본부/고시/무인도서 관리유형 재지정(변경) 고시/본문.md"


def test_resolve_ministry_names_collapses_historical_root_ministry_under_current_top():
    cases = [
        ("교육부", "문교부"),
        ("교육부", "교육인적자원부"),
        ("교육부", "교육과학기술부"),
        ("과학기술정보통신부", "교육과학기술부"),
        ("고용노동부", "노동부"),
        ("외교부", "외교통상부"),
        ("해양수산부", "국토해양부"),
        ("기후에너지환경부", "국토해양부"),
        ("산업통상부", "지식경제부"),
        ("과학기술정보통신부", "정보통신부"),
        ("문화체육관광부", "문화관광부"),
        ("행정안전부", "안전행정부"),
        ("보건복지부", "보건복지가족부"),
        ("농림축산식품부", "농림부"),
        ("농림축산식품부", "농림수산부"),
        ("농림축산식품부", "농림수산식품부"),
        ("해양수산부", "농림수산식품부"),
    ]
    for current, historical in cases:
        assert resolve_ministry_names(
            historical,
            current,
            f"{current}(운영지원과)",
        ) == (current, current)


def test_get_admrule_path_collapses_historical_root_ministry_to_current_headquarters():
    reset_path_registry()
    path = get_admrule_path({
        "상위부처명": "농림축산식품부",
        "소관부처명": "농림수산식품부",
        "담당부서기관명": "농림축산식품부(농업기반과)",
        "행정규칙종류": "고시",
        "행정규칙명": "고흥지구 서남해안 간척사업 준공검사 확인 고시",
        "행정규칙일련번호": "2000000022013",
    })
    assert path == "농림축산식품부/_본부/고시/고흥지구 서남해안 간척사업 준공검사 확인 고시/본문.md"


def test_resolve_org_path_applies_legal_parent_chain_for_external_agencies():
    assert resolve_org_path("병무청", "병무청") == ["국방부", "병무청"]
    assert resolve_org_path("산림청", "국립산림과학원") == [
        "농림축산식품부",
        "산림청",
        "국립산림과학원",
    ]
    assert resolve_org_path("대검찰청", "대검찰청") == ["법무부", "대검찰청"]
    assert resolve_org_path("국립농산물품질관리원", "국립농산물품질관리원") == [
        "농림축산식품부",
        "국립농산물품질관리원",
    ]
    assert resolve_org_path(
        "민주평화통일자문회의사무처",
        "민주평화통일자문회의사무처",
    ) == ["대통령", "민주평화통일자문회의사무처"]
    assert resolve_org_path("국립전파연구원", "국립전파연구원") == [
        "과학기술정보통신부",
        "국립전파연구원",
    ]
    assert resolve_org_path("중앙전파관리소", "중앙전파관리소") == [
        "과학기술정보통신부",
        "중앙전파관리소",
    ]
    assert resolve_org_path("전파관리소", "전파관리소") == [
        "과학기술정보통신부",
        "중앙전파관리소",
        "전파관리소",
    ]


def test_get_admrule_path_uses_legal_parent_for_prime_minister_and_presidential_agencies():
    reset_path_registry()
    law_path = get_admrule_path({
        "상위부처명": "법무부",
        "소관부처명": "법제처",
        "담당부서기관명": "법제처(운영지원과)",
        "행정규칙종류": "훈령",
        "행정규칙명": "법제처 훈령",
        "행정규칙일련번호": "100",
    })
    assert law_path == "국무총리/법제처/훈령/법제처 훈령/본문.md"

    education_path = get_admrule_path({
        "상위부처명": "교육부",
        "소관부처명": "국가교육위원회",
        "담당부서기관명": "국가교육위원회(운영지원과)",
        "행정규칙종류": "고시",
        "행정규칙명": "국가교육위원회 규칙",
        "행정규칙일련번호": "101",
    })
    assert education_path == "대통령/국가교육위원회/고시/국가교육위원회 규칙/본문.md"

    office_path = get_admrule_path({
        "상위부처명": "방송통신위원회",
        "소관부처명": "방송통신사무소",
        "담당부서기관명": "방송미디어통신사무소",
        "행정규칙종류": "훈령",
        "행정규칙명": "방송미디어통신사무소 세칙",
        "행정규칙일련번호": "102",
    })
    assert (
        office_path
        == "대통령/방송미디어통신위원회/방송미디어통신사무소/훈령/방송미디어통신사무소 세칙/본문.md"
    )


def test_get_admrule_path_does_not_replace_current_root_with_unrelated_department_agency():
    reset_path_registry()
    path = get_admrule_path({
        "상위부처명": "국방부",
        "소관부처명": "국방부",
        "담당부서기관명": "법제처(법제지원총괄과)",
        "행정규칙종류": "훈령",
        "행정규칙명": "국방전자기스펙트럼 업무 훈령",
        "행정규칙일련번호": "100",
    })
    assert path == "국방부/_본부/훈령/국방전자기스펙트럼 업무 훈령/본문.md"


def test_get_admrule_path_uses_verified_department_root_for_current_split_functions():
    reset_path_registry()
    path = get_admrule_path({
        "상위부처명": "산업통상부",
        "소관부처명": "산업통상부",
        "담당부서기관명": "기후에너지환경부(전력산업정책과)",
        "행정규칙종류": "고시",
        "행정규칙명": "전력산업 고시",
        "행정규칙일련번호": "100",
    })
    assert path == "기후에너지환경부/_본부/고시/전력산업 고시/본문.md"


def test_get_admrule_path_keeps_stale_broadcast_commission_rule_under_current_science_ministry():
    reset_path_registry()
    path = get_admrule_path({
        "상위부처명": "과학기술정보통신부",
        "소관부처명": "방송통신위원회",
        "담당부서기관명": "과학기술정보통신부(주파수정책과)",
        "행정규칙종류": "공고",
        "행정규칙명": "이동통신 주파수 할당",
        "행정규칙일련번호": "100",
    })
    assert path == "과학기술정보통신부/_본부/공고/이동통신 주파수 할당/본문.md"


def test_get_admrule_path_uses_current_environment_ministry_for_river_rules():
    reset_path_registry()
    path = get_admrule_path({
        "상위부처명": "기후에너지환경부",
        "소관부처명": "국토교통부",
        "담당부서기관명": "기후에너지환경부(하천계획과)",
        "행정규칙종류": "훈령",
        "행정규칙명": "하천에 관한 사무처리규정",
        "행정규칙일련번호": "2100000079411",
    })
    assert path == "기후에너지환경부/_본부/훈령/하천에 관한 사무처리규정/본문.md"


def test_get_admrule_path_keeps_independent_special_committee_as_root():
    reset_path_registry()
    path = get_admrule_path({
        "상위부처명": "행정안전부",
        "소관부처명": "10.29이태원참사진상규명과재발방지를위한특별조사위원회",
        "담당부서기관명": "10·29이태원참사진상규명과재발방지를위한특별조사위원회(운영지원과)",
        "행정규칙종류": "고시",
        "행정규칙명": "10·29 위원회 규칙",
        "행정규칙일련번호": "100",
    })
    assert (
        path
        == "10·29이태원참사진상규명과재발방지를위한특별조사위원회/_본부/고시/10·29 위원회 규칙/본문.md"
    )


def test_get_admrule_path_maps_government_affiliated_public_bodies():
    reset_path_registry()
    landfill_path = get_admrule_path({
        "상위부처명": "정부산하기관및위원회",
        "소관부처명": "수도권매립지관리공사",
        "담당부서기관명": "수도권매립지관리공사",
        "행정규칙종류": "고시",
        "행정규칙명": "수도권매립지 고시",
        "행정규칙일련번호": "100",
    })
    assert landfill_path == "기후에너지환경부/수도권매립지관리공사/고시/수도권매립지 고시/본문.md"

    education_path = get_admrule_path({
        "상위부처명": "정부산하기관및위원회",
        "소관부처명": "평생교육진흥원",
        "담당부서기관명": "평생교육진흥원",
        "행정규칙종류": "고시",
        "행정규칙명": "학점인정 기준",
        "행정규칙일련번호": "101",
    })
    assert education_path == "교육부/국가평생교육진흥원/고시/학점인정 기준/본문.md"


def test_xml_to_markdown_preserves_raw_ministry_when_mapped():
    xml = """
    <AdmRulService>
      <행정규칙ID>ABC</행정규칙ID>
      <행정규칙일련번호>123</행정규칙일련번호>
      <행정규칙명>문화재 테스트 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>문화재청</소관부처명>
      <발령일자>20240504</발령일자>
      <조문내용>제1조 목적</조문내용>
    </AdmRulService>
    """
    md = xml_to_markdown(xml)
    assert "상위기관명: '문화체육관광부'" in md
    assert "소관부처명: '국가유산청'" in md
    assert "- '문화체육관광부'" in md
    assert "- '국가유산청'" in md
    assert "소관부처명_원문: '문화재청'" in md


def test_build_frontmatter_clamps_pre_1970_issue_date():
    fm = build_frontmatter({
        "행정규칙ID": "A",
        "행정규칙일련번호": "1",
        "행정규칙명": "옛 규칙",
        "행정규칙종류": "훈령",
        "소관부처명": "총무처",
        "발령일자": "19650101",
    })
    assert fm["발령일자"] == datetime.date(1970, 1, 1)
    assert fm["발령일자보정"] is True
    assert fm["발령일자원문"] == "19650101"


def test_build_frontmatter_clamps_invalid_issue_date():
    fm = build_frontmatter({
        "행정규칙ID": "A",
        "행정규칙일련번호": "1",
        "행정규칙명": "잘못된 날짜 규칙",
        "행정규칙종류": "훈령",
        "소관부처명": "총무처",
        "발령일자": "20240231",
    })
    assert fm["발령일자"] == datetime.date(1970, 1, 1)
    assert fm["발령일자보정"] is True
    assert fm["발령일자원문"] == "20240231"


def test_xml_to_markdown_extracts_frontmatter_and_body():
    xml = """
    <AdmRulService>
      <행정규칙ID>ABC</행정규칙ID>
      <행정규칙일련번호>123</행정규칙일련번호>
      <행정규칙명>공공데이터 관리지침</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령번호>제2024-1호</발령번호>
      <발령일자>20240504</발령일자>
      <시행일자>20240505</시행일자>
      <제개정구분명>일부개정</제개정구분명>
      <조문내용>제1조 목적</조문내용>
    </AdmRulService>
    """
    md = xml_to_markdown(xml)
    assert "행정규칙ID: 'ABC'" in md
    assert "본문출처: 'api-text'" in md
    assert "발령일자: 2024-05-04" in md
    for legacy_key in (
        "source_url:",
        "body_source:",
        "hwp_sha256:",
        "attachments_hwp:",
        "epoch_clamped:",
        "발령일자_raw:",
    ):
        assert legacy_key not in md
    assert "제1조 목적" in md


def test_xml_to_markdown_quotes_yaml_sensitive_title():
    xml = """
    <AdmRulService>
      <행정규칙ID>ABC</행정규칙ID>
      <행정규칙일련번호>123</행정규칙일련번호>
      <행정규칙명>기록관 표준운영절차: 일반</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240504</발령일자>
      <조문내용>제1조 목적</조문내용>
    </AdmRulService>
    """
    md = xml_to_markdown(xml)
    _, yaml_text, _ = md.split("---", 2)
    fm = yaml.safe_load(yaml_text)
    assert fm["행정규칙명"] == "기록관 표준운영절차: 일반"


def test_xml_to_markdown_adds_attachment_links():
    xml = """
    <AdmRulService>
      <행정규칙ID>ABC</행정규칙ID>
      <행정규칙일련번호>123</행정규칙일련번호>
      <행정규칙명>첨부 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240504</발령일자>
      <조문내용>제1조 목적</조문내용>
      <별표>
        <별표번호>0001</별표번호>
        <별표가지번호>00</별표가지번호>
        <별표구분>별표</별표구분>
        <별표제목><![CDATA[수수료]]></별표제목>
        <별표서식파일링크>/LSW/flDownload.do?flSeq=1</별표서식파일링크>
        <별표서식PDF파일링크>/LSW/flDownload.do?flSeq=2</별표서식PDF파일링크>
      </별표>
    </AdmRulService>
    """

    md = xml_to_markdown(xml)
    _, yaml_text, _ = md.split("---", 2)
    fm = yaml.safe_load(yaml_text)

    assert fm["첨부파일"] == [{
        "별표번호": "0001",
        "별표가지번호": "00",
        "별표구분": "별표",
        "제목": "수수료",
        "파일링크": "https://www.law.go.kr/LSW/flDownload.do?flSeq=1",
        "PDF링크": "https://www.law.go.kr/LSW/flDownload.do?flSeq=2",
    }]


def test_xml_to_markdown_uses_parsing_failed_stub_when_body_empty():
    xml = """
    <AdmRulService>
      <행정규칙ID>ABC</행정규칙ID>
      <행정규칙일련번호>123</행정규칙일련번호>
      <행정규칙명>첨부 전용 고시</행정규칙명>
      <행정규칙종류>고시</행정규칙종류>
      <소관부처명>행정안전부</소관부처명>
      <발령일자>20240504</발령일자>
    </AdmRulService>
    """
    md = xml_to_markdown(xml)
    assert "본문출처: 'parsing-failed'" in md
    assert "본문은 국가법령정보센터 원문 또는 첨부파일을 참조하세요." in md
