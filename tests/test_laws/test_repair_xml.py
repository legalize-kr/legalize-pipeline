"""Verify narrow reference repairs and detail cache publication."""

import logging
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from core.counter import Counter
from laws import api_client as api, cache, detail_failure_allowlist, fetch_cache

REFERENCE = "<조문참고자료><![CDATA[참고 <조문내용> 문자열]]>"
CLOSE = "</조문참고자료>"
BODY = "제1조 본문 & 보존"
ARTICLE = f"<조문내용><![CDATA[{BODY}]]></조문내용>"


def document(content, suffix=""):
    return (
        '<법령><기본정보><법령명_한글>시험법</법령명_한글>'
        '<법령ID>123</법령ID></기본정보><조문><조문단위>'
        f'<조문번호>1</조문번호>{content}</조문단위></조문>{suffix}</법령>'
    ).encode()


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, 'CACHE_DIR', tmp_path / 'cache')


def respond(monkeypatch, raw):
    monkeypatch.setattr(api, '_request', lambda *a, **kw: SimpleNamespace(content=raw))


@pytest.mark.parametrize('tag', ['<조문내용>', '<조문내용 >', '<조문내용\n>', '<조문내용\t>'])
def test_real_boundary_preserves_bytes_and_parent(tag):
    article = ARTICLE.replace('<조문내용>', tag)
    raw = document(REFERENCE + article)
    expected = document(REFERENCE + CLOSE + article)
    repaired = api.repair_law_xml(raw)
    assert repaired == expected
    root = ET.fromstring(repaired)
    assert root.findtext('.//조문단위/조문내용') == BODY
    assert root.findtext('.//조문참고자료') == '참고 <조문내용> 문자열'
    assert api.repair_law_xml(repaired) is repaired


@pytest.mark.parametrize('reference', [
    '<조문참고자료><![CDATA[<조문내용> 가짜 </조문참고자료>]]>',
    '<조문참고자료><![CDATA[한글]]>\n<![CDATA[추가]]>\t',
    '<조문참고자료 > <![CDATA[참고]]>\r\n',
])
def test_reference_variants(reference):
    raw = document(reference + ARTICLE)
    assert api.repair_law_xml(raw) == document(reference + CLOSE + ARTICLE)


def test_multiple_and_mixed_references():
    closed = '<조문참고자료><![CDATA[정상]]></조문참고자료>'
    raw = document(closed + REFERENCE + REFERENCE + ARTICLE)
    expected = document(closed + REFERENCE + CLOSE + REFERENCE + CLOSE + ARTICLE)
    assert api.repair_law_xml(raw) == expected


def test_parent_close_boundary_and_bom():
    raw = b'\xef\xbb\xbf' + document(ARTICLE + REFERENCE)
    assert api.repair_law_xml(raw) == b'\xef\xbb\xbf' + document(ARTICLE + REFERENCE + CLOSE)


@pytest.mark.parametrize('content', [
    ARTICLE,
    REFERENCE + CLOSE + ARTICLE,
    '<조문참고자료><기타>정상</기타></조문참고자료>' + ARTICLE,
])
def test_valid_input_identity(content):
    raw = document(content)
    assert api.repair_law_xml(raw) is raw


@pytest.mark.parametrize('raw', [
    document(REFERENCE + '<항><항내용>항</항내용></항>' + ARTICLE),
    document(REFERENCE + '<조문내용추가>본문</조문내용추가>'),
    document('<조문참고자료>일반 텍스트' + ARTICLE),
    document(REFERENCE + '<조문내용 속성="값">본문</조문내용>'),
    document(REFERENCE + '<!-- 미종료' + ARTICLE),
    document(REFERENCE + ARTICLE, '<x></y>'),
    '<!DOCTYPE 법령>'.encode() + document(REFERENCE + ARTICLE),
    '<법령><기타><조문참고자료><![CDATA[x]]><조문내용>x</조문내용></기타></법령>'.encode(),
    document(REFERENCE + ARTICLE).decode().encode('utf-16'),
    b'\xff\xfe invalid',
])
def test_unsupported_input_is_unchanged(raw):
    assert api.repair_law_xml(raw) is raw


def test_fake_boundaries_outside_candidate():
    prefix = '<!-- <조문참고자료> --><기타 attr="&lt;조문내용&gt;"/><?test fake="<조문참고자료>"?>'
    raw = document(prefix + REFERENCE + ARTICLE)
    assert api.repair_law_xml(raw) == document(prefix + REFERENCE + CLOSE + ARTICLE)


