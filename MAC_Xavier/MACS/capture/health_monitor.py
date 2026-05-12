"""
health_monitor.py
-----------------
Background health monitoring thread that continuously checks system
health during recording:

  * **FPS drop**:       any modality FPS falls below target × warn_ratio
  * **Frame loss**:     any modality has no new frame for N consecutive checks
  * **Camera disconnect**: driver reports disconnected
  * **Sync drift**:     inter-camera drift exceeds threshold
  * **Disk space**:     remaining storage falls below minimum

The monitor emits Qt signals so the UI (StatusPanel) and
CaptureController can react (show warnings, pause, or stop recording).
"""

import os
import shutil
import time
import threading
from enum import Enum, auto

from PyQt5.QtCore import QObject, pyqtSignal


# ---------------------------------------------------------------------------
# Alert levels
# ---------------------------------------------------------------------------

class AlertLevel(Enum):
    OK    = auto()
    WARN  = auto()
    ERROR = auto()


class HealthAlert:
    """Lightweight container for a single health event."""

    __slots__ = ("check_name", "level", "message", "timestamp")

    def __init__(self, check_name, level, message=""):
        self.check_name = check_name
        self.level = level
        self.message = message
        self.timestamp = time.time()

    def __repr__(self):
        return (f"HealthAlert({self.check_name}, {self.level.name}, "
                f"{self.message!r})")


# ---------------------------------------------------------------------------
# Health monitor
# ---------------------------------------------------------------------------

