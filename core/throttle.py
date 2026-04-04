"""Thread-safe request throttle with per-instance state."""

import threading
import time


class Throttle:
    """Rate limiter with independent lock and timestamp per instance.

    Each pipeline should instantiate its own Throttle to maintain
    independent rate-limit buckets.
    """

    def __init__(self, delay_seconds: float):
        self._lock = threading.Lock()
        self._last = 0.0
        self._delay = delay_seconds

    def wait(self) -> None:
        with self._lock:
            elapsed = time.time() - self._last
            if elapsed < self._delay:
                time.sleep(self._delay - elapsed)
            self._last = time.time()
