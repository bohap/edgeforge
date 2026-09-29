"""Token-bucket rate limiter.

Limits requests within one process. Keeping one ingestion worker per provider (as planned)
makes this the effective global limit.
"""

import threading
import time
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        rate_per_second: float,
        burst: int = 1,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        if burst < 1:
            raise ValueError("burst must be at least 1")
        self._rate = rate_per_second
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._sleep = sleep
        self._updated = clock()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a request may be made."""
        with self._lock:
            now = self._clock()
            self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
            self._updated = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                self._sleep(wait)
                self._updated = self._clock()
                self._tokens = 0.0
            else:
                self._tokens -= 1
