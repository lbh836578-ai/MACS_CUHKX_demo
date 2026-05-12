"""
control_panel.py
----------------
Top-bar widget containing:
  * Action-label text input
  * Start / Breakpoint / Stop / Cancel buttons
  * Progress indicator for the current recording session
"""

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox,
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QFont


class ControlPanel(QWidget):
    """Recording control bar."""

    # ---- signals -----------------------------------------------------------
    start_requested      = pyqtSignal(object)  # session request dict
    breakpoint_requested = pyqtSignal()
    stop_requested       = pyqtSignal()
    cancel_requested     = pyqtSignal()

    def __init__(self, enable_breakpoint=True, parent=None):
        super().__init__(parent)
        self._enable_breakpoint = enable_breakpoint
        self._build_ui()
        self._wire_signals()

    # ---- UI construction ---------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(6)

        # Row 1 -- session routing inputs
        self._row0_widget = QWidget()
        row0 = QHBoxLayout(self._row0_widget)
        row0.setContentsMargins(0, 0, 0, 0)

        action_lbl = QLabel("Action ID:")
        action_lbl.setFont(QFont("Sans", 12, QFont.Bold))
        row0.addWidget(action_lbl)

        self.action_id_input = QLineEdit()
        self.action_id_input.setPlaceholderText("Enter action ID, e.g. A001")
        self.action_id_input.setFont(QFont("Sans", 12))
        self.action_id_input.setStyleSheet(
            "padding: 4px 8px; border: 1px solid #666666;"
            "border-radius: 4px; background-color: #2A2A2A; color: #EEEEEE;"
        )
        self.action_id_input.setMinimumWidth(180)
        row0.addWidget(self.action_id_input)

        path_lbl = QLabel("Subject Path:")
        path_lbl.setFont(QFont("Sans", 12, QFont.Bold))
        row0.addWidget(path_lbl)

        self.subject_path_input = QLineEdit()
        self.subject_path_input.setPlaceholderText(
            "Enter subject root path, e.g. /Volumes/SSD/person_01/location_a"
        )
        self.subject_path_input.setFont(QFont("Sans", 12))
        self.subject_path_input.setStyleSheet(
            "padding: 4px 8px; border: 1px solid #666666;"
            "border-radius: 4px; background-color: #2A2A2A; color: #EEEEEE;"
        )
        row0.addWidget(self.subject_path_input, stretch=1)
        root.addWidget(self._row0_widget)

        # Row 2 -- label input (hidden when breakpoint is disabled)
        self._row1_widget = QWidget()
        row1 = QHBoxLayout(self._row1_widget)
        row1.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Action Labels:")
        lbl.setFont(QFont("Sans", 12, QFont.Bold))
        row1.addWidget(lbl)

        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText(
            "Enter dash-separated labels, e.g.  walk-sit-read"
        )
        self.label_input.setFont(QFont("Sans", 12))
        self.label_input.setStyleSheet(
            "padding: 4px 8px; border: 1px solid #666666;"
            "border-radius: 4px; background-color: #2A2A2A; color: #EEEEEE;"
        )
        row1.addWidget(self.label_input, stretch=1)
        root.addWidget(self._row1_widget)

        if not self._enable_breakpoint:
            self._row1_widget.hide()

        # Row 3 -- buttons + progress text
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        self.btn_start = self._make_button(
            "Start", "#2E7D32", "#1B5E20"
        )
        self.btn_breakpoint = self._make_button(
            "Breakpoint", "#1565C0", "#0D47A1"
        )
        self.btn_stop = self._make_button(
            "Stop", "#E65100", "#BF360C"
        )
        self.btn_cancel = self._make_button(
            "Cancel", "#B71C1C", "#7F0000"
        )

        for btn in (self.btn_start, self.btn_breakpoint,
                     self.btn_stop, self.btn_cancel):
            row2.addWidget(btn)

        if not self._enable_breakpoint:
            self.btn_breakpoint.hide()

        self.progress_label = QLabel("")
        self.progress_label.setFont(QFont("Sans", 12))
        self.progress_label.setStyleSheet("color: #AAAAAA; padding-left: 12px;")
        self.progress_label.setMinimumWidth(220)
        row2.addWidget(self.progress_label, stretch=1)
        root.addLayout(row2)

        # Initial button state
        self.set_idle_state()

    @staticmethod
    def _make_button(text, bg, hover_bg):
        btn = QPushButton(text)
        btn.setFixedHeight(36)
        btn.setFont(QFont("Sans", 11, QFont.Bold))
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {bg}; color: #FFFFFF;"
            f"  border: none; border-radius: 4px; padding: 0 18px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {hover_bg}; }}"
            f"QPushButton:disabled {{"
            f"  background-color: #555555; color: #888888;"
            f"}}"
        )
        return btn

    # ---- internal signal wiring --------------------------------------------

    def _wire_signals(self):
        self.btn_start.clicked.connect(self._on_start)
        self.btn_breakpoint.clicked.connect(self._on_breakpoint)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_cancel.clicked.connect(self._on_cancel)

    def _on_start(self):
        session_request = self.get_session_request()
        if session_request is not None:
            self.start_requested.emit(session_request)

    def _on_breakpoint(self):
        self.breakpoint_requested.emit()

    def _on_stop(self):
        self.stop_requested.emit()

    def _on_cancel(self):
        self.cancel_requested.emit()

    # ---- public helpers ----------------------------------------------------

    def get_action_id(self):
        return self.action_id_input.text().strip()

    def get_subject_path(self):
        return self.subject_path_input.text().strip()

    def get_labels(self, default_label=None):
        """Parse the optional breakpoint field into one or more labels."""
        raw = self.label_input.text().strip()
        if not raw:
            return [default_label] if default_label else []
        return [t.strip() for t in raw.split("-") if t.strip()]

    def get_session_request(self):
        action_id = self.get_action_id()
        subject_path = self.get_subject_path()

        if not action_id:
            self._show_validation_error("Action ID is required.")
            return None
        if "/" in action_id or "\\" in action_id:
            self._show_validation_error(
                "Action ID must be a single path segment, not a nested path."
            )
            return None
        if action_id in (".", ".."):
            self._show_validation_error("Action ID cannot be '.' or '..'.")
            return None
        if not subject_path:
            self._show_validation_error("Subject Path is required.")
            return None

        labels = self.get_labels(default_label=action_id)
        return {
            "action_id": action_id,
            "subject_path": subject_path,
            "labels": labels,
        }

    def _show_validation_error(self, message):
        QMessageBox.warning(self, "Invalid Session Setup", message)

    # ---- state transitions -------------------------------------------------

    def set_idle_state(self):
        self.action_id_input.setReadOnly(False)
        self.subject_path_input.setReadOnly(False)
        self.label_input.setReadOnly(False)
        self.btn_start.setEnabled(True)
        self.btn_breakpoint.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.progress_label.setText("")

    def set_recording_state(self, has_multiple_labels=True):
        self.action_id_input.setReadOnly(True)
        self.subject_path_input.setReadOnly(True)
        self.label_input.setReadOnly(True)
        self.btn_start.setEnabled(False)
        # Never enable breakpoint button when the feature is disabled globally
        self.btn_breakpoint.setEnabled(
            has_multiple_labels and self._enable_breakpoint
        )
        self.btn_stop.setEnabled(True)
        self.btn_cancel.setEnabled(True)

    def set_processing_state(self):
        self.action_id_input.setReadOnly(True)
        self.subject_path_input.setReadOnly(True)
        self.label_input.setReadOnly(True)
        self.btn_start.setEnabled(False)
        self.btn_breakpoint.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.progress_label.setText("Processing ...")

    def update_progress(self, current_label, index, total):
        """Update the progress text during recording.

        Parameters
        ----------
        current_label : str
        index : int   (0-based)
        total : int
        """
        suffix = ""
        if index == total - 1:
            suffix = "  [last]"
        self.progress_label.setText(
            f"Recording: {current_label}  ({index + 1}/{total}){suffix}"
        )

    def set_breakpoint_enabled(self, enabled):
        self.btn_breakpoint.setEnabled(enabled)