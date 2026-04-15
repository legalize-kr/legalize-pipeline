"""Tests for laws/_ci/delta_gate.py::evaluate_delta.

Cases
-----
S. baseline == current -> exit 0
T. new (mst, empty_body) tuple -> exit 1
U. baseline mst with reason change api_error -> empty_body (failed_at > 24h ago) -> exit 1
V. brand-new (mst, api_error) failed_at 1h ago -> exit 0 with warning message
W. brand-new (mst, api_error) failed_at 48h ago -> exit 1 (grace expired)
X. Korean chars in law_name round-trip via encoding='utf-8' without mojibake
"""

import json
import time
from pathlib import Path

import pytest

from laws._ci.delta_gate import TRANSIENT_GRACE_SEC, evaluate_delta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _failed_entry(
    reason: str = "empty_body",
    failed_at: float | None = None,
    law_name: str = "테스트법",
) -> dict:
    return {
        "reason": reason,
        "law_name": law_name,
        "failed_at": failed_at if failed_at is not None else time.time(),
    }


def _state(msts: dict | None = None, misses: dict | None = None) -> dict:
    return {
        "failed_msts": msts or {},
        "search_misses": misses or {},
    }


NOW = 1_700_000_000.0  # arbitrary fixed timestamp


# ---------------------------------------------------------------------------
# S. baseline == current -> exit 0
# ---------------------------------------------------------------------------

def test_s_baseline_equals_current_exits_0():
    entry = _failed_entry(reason="empty_body", failed_at=NOW - 3600)
    cur = _state(msts={"100": entry})
    base = _state(msts={"100": entry})

    code, messages = evaluate_delta(cur, base, NOW)
    assert code == 0
    assert not any("::error::" in m for m in messages)


# ---------------------------------------------------------------------------
# T. new (mst, empty_body) tuple -> exit 1
# ---------------------------------------------------------------------------

def test_t_new_empty_body_exits_1():
    cur = _state(msts={"200": _failed_entry(reason="empty_body", failed_at=NOW - 100)})
    base = _state()

    code, messages = evaluate_delta(cur, base, NOW)
    assert code == 1
    error_msgs = [m for m in messages if "::error::" in m]
    assert error_msgs
    assert "200" in " ".join(error_msgs)


# ---------------------------------------------------------------------------
# U. baseline mst reason change api_error -> empty_body (old failed_at) -> exit 1
# ---------------------------------------------------------------------------

def test_u_reason_change_old_api_error_to_empty_body_exits_1():
    """Reason change on an existing MST is a semantic delta -> exit 1."""
    mst = "300"
    old_failed_at = NOW - (TRANSIENT_GRACE_SEC * 2)  # well past grace
    cur = _state(msts={mst: _failed_entry(reason="empty_body", failed_at=old_failed_at)})
    base = _state(msts={mst: _failed_entry(reason="api_error", failed_at=old_failed_at)})

    code, messages = evaluate_delta(cur, base, NOW)
    assert code == 1
    error_msgs = [m for m in messages if "::error::" in m]
    assert any(mst in m for m in error_msgs)


# ---------------------------------------------------------------------------
# V. brand-new api_error failed_at 1h ago -> exit 0, warning present
# ---------------------------------------------------------------------------

def test_v_new_api_error_within_grace_exits_0_with_warning():
    mst = "400"
    cur = _state(msts={mst: _failed_entry(reason="api_error", failed_at=NOW - 3600)})
    base = _state()

    code, messages = evaluate_delta(cur, base, NOW)
    assert code == 0
    warning_msgs = [m for m in messages if "::warning::" in m]
    assert warning_msgs, "Expected a ::warning:: message for transient api_error within grace"


# ---------------------------------------------------------------------------
# W. brand-new api_error failed_at 48h ago -> exit 1 (grace expired)
# ---------------------------------------------------------------------------

def test_w_new_api_error_grace_expired_exits_1():
    mst = "500"
    cur = _state(msts={mst: _failed_entry(reason="api_error", failed_at=NOW - (TRANSIENT_GRACE_SEC + 7200))})
    base = _state()

    code, messages = evaluate_delta(cur, base, NOW)
    assert code == 1
    error_msgs = [m for m in messages if "::error::" in m]
    assert any(mst in m for m in error_msgs)


# ---------------------------------------------------------------------------
# X. Korean chars in law_name round-trip via json + encoding='utf-8'
# ---------------------------------------------------------------------------

def test_x_korean_chars_roundtrip_utf8(tmp_path: Path):
    """Korean law names must survive JSON serialise -> write -> read without mojibake."""
    law_name = "대한민국헌법"
    state = {
        "failed_msts": {
            "600": _failed_entry(reason="empty_body", failed_at=NOW - 100, law_name=law_name)
        },
        "search_misses": {},
    }

    p = tmp_path / "failed.json"
    p.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    loaded = json.loads(p.read_text(encoding="utf-8"))
    assert loaded["failed_msts"]["600"]["law_name"] == law_name, (
        "Korean law_name corrupted after UTF-8 round-trip"
    )

    # Also confirm evaluate_delta handles the loaded state without error
    code, _msgs = evaluate_delta(loaded, _state(), NOW)
    assert code == 1  # new semantic failure