class HealthMonitor(QObject):
    """Periodic health checker that runs on a QTimer tick from the main
    thread (driven by CaptureController's status timer).

    It does **not** spin up its own thread — it piggybacks on the
    existing periodic refresh already present in ``CaptureController``.
    """

    # Emitted whenever a new alert is generated.
    # Listeners receive (HealthAlert,)
    alert_fired = pyqtSignal(object)

    # Emitted when recording should be auto-paused (red-level event).
    auto_pause_requested = pyqtSignal(str)    # reason

    # Emitted when recording should be auto-stopped (critical event).
    auto_stop_requested = pyqtSignal(str)     # reason

    ALL_MODALITIES = ("RGB", "Depth", "IR", "Thermal")

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        cfg = (config or {}).get("health", {})
        mm_cfg = cfg.get("mmwave", {})

        # ---- configurable thresholds --------------------------------------
        self._fps_warn_ratio       = cfg.get("fps_warn_ratio", 0.7)
        self._frame_loss_threshold = cfg.get("frame_loss_threshold", 10)
        self._drift_threshold_ms   = cfg.get("sync_drift_threshold_ms", 66.0)
        self._disk_min_gb          = cfg.get("disk_min_gb", 1.0)
        self._mmwave_health_enabled = bool(mm_cfg.get("enabled", True))
        self._mmwave_stall_timeout_s = float(
            mm_cfg.get("stall_timeout_s", 3.0)
        )
        self._mmwave_queue_warn_ratio = float(
            mm_cfg.get("writer_queue_warn_ratio", 0.8)
        )

        # Expected target FPS per modality (filled from camera config)
        cam_cfg = (config or {}).get("camera", {})
        nyx = cam_cfg.get("nyx650", {})
        tb  = cam_cfg.get("tb4117", {})
        self._target_fps = {
            "RGB":     nyx.get("rgb",   {}).get("fps", 15),
            "Depth":   nyx.get("depth", {}).get("fps", 15),
            "IR":      nyx.get("ir",    {}).get("fps", 15),
            "Thermal": tb.get("thermal", {}).get("fps", 30),
        }

        # ---- runtime state ------------------------------------------------
        self._active = False
        self._data_path = (config or {}).get("recording", {}).get(
            "output_dir", "data"
        )

        # Per-modality frame sequence counters — set by feed_frame_count()
        self._last_seq = {m: 0 for m in self.ALL_MODALITIES}
        self._stale_ticks = {m: 0 for m in self.ALL_MODALITIES}

        # Camera connection flags
        self._cam_connected = {"nyx650": False, "tb4117": False}

        # Latest aggregate status (for external query)
        self._overall = AlertLevel.OK
        self._alerts_history = []
        self._mmwave_last_frame_count = 0
        self._mmwave_last_frame_ts = time.time()
        self._mmwave_last_dropped = 0
        self._mmwave_unavailable_active = False
        self._mmwave_drop_active = False
        self._mmwave_stall_active = False
        self._mmwave_queue_active = False

        self._lock = threading.Lock()

    # ================================================================
    # Public control
    # ================================================================

    def start(self):
        """Call when recording starts.  Resets internal counters."""
        with self._lock:
            self._active = True
            for m in self.ALL_MODALITIES:
                self._last_seq[m] = 0
                self._stale_ticks[m] = 0
            self._overall = AlertLevel.OK
            self._alerts_history.clear()
            self._reset_mmwave_state()

    def stop(self):
        """Call when recording stops."""
        with self._lock:
            self._active = False
            self._reset_mmwave_state()

    @property
    def is_active(self):
        return self._active

    # ================================================================
    # External data feeds (called by CaptureController)
    # ================================================================

    def feed_frame_count(self, modality, seq):
        """Update the latest frame sequence counter for *modality*."""
        with self._lock:
            self._last_seq[modality] = seq

    def set_camera_connected(self, camera_name, connected):
        """camera_name: 'nyx650' or 'tb4117'."""
        with self._lock:
            self._cam_connected[camera_name] = connected

    def set_data_path(self, data_path):
        if not data_path:
            return
        with self._lock:
            self._data_path = data_path

    # ================================================================
    # Periodic tick — called by CaptureController._refresh_status()
    # ================================================================

    def tick(self, fps_values, drift_ms, external_summary=None):
        """Run all health checks once.

        Parameters
        ----------
        fps_values : dict
            ``{"RGB": float|None, "Depth": …, "IR": …, "Thermal": …}``
        drift_ms : float or None
            Current inter-camera sync drift in milliseconds.

        Returns
        -------
        AlertLevel
            The worst (highest-severity) alert level from this tick.
        """
        if not self._active:
            return AlertLevel.OK

        worst = AlertLevel.OK

        worst = self._max(worst, self._check_fps(fps_values))
        worst = self._max(worst, self._check_frame_loss(fps_values))
        worst = self._max(worst, self._check_camera_disconnect())
        worst = self._max(worst, self._check_sync_drift(drift_ms))
        worst = self._max(worst, self._check_disk_space())
        worst = self._max(worst, self._check_mmwave(external_summary))

        with self._lock:
            self._overall = worst

        return worst

    @property
    def overall_level(self):
        with self._lock:
            return self._overall

    @property
    def recent_alerts(self):
        """Return a copy of the alerts accumulated during this session."""
        with self._lock:
            return list(self._alerts_history)

    # ================================================================
    # Individual checks
    # ================================================================

    def _check_fps(self, fps_values):
        """Check each modality FPS against target × warn_ratio."""
        worst = AlertLevel.OK
        for mod in self.ALL_MODALITIES:
            fps = fps_values.get(mod)
            if fps is None:
                continue  # camera not connected — handled elsewhere
            target = self._target_fps.get(mod, 15)
            threshold = target * self._fps_warn_ratio
            if fps < threshold:
                alert = HealthAlert(
                    "fps_drop", AlertLevel.WARN,
                    f"{mod} FPS {fps:.1f} < {threshold:.1f} "
                    f"(target {target} × {self._fps_warn_ratio})",
                )
                self._fire(alert)
                worst = self._max(worst, AlertLevel.WARN)
        return worst

    def _check_frame_loss(self, fps_values):
        """Detect modalities that haven't produced new frames."""
        worst = AlertLevel.OK
        for mod in self.ALL_MODALITIES:
            fps = fps_values.get(mod)
            if fps is None:
                # Camera not connected — will be caught by disconnect check
                continue
            # If FPS is essentially 0, count a stale tick
            if fps < 0.5:
                self._stale_ticks[mod] += 1
            else:
                self._stale_ticks[mod] = 0

            if self._stale_ticks[mod] >= self._frame_loss_threshold:
                alert = HealthAlert(
                    "frame_loss", AlertLevel.ERROR,
                    f"{mod}: no frames for {self._stale_ticks[mod]} "
                    f"consecutive checks",
                )
                self._fire(alert)
                self.auto_pause_requested.emit(
                    f"{mod} modality lost — no frames received"
                )
                worst = self._max(worst, AlertLevel.ERROR)
        return worst

    def _check_camera_disconnect(self):
        """Check whether any camera driver has disconnected."""
        worst = AlertLevel.OK
        with self._lock:
            nyx = self._cam_connected.get("nyx650", False)
            tb  = self._cam_connected.get("tb4117", False)

        if not nyx and not tb:
            alert = HealthAlert(
                "camera_disconnect", AlertLevel.ERROR,
                "Both cameras disconnected",
            )
            self._fire(alert)
            self.auto_stop_requested.emit("All cameras disconnected")
            return AlertLevel.ERROR

        if not nyx:
            alert = HealthAlert(
                "camera_disconnect", AlertLevel.ERROR,
                "NYX650 disconnected",
            )
            self._fire(alert)
            self.auto_stop_requested.emit("NYX650 disconnected")
            worst = self._max(worst, AlertLevel.ERROR)

        if not tb:
            # TB4117 might not yet be available (Phase 2) — treat as WARN
            alert = HealthAlert(
                "camera_disconnect", AlertLevel.WARN,
                "TB4117 disconnected",
            )
            self._fire(alert)
            worst = self._max(worst, AlertLevel.WARN)

        return worst

    def _check_sync_drift(self, drift_ms):
        """Check inter-camera synchronisation drift."""
        if drift_ms is None:
            return AlertLevel.OK  # not enough data yet
        if drift_ms > self._drift_threshold_ms:
            alert = HealthAlert(
                "sync_drift", AlertLevel.WARN,
                f"Drift {drift_ms:.1f} ms > threshold "
                f"{self._drift_threshold_ms:.0f} ms",
            )
            self._fire(alert)
            return AlertLevel.WARN
        return AlertLevel.OK

    def _check_disk_space(self):
        """Check remaining disk space on the data partition."""
        path = self._data_path
        if not os.path.exists(path):
            path = os.path.expanduser("~")
        try:
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1024 ** 3)
        except OSError:
            return AlertLevel.OK  # can't check — don't block

        if free_gb < self._disk_min_gb:
            alert = HealthAlert(
                "disk_space", AlertLevel.ERROR,
                f"Only {free_gb:.2f} GB remaining "
                f"(minimum {self._disk_min_gb:.1f} GB)",
            )
            self._fire(alert)
            self.auto_stop_requested.emit(
                f"Disk space critically low ({free_gb:.2f} GB)"
            )
            return AlertLevel.ERROR

        if free_gb < self._disk_min_gb * 2:
            alert = HealthAlert(
                "disk_space", AlertLevel.WARN,
                f"{free_gb:.1f} GB remaining",
            )
            self._fire(alert)
            return AlertLevel.WARN

        return AlertLevel.OK

    def _check_mmwave(self, external_summary):
        if not self._mmwave_health_enabled:
            return AlertLevel.OK

        info = ((external_summary or {}).get("modalities", {}).get("mmwave") or {})
        if not info.get("enabled"):
            self._reset_mmwave_state()
            return AlertLevel.OK

        worst = AlertLevel.OK
        now = time.time()
        prepared = bool(info.get("prepared"))
        error = info.get("error")
        frames = int(info.get("frames_captured") or 0)
        queue_depth = int(info.get("writer_queue_depth") or 0)
        queue_size = int(info.get("writer_queue_size") or 0)
        dropped = int((info.get("writer_stats") or {}).get("dropped") or 0)

        if frames > self._mmwave_last_frame_count:
            self._mmwave_last_frame_count = frames
            self._mmwave_last_frame_ts = now
            self._mmwave_stall_active = False

        if not prepared or error:
            if not self._mmwave_unavailable_active:
                msg = error or "mmWave collector is not prepared"
                self._fire(HealthAlert("mmwave_unavailable", AlertLevel.WARN, msg))
            self._mmwave_unavailable_active = True
            worst = self._max(worst, AlertLevel.WARN)
        else:
            self._mmwave_unavailable_active = False

        if dropped > 0:
            self._mmwave_last_dropped = dropped
            if not self._mmwave_drop_active:
                self._fire(
                    HealthAlert(
                        "mmwave_drop",
                        AlertLevel.WARN,
                        f"mmWave dropped {dropped} frame(s) in the writer queue",
                    )
                )
            self._mmwave_drop_active = True
            worst = self._max(worst, AlertLevel.WARN)
        else:
            self._mmwave_last_dropped = 0
            self._mmwave_drop_active = False

        warn_depth = (
            queue_size > 0 and
            queue_depth >= max(1, int(queue_size * self._mmwave_queue_warn_ratio))
        )
        if warn_depth:
            if not self._mmwave_queue_active:
                self._fire(
                    HealthAlert(
                        "mmwave_queue",
                        AlertLevel.WARN,
                        f"mmWave writer queue is high: {queue_depth}/{queue_size}",
                    )
                )
            self._mmwave_queue_active = True
            worst = self._max(worst, AlertLevel.WARN)
        else:
            self._mmwave_queue_active = False

        idle_for = now - self._mmwave_last_frame_ts
        if prepared and not error and idle_for >= self._mmwave_stall_timeout_s:
            if not self._mmwave_stall_active:
                self._fire(
                    HealthAlert(
                        "mmwave_stall",
                        AlertLevel.WARN,
                        f"mmWave has no new frames for {idle_for:.1f} s",
                    )
                )
            self._mmwave_stall_active = True
            worst = self._max(worst, AlertLevel.WARN)
        elif prepared and not error:
            self._mmwave_stall_active = False

        return worst

    # ================================================================
    # Helpers
    # ================================================================

    def _fire(self, alert):
        """Record and emit an alert."""
        with self._lock:
            self._alerts_history.append(alert)
            # Keep history bounded
            if len(self._alerts_history) > 500:
                self._alerts_history = self._alerts_history[-250:]
        self.alert_fired.emit(alert)

    def _reset_mmwave_state(self):
        self._mmwave_last_frame_count = 0
        self._mmwave_last_frame_ts = time.time()
        self._mmwave_last_dropped = 0
        self._mmwave_unavailable_active = False
        self._mmwave_drop_active = False
        self._mmwave_stall_active = False
        self._mmwave_queue_active = False

    @staticmethod
    def _max(a, b):
        """Return the more severe of two AlertLevels."""
        order = {AlertLevel.OK: 0, AlertLevel.WARN: 1, AlertLevel.ERROR: 2}
        return a if order.get(a, 0) >= order.get(b, 0) else b
