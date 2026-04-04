"""Tests for core/throttle.py."""

import time

from core.throttle import Throttle


def test_throttle_first_call_no_delay():
    """First call should return near-instantly (no prior timestamp)."""
    t = Throttle(delay_seconds=0.5)
    start = time.monotonic()
    t.wait()
    elapsed = time.monotonic() - start
    assert elapsed < 0.2, f"First call took too long: {elapsed:.3f}s"


def test_throttle_enforces_delay():
    """Second call within delay period should wait."""
    delay = 0.1
    t = Throttle(delay_seconds=delay)
    t.wait()  # first call — sets _last
    start = time.monotonic()
    t.wait()  # second call — should sleep ~delay
    elapsed = time.monotonic() - start
    assert elapsed >= delay * 0.8, f"Throttle did not enforce delay: {elapsed:.3f}s"


def test_throttle_independent_instances():
    """Two separate Throttle instances have independent rate limits."""
    t1 = Throttle(delay_seconds=0.1)
    t2 = Throttle(delay_seconds=0.1)
    t1.wait()

    # t2 should NOT be affected by t1's last-call timestamp
    start = time.monotonic()
    t2.wait()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05, f"t2 was affected by t1: {elapsed:.3f}s"
