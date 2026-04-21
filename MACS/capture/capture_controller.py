"""
capture_controller.py
---------------------
Top-level orchestrator that wires camera drivers, the sync manager,
and the session recorder to the MACS UI (MainWindow).

Signal / slot interface
~~~~~~~~~~~~~~~~~~~~~~~
**Consumed from MainWindow:**

=========================  ===========================================
Signal                     Action
=========================  ===========================================
recording_started(list)    Create SessionRecorder, begin saving
breakpoint_marked(i,b,a)   Forward to recorder
recording_stopped()        Finalise recorder
recording_cancelled()      Discard recorder data
=========================  ===========================================

**Produced towards MainWindow:**

=========================  ===========================================
Signal                     Data
=========================  ===========================================
frame_received(str,obj,f)  Modality, numpy frame, current fps (float)
=========================  ===========================================

Camera threads are started when ``initialize()`` is called and remain
alive until ``shutdown()`` so that multiple recording sessions do not
incur repeated hardware init overhead.
"""

import time

from PyQt5.QtCore import QObject, QTimer, pyqtSlot

from .fps_counter import FPSCounter
from .sync_manager import SyncManager
from .recorder import SessionRecorder
from .nyx650_driver import NYX650Driver
from .session_coordinator import SessionCoordinator
from .tb4117_driver import TB4117Driver
from .health_monitor import HealthMonitor, AlertLevel

# Imported lazily to avoid circular deps at module level
_PostProcessor = None
def _get_post_processor():
    global _PostProcessor
    if _PostProcessor is None:
        from processing.pipeline import PostProcessor
        _PostProcessor = PostProcessor
    return _PostProcessor


