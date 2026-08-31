"""Tests for laws.api_client.repair_law_xml."""

from xml.etree import ElementTree

import pytest

from laws.api_client import repair_law_xml


def _doc(body: str) -> bytes:
    return f'<?xml version="1.0" encoding="UTF-8"?><법령>{body}</법령>'.encode()


UNCLOSED = _doc(
    "<조문단위><조문번호>1</조문번호>"
    "<조문참고자료><![CDATA[[본조신설 1995.10.27]]]>"  # 닫는 태그 없음
    "<조문내용><![CDATA[제5장 소청]]></조문내용></조문단위>"
)


def test_repairs_unclosed_reference_element():
    with pytest.raises(ElementTree.ParseError):
        ElementTree.fromstring(UNCLOSED)

    repaired = repair_law_xml(UNCLOSED)
    root = ElementTree.fromstring(repaired)

    assert root.findtext(".//조문번호") == "1"
    assert root.findtext(".//조문내용") == "제5장 소청"


def test_repair_only_inserts_the_closing_tag():
    """본문이 변조되면 안 된다 — 삽입된 것이 닫는 태그뿐임을 대사한다."""
    repaired = repair_law_xml(UNCLOSED)

    assert repaired != UNCLOSED
    assert repaired.replace("</조문참고자료>".encode(), b"") == UNCLOSED.replace(
        "</조문참고자료>".encode(), b""
    )
    assert len(repaired) - len(UNCLOSED) == len("</조문참고자료>".encode())


def test_well_formed_input_is_returned_untouched():
    """정상 문서는 바이트 단위로 그대로 돌려줘야 한다."""
    good = _doc(
        "<조문단위><조문참고자료><![CDATA[참고]]></조문참고자료>"
        "<조문내용><![CDATA[본문]]></조문내용></조문단위>"
    )

    assert repair_law_xml(good) is good


def test_document_without_the_element_is_returned_untouched():
    good = _doc("<조문단위><조문내용><![CDATA[본문]]></조문내용></조문단위>")

    assert repair_law_xml(good) is good


def test_repair_is_idempotent():
    once = repair_law_xml(UNCLOSED)

    assert repair_law_xml(once) is once


def test_multiple_unclosed_elements_are_all_closed():
    doc = _doc(
        "<조문단위><조문참고자료><![CDATA[a]]>"
        "<조문참고자료><![CDATA[b]]>"
        "<조문내용><![CDATA[본문]]></조문내용></조문단위>"
    )

    root = ElementTree.fromstring(repair_law_xml(doc))

    assert [node.text for node in root.iter("조문참고자료")] == ["a", "b"]


def test_undecodable_input_is_left_alone():
    """복구를 시도할 수 없으면 원본을 그대로 돌려 호출자가 원 예외를 보게 한다."""
    raw = b"\xff\xfe not utf-8"

    assert repair_law_xml(raw) is raw
