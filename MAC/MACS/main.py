#!/usr/bin/env python3
"""
main.py
-------
Entry point for the MACS capture application.

Usage
-----
    python3 main.py                       # production (real cameras)
    python3 main.py --demo                # synthetic frames, no hardware
    python3 main.py --config path.yaml    # custom config
    python3 main.py --imu-device imu03_waist --imu-device imu04_left_ankle
"""

import sys
import os
import argparse

import numpy as np

from runtime_config import apply_runtime_imu_selection

# ---------------------------------------------------------------------------
# Guard against opencv-python hijacking Qt's platform plugin path.
# opencv-python (non-headless) sets QT_QPA_PLATFORM_PLUGIN_PATH to its own
# bundled Qt plugins directory on import, which breaks PyQt5 initialisation.
# We capture the value *before* the ui package (which may import cv2
# transitively) is loaded, then restore it so QApplication finds the correct
# PyQt5 plugins.
# ---------------------------------------------------------------------------
_qt_plugin_path_before = os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

from ui.main_window import MainWindow

# Restore / clear the plugin path after all module-level imports are done.
if _qt_plugin_path_before is None:
    os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
else:
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = _qt_plugin_path_before


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_config(path):
    if not os.path.isfile(path):
        print(f"[config] {path} not found, using defaults")
        return {}
    try:
        import yaml
        with open(path, "r") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:
        print(f"[config] failed to parse {path}: {exc}")
        return {}


# ---------------------------------------------------------------------------
# Demo frame generator (no hardware required)
# ---------------------------------------------------------------------------

class DemoFrameGenerator:
    """Pushes synthetic frames into the UI for testing."""

    def __init__(self, window):
        self._win = window
        self._tick = 0
        self._timer = QTimer()
        self._timer.timeout.connect(self._generate)
        self._timer.start(67)

    def _generate(self):
        if self._win.state.name != "RECORDING":
            return
        self._tick += 1
        t = self._tick

        self._win.update_frame("RGB",     self._rgb(t),     15.0)
        self._win.update_frame("Depth",   self._depth(t),   15.0)
        self._win.update_frame("IR",      self._ir(t),      15.0)
        self._win.update_frame("Thermal", self._thermal(t), 30.0)

        self._win.status_panel.update_fps(
            rgb=15.0, depth=15.0, ir=15.0, thermal=30.0,
        )
        drift = 8.0 + 12.0 * abs(np.sin(t * 0.02))
        self._win.status_panel.update_sync(drift_ms=drift)
        self._win.status_panel.update_health("OK")

    @staticmethod
    def _rgb(t):
        f = np.zeros((480, 640, 3), dtype=np.uint8)
        c = np.linspace(0, 255, 640, dtype=np.uint8)
        f[:, :, 0] = c
        f[:, :, 2] = c[::-1]
        bar = (t * 4) % 640
        f[:, max(bar - 8, 0):min(bar + 8, 640), 1] = 255
        return f

    @staticmethod
    def _depth(t):
        bg = np.full((480, 640), 4000, dtype=np.uint16)
        yy, xx = np.ogrid[:480, :640]
        cx = 320 + int(180 * np.sin(t * 0.04))
        cy = 240 + int(100 * np.cos(t * 0.03))
        bg[((xx - cx) ** 2 + (yy - cy) ** 2) < 70 ** 2] = 1200
        return bg

    @staticmethod
    def _ir(t):
        base = np.random.randint(1000, 4000, (480, 640), dtype=np.uint16)
        yy, xx = np.ogrid[:480, :640]
        cx = 320 + int(150 * np.sin(t * 0.05))
        cy = 240 + int(80 * np.cos(t * 0.04))
        spot = np.clip(50000 - ((xx - cx) ** 2 + (yy - cy) ** 2), 0, 65535)
        return np.maximum(base, spot.astype(np.uint16))

    @staticmethod
    def _thermal(t):
        c = np.zeros((192, 256, 3), dtype=np.uint8)
        c[:, :, 0] = 30
        yy, xx = np.ogrid[:192, :256]
        cx = 128 + int(70 * np.sin(t * 0.045))
        cy = 96  + int(40 * np.cos(t * 0.06))
        d = np.sqrt(((xx - cx) ** 2 + (yy - cy) ** 2).astype(np.float32))
        heat = np.clip(255 - d * 2.8, 0, 255).astype(np.uint8)
        c[:, :, 2] = heat
        c[:, :, 1] = heat // 3
        return c


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="MACS - MultiModal Action Capture System"
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Run with synthetic frames (no cameras needed)",
    )
    parser.add_argument(
        "--config", type=str, default="config/default.yaml",
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--imu-device",
        action="append",
        default=[],
        help="Only enable the named IMU label; repeat to keep multiple labels",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    apply_runtime_imu_selection(config, args.imu_device)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow(config=config)
    window.show()

    controller = None
    generator = None

    if args.demo:
        generator = DemoFrameGenerator(window)
    else:
        from capture.capture_controller import CaptureController
        controller = CaptureController(config, window)
        controller.initialize()
        app.aboutToQuit.connect(controller.shutdown)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()