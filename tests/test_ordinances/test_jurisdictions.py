import pytest

from ordinances.jurisdictions import UnknownJurisdiction, split_jurisdiction


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("서울특별시 강남구", ("서울특별시", "강남구")),
        ("서울특별시", ("서울특별시", "_본청")),
        ("세종특별자치시", ("세종특별자치시", "_본청")),
        ("서울특별시강남구", ("서울특별시", "강남구")),
        ("서울특별시 교육청", ("서울특별시", "_교육청")),
        ("서울特別市강남구", ("서울특별시", "강남구")),
        ("강원도 춘천시", ("강원특별자치도", "춘천시")),
        ("전라북도 전주시", ("전북특별자치도", "전주시")),
        ("제주도교육청", ("제주특별자치도", "_교육청")),
        ("제주도 제주시", ("제주특별자치도", "제주시")),
        ("충청광역연합", ("충청광역연합", "_본청")),
    ],
)
def test_split_jurisdiction(raw, expected):
    assert split_jurisdiction(raw) == expected


def test_split_jurisdiction_unknown():
    with pytest.raises(UnknownJurisdiction):
        split_jurisdiction("(unknown)")
