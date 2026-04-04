"""Tests for core/counter.py."""

from core.counter import Counter


def test_counter_initial_values():
    c = Counter()
    assert c.cached == 0
    assert c.fetched == 0
    assert c.errors == 0


def test_counter_inc():
    c = Counter()
    c.inc("cached")
    c.inc("cached")
    c.inc("fetched")
    c.inc("errors")
    assert c.cached == 2
    assert c.fetched == 1
    assert c.errors == 1


def test_counter_snapshot():
    c = Counter()
    c.inc("cached")
    c.inc("fetched")
    c.inc("fetched")
    c.inc("errors")
    snap = c.snapshot()
    assert snap == (1, 2, 1)


def test_counter_snapshot_is_consistent():
    """Snapshot returns a tuple, not a reference that changes."""
    c = Counter()
    snap1 = c.snapshot()
    c.inc("cached")
    snap2 = c.snapshot()
    assert snap1 == (0, 0, 0)
    assert snap2 == (1, 0, 0)
