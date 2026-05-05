"""Attachment metadata helpers for administrative rule 별표/서식 links."""

import hashlib
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse

import requests


@dataclass(frozen=True)
class AttachmentMetadata:
    kind: str
    no: str
    title: str
    source_url: str
    pdf_url: str
    file_type: str
    sha256: str
    size_bytes: int
    fetched_at: str

    def as_frontmatter(self) -> dict:
        data = {
            "별표구분": self.kind,
            "별표번호": self.no,
            "제목": self.title,
            "파일형식": self.file_type,
            "파일링크": self.source_url,
        }
        if self.pdf_url:
            data["PDF링크"] = self.pdf_url
        return data


def is_law_go_kr_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host == "law.go.kr" or host.endswith(".law.go.kr")


def infer_file_type(url: str, content_type: str = "") -> str:
    lower_url = url.lower()
    lower_type = content_type.lower()
    if lower_url.endswith(".hwp") or "hwp" in lower_type:
        return "hwp"
    if lower_url.endswith(".pdf") or "pdf" in lower_type:
        return "pdf"
    if any(lower_url.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif")) or lower_type.startswith("image/"):
        return "image"
    if "html" in lower_type:
        return "html"
    return "text"


def fetch_attachment_metadata(
    *,
    kind: str,
    no: str,
    title: str,
    source_url: str,
    pdf_url: str = "",
    timeout: int = 30,
) -> AttachmentMetadata:
    """Download an attachment URL and return deterministic frontmatter metadata."""
    if not is_law_go_kr_url(source_url):
        raise ValueError(f"attachment source_url is not a law.go.kr URL: {source_url}")

    resp = requests.get(source_url, timeout=timeout)
    resp.raise_for_status()
    content = resp.content

    return AttachmentMetadata(
        kind=kind,
        no=no,
        title=title,
        source_url=source_url,
        pdf_url=pdf_url,
        file_type=infer_file_type(source_url, resp.headers.get("Content-Type", "")),
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        fetched_at=date.today().isoformat(),
    )
