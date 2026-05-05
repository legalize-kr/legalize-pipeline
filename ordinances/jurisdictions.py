"""Jurisdiction normalization for local ordinances."""

import re
import unicodedata

GWANGYEOK = frozenset({
    "서울특별시",
    "부산광역시",
    "대구광역시",
    "인천광역시",
    "광주광역시",
    "대전광역시",
    "울산광역시",
    "세종특별자치시",
    "경기도",
    "강원특별자치도",
    "충청북도",
    "충청남도",
    "전북특별자치도",
    "전라남도",
    "경상북도",
    "경상남도",
    "제주특별자치도",
    "충청광역연합",
})

HANJA_ALIAS = {
    "서울特別市": "서울특별시",
    "강원도": "강원특별자치도",
    "전라북도": "전북특별자치도",
    "제주도교육청": "제주특별자치도교육청",
    "제주도": "제주특별자치도",
}

MAIN_OFFICE_SENTINEL = "_본청"
EDUCATION_OFFICE_SENTINEL = "_교육청"


class UnknownJurisdiction(ValueError):
    """Raised when a jurisdiction cannot be mapped to the 17-province set."""


def _normalize(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw or "")
    for old, new in HANJA_ALIAS.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def split_jurisdiction(raw: str) -> tuple[str, str]:
    """Split raw law.go.kr jurisdiction text into (광역, 기초_or_sentinel)."""
    text = _normalize(raw)
    for gwangyeok in sorted(GWANGYEOK, key=len, reverse=True):
        if text.startswith(gwangyeok):
            rest = text[len(gwangyeok):].strip()
            if not rest:
                return gwangyeok, MAIN_OFFICE_SENTINEL
            if rest.endswith("교육청"):
                return gwangyeok, EDUCATION_OFFICE_SENTINEL
            return gwangyeok, rest
    raise UnknownJurisdiction(raw)
