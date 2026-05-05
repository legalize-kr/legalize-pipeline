"""Attachment metadata helpers for ordinance bylaws."""

from urllib.parse import urlparse


def is_law_go_kr_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host == "law.go.kr" or host.endswith(".law.go.kr")
