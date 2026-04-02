"""
preview_panel.py
----------------
2x2 grid widget that displays the four modality streams
(RGB, Depth, IR, Thermal) in real time.
"""

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QGridLayout, QVBoxLayout, QLabel, QSizePolicy,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap, QFont


# ---------------------------------------------------------------------------
# Single modality viewport
# ---------------------------------------------------------------------------

class ModalityView(QWidget):
    """Displays a single modality frame with a title and info bar."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._title_text = title
        self._build_ui()

    # -- UI ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Title
        self._title = QLabel(self._title_text)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setFont(QFont("Monospace", 11, QFont.Bold))
        self._title.setStyleSheet(
            "color: #CCCCCC; background-color: #333333; padding: 2px;"
        )
        layout.addWidget(self._title)

        # Frame display
        self._canvas = QLabel()
        self._canvas.setAlignment(Qt.AlignCenter)
        self._canvas.setMinimumSize(160, 120)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas.setStyleSheet(
            "background-color: #1A1A1A; border: 1px solid #444444;"
        )
        self._canvas.setScaledContents(False)
        layout.addWidget(self._canvas, stretch=1)

        # Info (resolution + fps)
        self._info = QLabel("-- x -- | -- fps")
        self._info.setAlignment(Qt.AlignCenter)
        self._info.setFont(QFont("Monospace", 9))
        self._info.setStyleSheet("color: #777777; padding: 1px;")
        layout.addWidget(self._info)

    # -- public API ----------------------------------------------------------

    def update_frame(self, frame, fps=None):
        """Push a new numpy frame to the display.

        Parameters
        ----------
        frame : np.ndarray
            (H, W) uint8/uint16 grayscale  **or**  (H, W, 3) uint8 BGR.
        fps : float, optional
            Current capture rate to show in the info bar.
        """
        if frame is None:
            return

        pixmap = self._to_pixmap(frame)
        if pixmap is not None:
            scaled = pixmap.scaled(
                self._canvas.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._canvas.setPixmap(scaled)

        h, w = frame.shape[:2]
        fps_str = f"{fps:.1f}" if fps is not None else "--"
        self._info.setText(f"{w} x {h} | {fps_str} fps")

    def clear(self):
        self._canvas.clear()
        self._canvas.setStyleSheet(
            "background-color: #1A1A1A; border: 1px solid #444444;"
        )
        self._info.setText("-- x -- | -- fps")

    # -- conversion ----------------------------------------------------------

    @staticmethod
    def _to_pixmap(frame):
        """Convert a numpy array to QPixmap (data is deep-copied)."""
        import cv2  # lazy import: called only after QApplication is running,
                    # preventing opencv-python from hijacking QT_QPA_PLATFORM_PLUGIN_PATH
        if frame is None:
            return None

        # --- grayscale / 16-bit ---
        if frame.ndim == 2:
            if frame.dtype == np.uint16:
                norm = cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX)
                gray = np.ascontiguousarray(norm.astype(np.uint8))
            else:
                gray = np.ascontiguousarray(frame.astype(np.uint8))
            h, w = gray.shape
            qimg = QImage(gray.data, w, h, w, QImage.Format_Grayscale8).copy()
            return QPixmap.fromImage(qimg)

        # --- 3-channel BGR ---
        if frame.ndim == 3 and frame.shape[2] == 3:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb = np.ascontiguousarray(rgb)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, w * ch, QImage.Format_RGB888).copy()
            return QPixmap.fromImage(qimg)

        return None


# ---------------------------------------------------------------------------
# 2x2 grid panel
# ---------------------------------------------------------------------------

class PreviewPanel(QWidget):
    """Arranges four ModalityView widgets in a 2x2 grid."""

    LAYOUT_MAP = {
        "RGB":     (0, 0),
        "Depth":   (0, 1),
        "IR":      (1, 0),
        "Thermal": (1, 1),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._views = {}
        self._build_ui()

    def _build_ui(self):
        grid = QGridLayout(self)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setSpacing(4)

        for name, (row, col) in self.LAYOUT_MAP.items():
            view = ModalityView(name, self)
            grid.addWidget(view, row, col)
            self._views[name] = view

    # -- public API ----------------------------------------------------------

    def update_frame(self, modality, frame, fps=None):
        """Forward a frame to the corresponding viewport."""
        view = self._views.get(modality)
        if view is not None:
            view.update_frame(frame, fps)

    def clear_all(self):
        for v in self._views.values():
            v.clear()