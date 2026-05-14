"""Tests for deterministic precedent update ordering."""

import precedents.update as update_mod


def test_collect_recent_ids_sorts_by_date_and_serial(monkeypatch):
    responses = {
        1: {
            "totalCnt": 3,
            "precedents": [
                {"판례일련번호": "30", "선고일자": "20240102"},
                {"판례일련번호": "9", "선고일자": "20240101"},
                {"판례일련번호": "20", "선고일자": "20240101"},
            ],
        },
    }

    def search_stub(*, query, page, display, sort, date_range):
        return responses[page]

    monkeypatch.setattr(update_mod, "search_precedents", search_stub)

    recent = update_mod._collect_recent_ids(days=1)

    assert [item["판례일련번호"] for item in recent] == ["20", "9", "30"]