@pytest.mark.parametrize('cached', [False, True])
def test_detail_repairs_and_publishes_for_offline_reuse(monkeypatch, caplog, cached):
    nested = '<항><항내용>항 본문</항내용><호><호내용>호 본문</호내용><목><목내용>목 본문</목내용></목></호></항>'
    raw = document(REFERENCE + ARTICLE.replace('<조문내용>', '<조문내용 >') + nested)
    respond(monkeypatch, raw)
    if cached:
        cache.put_detail('123', raw)
        monkeypatch.setattr(api, '_request', lambda *a, **kw: pytest.fail('Network call on cache hit'))
    with caplog.at_level(logging.WARNING):
        result = api.get_law_detail('123')
    assert result['metadata']['법령명한글'] == '시험법'
    assert result['metadata']['법령ID'] == '123'
    assert result['articles'][0]['조문내용'] == BODY
    assert result['articles'][0]['항'][0]['호'][0]['목'][0]['목내용'] == '목 본문'
    assert result['raw_xml'] == cache.get_detail('123') == api.repair_law_xml(raw)
    assert len([r for r in caplog.records if 'Repaired malformed XML' in r.message and '123' in r.message]) == 1
    path = cache._detail_path('123')
    before = path.stat().st_mtime_ns
    monkeypatch.setattr(api, '_request', lambda *a, **kw: pytest.fail('Network call on cache hit'))
    caplog.clear()
    assert api.get_law_detail('123') == result
    assert path.stat().st_mtime_ns == before
    assert not caplog.records


@pytest.mark.parametrize('cached', [False, True])
def test_original_error_and_cache_survive_failure(monkeypatch, caplog, cached):
    raw = document(REFERENCE + ARTICLE, '<x></y>')
    respond(monkeypatch, raw)
    if cached:
        cache.put_detail('123', raw)
    original = []
    parse = api.ElementTree.fromstring

    def capture(*args, **kwargs):
        try:
            return parse(*args, **kwargs)
        except ET.ParseError as error:
            original.append(error)
            raise

    monkeypatch.setattr(api.ElementTree, 'fromstring', capture)
    with pytest.raises(ET.ParseError) as caught:
        api.get_law_detail('123')
    assert caught.value is original[0]
    assert cache.get_detail('123') == (raw if cached else None)
    assert not caplog.records


def test_no_cache_publication_before_attachment_extraction(monkeypatch):
    respond(monkeypatch, document(REFERENCE + ARTICLE))

    def fail(root):
        raise RuntimeError('attachment extraction failed')

    monkeypatch.setattr(api, '_attachments_from_xml', fail)
    with pytest.raises(RuntimeError, match='attachment extraction failed'):
        api.get_law_detail('123')
    assert cache.get_detail('123') is None


def test_failed_second_parse_keeps_original_position(monkeypatch):
    raw = document(REFERENCE + ARTICLE, '<x></y>')
    respond(monkeypatch, raw)
    with pytest.raises(ET.ParseError) as original:
        ET.fromstring(raw)
    monkeypatch.setattr(api, 'repair_law_xml', lambda value: value.replace(
        REFERENCE.encode(), (REFERENCE + CLOSE).encode()))
    with pytest.raises(ET.ParseError) as caught:
        api.get_law_detail('123')
    assert caught.value.position == original.value.position
    assert caught.value.code == original.value.code
    assert str(caught.value) == str(original.value)
    assert cache.get_detail('123') is None


def test_undefined_entity_still_fails_without_cache(monkeypatch):
    raw = document('<조문내용>A & B</조문내용>')
    respond(monkeypatch, raw)
    with pytest.raises(ET.ParseError):
        api.get_law_detail('123')
    assert cache.get_detail('123') is None


@pytest.mark.parametrize('supported', [True, False])
def test_fetch_task_does_not_hide_success_in_allowlist(monkeypatch, supported):
    entry = {'mst': '123', 'law_name': '시험법', 'reason': 'upstream_malformed_xml',
             'expected_error': 'mismatched tag', 'expires_on': '2099-01-01'}
    monkeypatch.setattr(detail_failure_allowlist, 'load_allowlist', lambda: {'123': entry})
    raw = document(REFERENCE + ARTICLE, '' if supported else '<x></y>')
    respond(monkeypatch, raw)
    counter = Counter()
    fetch_cache._fetch_detail_task('123', '시험법', counter)
    counts = counter.snapshot_all()
    assert counts['fetched'] == int(supported)
    assert counts.get('known_failures', 0) == int(not supported)
    assert counts['errors'] == 0
    assert (cache.get_detail('123') is not None) == supported
