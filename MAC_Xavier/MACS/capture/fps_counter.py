"""
fps_counter.py
--------------
Real-time FPS estimator using a sliding window of frame arrival times.
"""

import time
from collections import deque


class FPSCounter:
    """Estimates frames-per-second over a configurable sliding window."""

    def __init__(self, window_size=60):
        self._times = deque(maxlen=window_size)
        self._fps = 0.0

    def tick(self):
        """Record a new frame arrival and return the current FPS estimate."""
        now = time.monotonic()
        self._times.append(now)
        n = len(self._times)
        if n < 2:
            self._fps = 0.0
        else:
            elapsed = self._times[-1] - self._times[0]
            self._fps = (n - 1) / elapsed if elapsed > 0.0 else 0.0
        return self._fps

    @property
    def fps(self):
        """Latest FPS estimate without recording a new tick."""
        return self._fps

    def reset(self):
        self._times.clear()
        self._fps = 0.0