class CaptureController(QObject):
    """Connects cameras <==> UI <==> recorder."""

    def __init__(self, config, main_window, parent=None):
        super().__init__(parent)
        self._cfg = config
        self._win = main_window

        # ---- drivers -------------------------------------------------------
        cam_cfg = config.get("camera", {})
        self._nyx_driver = NYX650Driver(
            config=cam_cfg.get("nyx650", {}),
        )
        self._tb_driver = TB4117Driver(
            config=cam_cfg.get("tb4117", {}),
        )

        # ---- sync & fps ----------------------------------------------------
        health_cfg = config.get("health", {})
        drift_thresh = health_cfg.get("sync_drift_threshold_ms", 66.0)
        self._sync = SyncManager(
            window_size=60, drift_threshold_ms=drift_thresh,
        )
        self._fps = {
            "RGB":     FPSCounter(),
            "Depth":   FPSCounter(),
            "IR":      FPSCounter(),
            "Thermal": FPSCounter(),
        }

        # ---- health monitor ------------------------------------------------
        self._health = HealthMonitor(config=config, parent=self)
        self._health.alert_fired.connect(self._on_health_alert)
        self._health.auto_pause_requested.connect(self._on_auto_pause)
        self._health.auto_stop_requested.connect(self._on_auto_stop)

        # ---- recorder (created per session) --------------------------------
        self._recorder = None
        self._recording = False
        self._session_coordinator = SessionCoordinator(config=config, logger=self._log)

        # ---- state flags ---------------------------------------------------
        self._nyx_ok = False
        self._tb_ok  = False

        # ---- connect driver signals ----------------------------------------
        self._nyx_driver.frame_captured.connect(self._on_frame)
        self._nyx_driver.error_occurred.connect(self._on_error)
        self._nyx_driver.connected.connect(self._on_nyx_connected)
        self._nyx_driver.disconnected.connect(self._on_nyx_disconnected)

        self._tb_driver.frame_captured.connect(self._on_frame)
        self._tb_driver.error_occurred.connect(self._on_error)
        self._tb_driver.connected.connect(self._on_tb_connected)
        self._tb_driver.disconnected.connect(self._on_tb_disconnected)

        # ---- connect UI signals (matches MainWindow pyqtSignals) -----------
        self._win.recording_started.connect(self._on_recording_started)
        self._win.breakpoint_marked.connect(self._on_breakpoint_marked)
        self._win.recording_stopped.connect(self._on_recording_stopped)
        self._win.recording_cancelled.connect(self._on_recording_cancelled)

        # ---- periodic status refresh ---------------------------------------
        ui_cfg = config.get("ui", {})
        interval = ui_cfg.get("status_update_interval_ms", 500)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(interval)

    # ================================================================
    # Lifecycle (called from main.py)
    # ================================================================

    def initialize(self):
        """Start camera threads.  Non-blocking -- cameras connect in
        their own threads and emit ``connected`` / ``error_occurred``.
        """
        if NYX650Driver.SDK_AVAILABLE and not self._nyx_driver.isRunning():
            self._nyx_driver.start()
        elif not NYX650Driver.SDK_AVAILABLE:
            self._on_error("NYX650: ScepterSDK not available, skipping")

        if not self._tb_driver.isRunning():
            self._tb_driver.start()

        summary = self._session_coordinator.prepare()
        for name, info in summary.get("modalities", {}).items():
            if not info.get("enabled"):
                continue
            if info.get("prepared"):
                self._log(f"{name} prepared")
            elif info.get("error"):
                self._log(f"{name} unavailable: {info['error']}")

    def shutdown(self):
        """Stop camera threads and any active recorder.  Blocking."""
        self._recording = False
        multimodal_meta = None
        if self._recorder is not None:
            multimodal_meta = self._session_coordinator.stop_session()
        self._nyx_driver.stop(timeout_ms=5000)
        self._tb_driver.stop(timeout_ms=5000)
        if self._recorder is not None:
            try:
                self._recorder.set_external_metadata(multimodal_meta)
                self._recorder.finalize()
            except Exception:
                pass
            self._recorder = None
        self._session_coordinator.shutdown()

    # ================================================================
    # Driver connection status
    # ================================================================

    @pyqtSlot()
    def _on_nyx_connected(self):
        self._nyx_ok = True
        self._health.set_camera_connected("nyx650", True)
        self._log("NYX650 connected")

    @pyqtSlot()
    def _on_nyx_disconnected(self):
        self._nyx_ok = False
        self._health.set_camera_connected("nyx650", False)
        self._log("NYX650 disconnected")

    @pyqtSlot()
    def _on_tb_connected(self):
        self._tb_ok = True
        self._health.set_camera_connected("tb4117", True)
        self._log("TB4117 connected")

    @pyqtSlot()
    def _on_tb_disconnected(self):
        self._tb_ok = False
        self._health.set_camera_connected("tb4117", False)
        self._log("TB4117 disconnected")

    # ================================================================
    # Frame reception (called in main thread via queued connection)
    # ================================================================

    @pyqtSlot(str, object, object)
    def _on_frame(self, modality, frame, timestamp_ns):
        # FPS tracking
        fps_val = self._fps[modality].tick()

        # Sync tracking
        self._sync.record_timestamp(modality, timestamp_ns)

        # Forward to UI preview (always -- UI decides whether to display)
        self._win.frame_received.emit(modality, frame, fps_val)

        # Persist when recording
        if self._recording and self._recorder is not None:
            self._recorder.write_frame(modality, frame, timestamp_ns)

    # ================================================================
    # Recording lifecycle (UI signal slots)
    # ================================================================

    @pyqtSlot(list)
    def _on_recording_started(self, labels):
        base_dir = self._cfg.get("recording", {}).get("output_dir", "data")
        session_start_ns = time.time_ns()
        self._recorder = SessionRecorder(
            base_dir,
            labels,
            self._cfg,
            start_ns=session_start_ns,
        )
        self._session_coordinator.start_session(
            self._recorder.session_dir,
            session_start_ns,
        )
        self._recording = True

        # Reset counters for the new session
        for c in self._fps.values():
            c.reset()
        self._sync.reset()
        self._health.start()

        self._log(f"Recording started: labels={labels}, "
                  f"dir={self._recorder.session_dir}")

        # If cameras are not running (e.g. they disconnected), restart
        if NYX650Driver.SDK_AVAILABLE and not self._nyx_driver.isRunning():
            self._nyx_driver.start()
        if not self._tb_driver.isRunning():
            self._tb_driver.start()

    @pyqtSlot(int, str, str)
    def _on_breakpoint_marked(self, index, label_before, label_after):
        if self._recorder is not None:
            ts = time.time_ns()
            self._recorder.add_breakpoint(
                index, label_before, label_after, ts,
            )
        self._log(f"Breakpoint {index}: {label_before} -> {label_after}")

    @pyqtSlot()
    def _on_recording_stopped(self):
        self._recording = False
        self._health.stop()
        session_path = None
        if self._recorder is not None:
            try:
                self._recorder.set_external_metadata(
                    self._session_coordinator.stop_session()
                )
                session_path = self._recorder.finalize()
                self._log(f"Session saved to {session_path}")
            except Exception as exc:
                self._log(f"Recorder finalize error: {exc}")
            self._recorder = None

        # Launch post-processing pipeline in background
        if session_path is not None:
            self._start_post_processing(session_path)

    @pyqtSlot()
    def _on_recording_cancelled(self):
        self._recording = False
        self._health.stop()
        if self._recorder is not None:
            try:
                self._session_coordinator.discard_session()
                self._recorder.discard()
                self._log("Session discarded")
            except Exception as exc:
                self._log(f"Recorder discard error: {exc}")
            self._recorder = None

    # ================================================================
    # Status panel refresh
    # ================================================================

    def _refresh_status(self):
        sp = self._win.status_panel

        # FPS
        fps_values = {
            "RGB":     self._fps["RGB"].fps     if self._nyx_ok else None,
            "Depth":   self._fps["Depth"].fps   if self._nyx_ok else None,
            "IR":      self._fps["IR"].fps       if self._nyx_ok else None,
            "Thermal": self._fps["Thermal"].fps if self._tb_ok  else None,
        }
        sp.update_fps(
            rgb=fps_values["RGB"],
            depth=fps_values["Depth"],
            ir=fps_values["IR"],
            thermal=fps_values["Thermal"],
        )

        # Sync drift
        drift = self._sync.get_drift_ms()
        sp.update_sync(drift_ms=drift)

        # Health monitor tick
        level = self._health.tick(fps_values, drift)
        sp.update_health(level.name)

    # ================================================================
    # Error handling
    # ================================================================

    @pyqtSlot(str)
    def _on_error(self, msg):
        self._log(f"ERROR: {msg}")
        self._win.status_panel.update_health("ERROR")

    # ================================================================
    # Health monitor callbacks
    # ================================================================

    @pyqtSlot(object)
    def _on_health_alert(self, alert):
        self._log(f"Health: [{alert.level.name}] {alert.check_name}: "
                  f"{alert.message}")

    @pyqtSlot(str)
    def _on_auto_pause(self, reason):
        self._log(f"Auto-pause requested: {reason}")
        # Pause recording but keep cameras alive so user can resume
        if self._recording and self._recorder is not None:
            self._recording = False
            self._win.status_panel.update_health("ERROR")

    @pyqtSlot(str)
    def _on_auto_stop(self, reason):
        self._log(f"Auto-stop requested: {reason}")
        if self._recording:
            self._recording = False
            self._health.stop()
            if self._recorder is not None:
                try:
                    self._recorder.set_external_metadata(
                        self._session_coordinator.stop_session()
                    )
                    path = self._recorder.finalize()
                    self._log(f"Auto-saved session to {path}")
                except Exception as exc:
                    self._log(f"Auto-save error: {exc}")
                self._recorder = None
            self._win.handle_health_auto_stop(reason)

    # ================================================================
    # Post-processing pipeline
    # ================================================================

    def _start_post_processing(self, session_path):
        """Launch the PostProcessor QThread for *session_path*."""
        PP = _get_post_processor()
        self._post_processor = PP(session_path, self._cfg, parent=self)
        self._post_processor.progress.connect(self._on_pp_progress)
        self._post_processor.finished_ok.connect(self._on_pp_ok)
        self._post_processor.finished_error.connect(self._on_pp_error)
        self._post_processor.start()
        self._log("Post-processing started")

    @pyqtSlot(int, str)
    def _on_pp_progress(self, percent, text):
        self._log(f"PostProcess: {text} ({percent}%)")
        self._win.on_post_processing_progress(percent, text)

    @pyqtSlot(str)
    def _on_pp_ok(self, output_dir):
        self._log(f"Post-processing complete: {output_dir}")
        self._post_processor = None
        self._win.on_post_processing_done(output_dir)

    @pyqtSlot(str)
    def _on_pp_error(self, error_msg):
        self._log(f"Post-processing error: {error_msg}")
        self._post_processor = None
        self._win.on_post_processing_done(None, error_msg)

    # ================================================================
    # Logging
    # ================================================================

    @staticmethod
    def _log(msg):
        ts = time.strftime("%H:%M:%S")
        print(f"[CaptureController {ts}] {msg}")
