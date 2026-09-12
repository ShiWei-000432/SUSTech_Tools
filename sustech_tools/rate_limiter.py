"""单进程、线程安全的请求频率控制。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RateLimiter:
    """所有选课请求共享一个实例，确保线程之间也不会缩短请求间隔。"""

    def __init__(
        self,
        min_interval: float = 1.2,
        *,
        max_backoff: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_interval <= 0:
            raise ValueError("min_interval 必须大于 0")
        self.min_interval = min_interval
        self.max_backoff = max_backoff
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_request_at: float | None = None
        self.consecutive_errors = 0

    @property
    def current_interval(self) -> float:
        return min(
            self.max_backoff,
            self.min_interval * (2 ** self.consecutive_errors),
        )

    @property
    def last_request_at(self) -> float | None:
        return self._last_request_at

    def acquire(self) -> float:
        """等待必要时间并登记本次请求开始，返回实际等待秒数。"""

        with self._lock:
            now = self._clock()
            wait_seconds = 0.0
            if self._last_request_at is not None:
                wait_seconds = max(
                    0.0, self.current_interval - (now - self._last_request_at)
                )
            if wait_seconds:
                self._sleep(wait_seconds)
            self._last_request_at = self._clock()
            return wait_seconds

    def record_success(self) -> None:
        with self._lock:
            self.consecutive_errors = 0

    def record_error(self) -> None:
        with self._lock:
            self.consecutive_errors += 1
