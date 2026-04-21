"""
session_coordinator.py
----------------------
Coordinates non-camera modalities so they share the same MACS session_dir
and recording_start_ns as SessionRecorder.

This helper does not create its own session IDs. CaptureController remains
the single owner of the recording lifecycle.
"""

from pathlib import Path

from .imu_driver import ImuDriver
from .mmwave_driver import MmWaveDriver


class SessionCoordinator:
    """Owns external modality drivers and arms them per session."""

    def __init__(self, config=None, logger=None):
        cfg = (config or {}).get("multimodal", {})
        self._log_fn = logger

        self._mmwave = MmWaveDriver(cfg.get("mmwave", {}), logger=self._log)
        self._imu = ImuDriver(cfg.get("imu", {}), logger=self._log)

    def prepare(self):
        """Warm up all enabled external modalities."""
        if self._mmwave.enabled:
            self._mmwave.prepare()
        if self._imu.enabled:
            self._imu.prepare()
        return self.get_summary()

    def start_session(self, session_dir, session_start_ns):
        session_dir = Path(session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)

        if self._mmwave.enabled:
            self._mmwave.start_session(session_dir, session_start_ns)
        if self._imu.enabled:
            self._imu.start_session(session_dir, session_start_ns)
        return self.get_summary()

    def stop_session(self):
        if self._mmwave.enabled:
            self._mmwave.stop_session()
        if self._imu.enabled:
            self._imu.stop_session()
        return self.get_summary()

    def discard_session(self):
        if self._mmwave.enabled:
            self._mmwave.discard_session()
        if self._imu.enabled:
            self._imu.discard_session()
        return self.get_summary()

    def shutdown(self):
        self._mmwave.shutdown()
        self._imu.shutdown()

    def get_summary(self):
        return {
            "modalities": {
                "mmwave": self._mmwave.get_summary(),
                "imu": self._imu.get_summary(),
            }
        }

    def _log(self, msg):
        if self._log_fn is not None:
            self._log_fn(msg)