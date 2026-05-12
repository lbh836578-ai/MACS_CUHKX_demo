"""
main_window.py
--------------
Top-level application window that composes all UI panels and
manages the IDLE -> RECORDING -> PROCESSING state machine.
"""

import time
from enum import Enum, auto

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QMessageBox,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QPalette, QColor

from .preview_panel import PreviewPanel
from .control_panel import ControlPanel
from .status_panel import StatusPanel


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------

class AppState(Enum):
    IDLE       = auto()
    RECORDING  = auto()
    PROCESSING = auto()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Orchestrates the entire capture UI."""

    # Signals that external modules (camera drivers, post-processor) can
    # connect to in order to react to user actions.
    recording_started   = pyqtSignal(object)            # session request dict
    breakpoint_marked   = pyqtSignal(int, str, str)     # idx, before, after
    recording_stopped   = pyqtSignal()
    recording_cancelled = pyqtSignal()

    # Thread-safe frame delivery signal.
    # Camera threads should emit this; it is auto-queued across threads.
    frame_received = pyqtSignal(str, object, float)     # modality, ndarray, fps

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self._cfg = config or {}

        # ---- state ---------------------------------------------------------
        self._state              = AppState.IDLE
        self._labels             = []
        self._label_idx          = 0
        self._breakpoints        = []
        self._rec_start_ns       = None
        self._session_request    = {}
        self._pending_preview    = {}
        self._mmwave_alert_boxes = []
        self._enable_breakpoint  = (
            self._cfg.get("recording", {}).get("enable_breakpoint", True)
        )

        # ---- build UI ------------------------------------------------------
        self._init_window()
        self._build_layout()
        self._connect_signals()
        self._start_timers()

    # ================================================================
    # Construction helpers
    # ================================================================

    def _init_window(self):
        self.setWindowTitle("MACS - MultiModal Action Capture System")
        self.setMinimumSize(860, 620)
        self.resize(1100, 780)
        self._apply_dark_palette()

    def _apply_dark_palette(self):
        pal = QPalette()
        pal.setColor(QPalette.Window,          QColor(43, 43, 43))
        pal.setColor(QPalette.WindowText,      QColor(220, 220, 220))
        pal.setColor(QPalette.Base,            QColor(35, 35, 35))
        pal.setColor(QPalette.AlternateBase,   QColor(53, 53, 53))
        pal.setColor(QPalette.ToolTipBase,     QColor(25, 25, 25))
        pal.setColor(QPalette.ToolTipText,     QColor(220, 220, 220))
        pal.setColor(QPalette.Text,            QColor(220, 220, 220))
        pal.setColor(QPalette.Button,          QColor(53, 53, 53))
        pal.setColor(QPalette.ButtonText,      QColor(220, 220, 220))
        pal.setColor(QPalette.BrightText,      QColor(255, 50, 50))
        pal.setColor(QPalette.Link,            QColor(42, 130, 218))
        pal.setColor(QPalette.Highlight,       QColor(42, 130, 218))
        pal.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
        self.setPalette(pal)

    def _build_layout(self):
        central = QWidget()
        self.setCentralWidget(central)
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(4, 4, 4, 0)
        vbox.setSpacing(4)

        self.control_panel = ControlPanel(
            enable_breakpoint=self._enable_breakpoint, parent=self
        )
        vbox.addWidget(self.control_panel)

        ui_cfg = self._cfg.get("ui", {})
        self.preview_panel = PreviewPanel(
            preview_width=ui_cfg.get("preview_width", 320),
            preview_height=ui_cfg.get("preview_height", 240),
            parent=self,
        )
        vbox.addWidget(self.preview_panel, stretch=1)

        data_dir = self._cfg.get("recording", {}).get("output_dir", "data")
        self.status_panel = StatusPanel(data_path=data_dir, parent=self)
        vbox.addWidget(self.status_panel)

    def _connect_signals(self):
        cp = self.control_panel
        cp.start_requested.connect(self._on_start)
        cp.breakpoint_requested.connect(self._on_breakpoint)
        cp.stop_requested.connect(self._on_stop)
        cp.cancel_requested.connect(self._on_cancel)

        # Thread-safe frame delivery
        self.frame_received.connect(self._on_frame_received)

    def _start_timers(self):
        ui_cfg = self._cfg.get("ui", {})
        interval = ui_cfg.get("status_update_interval_ms", 500)
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(interval)

        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._flush_preview_frames)
        self._preview_timer.start(ui_cfg.get("preview_update_interval_ms", 33))

    # ================================================================
    # State helpers
    # ================================================================

    @property
    def state(self):
        return self._state

    def _set_state(self, new):
        self._state = new
        if new != AppState.RECORDING:
            self._pending_preview.clear()
        if new == AppState.IDLE:
            self.control_panel.set_idle_state()
            self.status_panel.reset()
        elif new == AppState.RECORDING:
            multi = len(self._labels) > 1
            self.control_panel.set_recording_state(has_multiple_labels=multi)
        elif new == AppState.PROCESSING:
            self.control_panel.set_processing_state()
            self.status_panel.stop_timer()

    # ================================================================
    # Slots -- control panel
    # ================================================================

    @pyqtSlot(object)
    def _on_start(self, session_request):
        if self._state != AppState.IDLE:
            return
        session_request = dict(session_request or {})
        labels = list(session_request.get("labels") or [])
        if not labels:
            return

        self._session_request = session_request
        self._labels       = labels
        self._label_idx    = 0
        self._breakpoints  = []
        self._rec_start_ns = time.time_ns()

        self._set_state(AppState.RECORDING)
        self.status_panel.start_timer()
        self.control_panel.update_progress(labels[0], 0, len(labels))

        # Disable breakpoint if only one label
        if len(labels) <= 1:
            self.control_panel.set_breakpoint_enabled(False)

        self.recording_started.emit(session_request)

    @pyqtSlot()
    def _on_breakpoint(self):
        if not self._enable_breakpoint:
            return  # feature disabled globally
        if self._state != AppState.RECORDING:
            return
        if self._label_idx >= len(self._labels) - 1:
            return  # already on the last label

        bp = {
            "index":         len(self._breakpoints),
            "label_before":  self._labels[self._label_idx],
            "label_after":   self._labels[self._label_idx + 1],
            "host_timestamp_ns": time.time_ns(),
        }
        self._breakpoints.append(bp)
        self._label_idx += 1

        self.control_panel.update_progress(
            self._labels[self._label_idx],
            self._label_idx,
            len(self._labels),
        )

        # Disable breakpoint when the last label is reached
        if self._label_idx >= len(self._labels) - 1:
            self.control_panel.set_breakpoint_enabled(False)

        self.breakpoint_marked.emit(
            bp["index"], bp["label_before"], bp["label_after"]
        )

    @pyqtSlot()
    def _on_stop(self):
        if self._state != AppState.RECORDING:
            return

        self._set_state(AppState.PROCESSING)
        self.preview_panel.clear_all()
        self.recording_stopped.emit()
        # CaptureController will finalize the recorder and launch
        # PostProcessor; progress comes back through
        # on_post_processing_progress / on_post_processing_done.

    @pyqtSlot()
    def _on_cancel(self):
        if self._state != AppState.RECORDING:
            return

        reply = QMessageBox.question(
            self,
            "Cancel Recording",
            "Discard all data from this recording session?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._set_state(AppState.IDLE)
            self.preview_panel.clear_all()
            self.recording_cancelled.emit()

    def _finish_processing(self, output_dir=None, error=None):
        """Transition back to IDLE after post-processing."""
        self._set_state(AppState.IDLE)
        if error:
            QMessageBox.warning(
                self,
                "Post-Processing Error",
                f"Post-processing encountered an error:\n\n{error}",
            )
        elif output_dir:
            action_id = self._session_request.get("action_id", "")
            QMessageBox.information(
                self,
                "Session Complete",
                (f"Action ID: {action_id}\n" if action_id else "") +
                f"Actions:  {len(self._labels)}\n"
                f"Labels:   {', '.join(self._labels)}\n\n"
                f"Processed data saved to:\n{output_dir}",
            )

    # ================================================================
    # Post-processing callbacks (called by CaptureController)
    # ================================================================

    def on_post_processing_progress(self, percent, text):
        """Update UI during background post-processing."""
        if percent >= 0:
            self.status_panel.update_health(f"PP {percent}%")
        self.setWindowTitle(f"MACS - {text}")

    def on_post_processing_done(self, output_dir=None, error=None):
        """Called when the PostProcessor finishes (or is skipped)."""
        self.setWindowTitle("MACS - MultiModal Action Capture System")
        # output_dir=None and error=None means post-processing was skipped
        if output_dir is None and error is None:
            self._set_state(AppState.IDLE)
            return
        self._finish_processing(output_dir, error)

    # ================================================================
    # Slots -- frame delivery
    # ================================================================

    @pyqtSlot(str, object, float)
    def _on_frame_received(self, modality, frame, fps):
        """Store only the latest frame per modality for low-latency preview."""
        if self._state == AppState.RECORDING:
            self._pending_preview[modality] = (frame, fps)

    def update_frame(self, modality, frame, fps=None):
        """Convenience for same-thread callers (e.g. demo generator)."""
        if self._state == AppState.RECORDING:
            self._pending_preview[modality] = (frame, fps)

    def _flush_preview_frames(self):
        if self._state != AppState.RECORDING or not self._pending_preview:
            return

        pending = self._pending_preview
        self._pending_preview = {}
        for modality, (frame, fps) in pending.items():
            self.preview_panel.update_frame(modality, frame, fps)

    # ================================================================
    # Periodic tick
    # ================================================================

    def _on_tick(self):
        if self._state == AppState.RECORDING:
            self.status_panel.update_disk()
            self.status_panel.refresh_timer()

    # ================================================================
    # Health auto-stop (called by CaptureController)
    # ================================================================

    def handle_health_auto_stop(self, reason):
        """Transition UI to IDLE after a health-triggered auto-stop."""
        if self._state == AppState.RECORDING:
            self._set_state(AppState.IDLE)
            self.preview_panel.clear_all()
            QMessageBox.warning(
                self,
                "Recording Auto-Stopped",
                f"Recording was stopped automatically:\n\n{reason}\n\n"
                "Data captured so far has been saved.",
            )

    def set_output_root(self, data_path):
        self.status_panel.set_data_path(data_path)

    def handle_recording_start_error(self, message):
        self._set_state(AppState.IDLE)
        self.preview_panel.clear_all()
        QMessageBox.warning(
            self,
            "Recording Start Failed",
            f"Unable to start recording:\n\n{message}",
        )

    def show_mmwave_warning(self, message):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("mmWave Warning")
        box.setText(message)
        box.setStandardButtons(QMessageBox.Ok)
        box.setModal(False)
        box.show()
        self._mmwave_alert_boxes.append(box)
        box.finished.connect(lambda _res, ref=box: self._release_alert_box(ref))

    def _release_alert_box(self, box):
        if box in self._mmwave_alert_boxes:
            self._mmwave_alert_boxes.remove(box)

    # ================================================================
    # Keyboard shortcuts
    # ================================================================

    def keyPressEvent(self, event):
        # While typing labels, pass keys through normally
        if (self._state == AppState.IDLE
                and (
                    self.control_panel.label_input.hasFocus()
                    or self.control_panel.action_id_input.hasFocus()
                    or self.control_panel.subject_path_input.hasFocus()
                )):
            super().keyPressEvent(event)
            return

        key = event.key()

        if key == Qt.Key_Space and self._state == AppState.IDLE:
            session_request = self.control_panel.get_session_request()
            if session_request is not None:
                self._on_start(session_request)

        elif key == Qt.Key_B and self._state == AppState.RECORDING:
            self._on_breakpoint()

        elif key == Qt.Key_Escape and self._state == AppState.RECORDING:
            self._on_stop()

        elif key == Qt.Key_C and self._state == AppState.RECORDING:
            self._on_cancel()

        else:
            super().keyPressEvent(event)