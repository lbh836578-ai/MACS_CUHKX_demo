"""
sync_manager.py
---------------
Tracks per-modality frame timestamps and computes the inter-camera
synchronisation drift between the NYX650 group (RGB / Depth / IR) and
the TB4117 (Thermal).

Drift is defined as the *absolute time difference* between the latest
NYX650 frame and its temporally nearest TB4117 frame, averaged over a
configurable sliding window.
"""

import threading
from collections import deque


class SyncManager:
    """Thread-safe timestamp tracker and drift calculator."""

    # Modalities produced by each physical camera
    NYX_MODALITIES     = ("RGB", "Depth", "IR")
    THERMAL_MODALITIES = ("Thermal",)

    def __init__(self, window_size=60, drift_threshold_ms=66.0):
        self._window = window_size
        self._threshold_ms = drift_threshold_ms

        self._history = {
            "RGB":     deque(maxlen=window_size),
            "Depth":   deque(maxlen=window_size),
            "IR":      deque(maxlen=window_size),
            "Thermal": deque(maxlen=window_size),
        }

        self._drift_samples = deque(maxlen=window_size)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ feed

    def record_timestamp(self, modality, timestamp_ns):
        """Record a frame arrival and update the drift estimate."""
        with self._lock:
            buf = self._history.get(modality)
            if buf is not None:
                buf.append(timestamp_ns)
            self._update_drift()

    # ------------------------------------------------------------------ query

    def get_drift_ms(self):
        """Return average inter-camera drift in milliseconds, or None."""
        with self._lock:
            if not self._drift_samples:
                return None
            avg_ns = sum(self._drift_samples) / len(self._drift_samples)
        return avg_ns / 1.0e6

    def get_health(self):
        """Return ``"OK"``, ``"WARN"``, or ``"ERROR"`` based on drift."""
        drift = self.get_drift_ms()
        if drift is None:
            return "WARN"
        if drift < self._threshold_ms * 0.5:
            return "OK"
        if drift < self._threshold_ms:
            return "WARN"
        return "ERROR"

    def get_intra_nyx_spread_ms(self):
        """Return the spread among RGB/Depth/IR timestamps (ms) or None.

        A large spread indicates the three NYX modalities are out of step
        -- this should normally be very small (< 1 ms) because they share
        a single capture trigger.
        """
        with self._lock:
            times = [
                self._history[m][-1]
                for m in self.NYX_MODALITIES
                if len(self._history[m]) > 0
            ]
        if len(times) < 2:
            return None
        return (max(times) - min(times)) / 1.0e6

    def reset(self):
        with self._lock:
            for buf in self._history.values():
                buf.clear()
            self._drift_samples.clear()

    # --------------------------------------------------------- internal calc

    def _update_drift(self):
        """Compute and store latest drift sample (caller holds lock)."""
        nyx_stamps = [
            self._history[m][-1]
            for m in self.NYX_MODALITIES
            if len(self._history[m]) > 0
        ]
        thermal_buf = self._history["Thermal"]
        if not nyx_stamps or len(thermal_buf) == 0:
            return

        latest_nyx = max(nyx_stamps)

        # Find the temporally nearest thermal timestamp
        nearest_thermal = min(thermal_buf, key=lambda t: abs(t - latest_nyx))
        drift_ns = abs(latest_nyx - nearest_thermal)
        self._drift_samples.append(drift_ns)