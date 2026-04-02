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
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QFont


class ControlPanel(QWidget):
    """Recording control bar."""

    # ---- signals -----------------------------------------------------------
    start_requested      = pyqtSignal(list)   # parsed label list
    breakpoint_requested = pyqtSignal()
    stop_requested       = pyqtSignal()
    cancel_requested     = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._wire_signals()

    # ---- UI construction ---------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(6)

        # Row 1 -- label input
        row1 = QHBoxLayout()
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
        root.addLayout(row1)

        # Row 2 -- buttons + progress text
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
        labels = self.get_labels()
        if labels:
            self.start_requested.emit(labels)

    def _on_breakpoint(self):
        self.breakpoint_requested.emit()

    def _on_stop(self):
        self.stop_requested.emit()

    def _on_cancel(self):
        self.cancel_requested.emit()

    # ---- public helpers ----------------------------------------------------

    def get_labels(self):
        """Parse the text field and return a list of non-empty labels."""
        raw = self.label_input.text().strip()
        if not raw:
            return []
        return [t.strip() for t in raw.split("-") if t.strip()]

    # ---- state transitions -------------------------------------------------

    def set_idle_state(self):
        self.label_input.setReadOnly(False)
        self.btn_start.setEnabled(True)
        self.btn_breakpoint.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.progress_label.setText("")

    def set_recording_state(self, has_multiple_labels=True):
        self.label_input.setReadOnly(True)
        self.btn_start.setEnabled(False)
        self.btn_breakpoint.setEnabled(has_multiple_labels)
        self.btn_stop.setEnabled(True)
        self.btn_cancel.setEnabled(True)

    def set_processing_state(self):
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