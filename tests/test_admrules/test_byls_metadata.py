"""Tests for admrules/byls_metadata.py."""

from admrules.byls_metadata import (
    AttachmentMetadata,
    fetch_attachment_metadata,
    infer_file_type,
    is_law_go_kr_url,
)


def test_is_law_go_kr_url_accepts_subdomain():
    assert is_law_go_kr_url("https://www.law.go.kr/example")


def test_is_law_go_kr_url_rejects_other_domain():
    assert not is_law_go_kr_url("https://example.com/file.hwp")


def test_infer_file_type_from_content_type():
    assert infer_file_type("https://www.law.go.kr/download", "application/pdf") == "pdf"
    assert infer_file_type("https://www.law.go.kr/download", "image/png") == "image"


def test_attachment_metadata_as_frontmatter():
    metadata = AttachmentMetadata(
        kind="별표",
        no="별표 1",
        title="서식",
        source_url="https://www.law.go.kr/file.hwp",
        pdf_url="https://www.law.go.kr/file.pdf",
        file_type="hwp",
        sha256="abc",
        size_bytes=3,
        fetched_at="2026-05-04",
    )
    assert metadata.as_frontmatter() == {
        "별표구분": "별표",
        "별표번호": "별표 1",
        "제목": "서식",
        "파일형식": "hwp",
        "파일링크": "https://www.law.go.kr/file.hwp",
        "PDF링크": "https://www.law.go.kr/file.pdf",
    }


def test_fetch_attachment_metadata(monkeypatch):
    class Response:
        content = b"abc"
        headers = {"Content-Type": "application/pdf"}

        def raise_for_status(self):
            return None

    def fake_get(url, timeout):
        assert url == "https://www.law.go.kr/file"
        assert timeout == 30
        return Response()

    monkeypatch.setattr("admrules.byls_metadata.requests.get", fake_get)

    metadata = fetch_attachment_metadata(
        kind="별표",
        no="별표 1",
        title="서식",
        source_url="https://www.law.go.kr/file",
    )
    assert metadata.file_type == "pdf"
    assert metadata.sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert metadata.size_bytes == 3


def test_fetch_attachment_metadata_rejects_non_law_go_kr():
    try:
        fetch_attachment_metadata(
            kind="별표",
            no="별표 1",
            title="서식",
            source_url="https://example.com/file",
        )
    except ValueError as e:
        assert "law.go.kr" in str(e)
    else:
        raise AssertionError("expected ValueError")
