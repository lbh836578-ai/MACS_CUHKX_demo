"""
status_panel.py
---------------
Bottom status bar displaying live health metrics:
  FPS per modality | sync drift | disk usage | health flag | elapsed time
"""

import os
import time
import shutil

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class StatusPanel(QWidget):
    """Thin bottom bar for real-time system metrics."""

    _LABEL_STYLE = "font-size: 11px; color: #AAAAAA;"

    def __init__(self, data_path="data", parent=None):
        super().__init__(parent)
        self._data_path = data_path
        self._rec_start = None
        self._build_ui()

    # ---- UI ----------------------------------------------------------------

    def _build_ui(self):
        self.setFixedHeight(28)
        self.setStyleSheet(
            "background-color: #1E1E1E; border-top: 1px solid #444444;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(24)

        mono = QFont("Monospace", 9)

        self._fps_lbl    = self._make_label(mono, layout)
        self._sync_lbl   = self._make_label(mono, layout)
        self._disk_lbl   = self._make_label(mono, layout)
        self._health_lbl = self._make_label(mono, layout)
        self._timer_lbl  = self._make_label(mono, layout, stretch=1,
                                             align=Qt.AlignRight | Qt.AlignVCenter)

        self.reset()

    def _make_label(self, font, layout, stretch=0, align=None):
        lbl = QLabel()
        lbl.setFont(font)
        lbl.setStyleSheet(self._LABEL_STYLE)
        if align is not None:
            lbl.setAlignment(align)
        layout.addWidget(lbl, stretch=stretch)
        return lbl

    # ---- public setters ----------------------------------------------------

    def update_fps(self, rgb=None, depth=None, ir=None, thermal=None):
        parts = []
        if rgb is not None:
            parts.append(f"RGB:{rgb:.1f}")
        if depth is not None:
            parts.append(f"D:{depth:.1f}")
        if ir is not None:
            parts.append(f"IR:{ir:.1f}")
        if thermal is not None:
            parts.append(f"T:{thermal:.1f}")
        self._fps_lbl.setText("FPS  " + " | ".join(parts) if parts else "FPS  --")

    def update_sync(self, drift_ms=None):
        if drift_ms is None:
            self._sync_lbl.setText("Sync --")
            self._sync_lbl.setStyleSheet(self._LABEL_STYLE)
            return
        if drift_ms < 33:
            color = "#4CAF50"
        elif drift_ms < 66:
            color = "#FF9800"
        else:
            color = "#F44336"
        self._sync_lbl.setText(f"Sync {drift_ms:.1f}ms")
        self._sync_lbl.setStyleSheet(f"font-size: 11px; color: {color};")

    def update_disk(self):
        path = self._data_path
        if not os.path.exists(path):
            path = os.path.expanduser("~")
        try:
            usage = shutil.disk_usage(path)
            free = usage.free / (1024 ** 3)
            if free > 5:
                color = "#4CAF50"
            elif free > 1:
                color = "#FF9800"
            else:
                color = "#F44336"
            self._disk_lbl.setText(f"Disk {free:.1f}GB")
            self._disk_lbl.setStyleSheet(f"font-size: 11px; color: {color};")
        except OSError:
            self._disk_lbl.setText("Disk N/A")

    def update_health(self, status):
        """status: one of 'OK', 'WARN', 'ERROR'."""
        colors = {"OK": "#4CAF50", "WARN": "#FF9800", "ERROR": "#F44336"}
        c = colors.get(status, "#AAAAAA")
        self._health_lbl.setText(f"Health {status}")
        self._health_lbl.setStyleSheet(
            f"font-size: 11px; color: {c}; font-weight: bold;"
        )

    # ---- recording timer ---------------------------------------------------

    def start_timer(self):
        self._rec_start = time.monotonic()

    def stop_timer(self):
        self._rec_start = None
        self._timer_lbl.setText("")
        self._timer_lbl.setStyleSheet(self._LABEL_STYLE)

    def refresh_timer(self):
        if self._rec_start is None:
            return
        elapsed = time.monotonic() - self._rec_start
        m, s = divmod(int(elapsed), 60)
        self._timer_lbl.setText(f"REC  {m:02d}:{s:02d}")
        self._timer_lbl.setStyleSheet(
            "font-size: 11px; color: #F44336; font-weight: bold;"
        )

    # ---- reset -------------------------------------------------------------

    def reset(self):
        self._fps_lbl.setText("FPS  --")
        self._fps_lbl.setStyleSheet(self._LABEL_STYLE)
        self._sync_lbl.setText("Sync --")
        self._sync_lbl.setStyleSheet(self._LABEL_STYLE)
        self._disk_lbl.setText("Disk --")
        self._disk_lbl.setStyleSheet(self._LABEL_STYLE)
        self._health_lbl.setText("Health --")
        self._health_lbl.setStyleSheet(self._LABEL_STYLE)
        self.stop_timer()