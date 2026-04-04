"""Thread-safe progress counter."""

import threading


class Counter:
    """Thread-safe counters for tracking cached/fetched/errors progress."""

    def __init__(self):
        self._lock = threading.Lock()
        self.cached = 0
        self.fetched = 0
        self.errors = 0

    def inc(self, field: str) -> None:
        with self._lock:
            setattr(self, field, getattr(self, field) + 1)

    def snapshot(self) -> tuple[int, int, int]:
        with self._lock:
            return self.cached, self.fetched, self.errors
