import time
from collections import defaultdict, deque
from collections.abc import Callable


class FixedWindowRateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: int) -> int | None:
        now = self._clock()
        events = self._events[key]
        cutoff = now - window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= limit:
            return max(1, int(window_seconds - (now - events[0]) + 0.999))
        events.append(now)
        return None
