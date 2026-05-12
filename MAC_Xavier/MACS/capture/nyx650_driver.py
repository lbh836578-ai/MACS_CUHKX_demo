"""
nyx650_driver.py
----------------
Driver for the Vzense NYX650 ToF camera via the ScepterSDK Python API.

Streams
* RGB   --  (H, W, 3) uint8  BGR
* Depth --  (H, W)    uint16 millimetres
* IR    --  (H, W)    uint8

SDK compatibility
Targets the 2023-2024 ScepterSDK Python API (ScepterTofCam class with
scGetFrameReady / scGetFrame).  If your SDK version uses a different
API surface, update ``_capture_loop`` and the import block.

If the SDK is not installed, ``connect_device()`` raises RuntimeError and
the rest of the MACS pipeline continues without this camera.
"""

import os
import sys
import time
import ctypes
from ctypes import c_uint16
import importlib
import numpy as np

from .base_driver import BaseCameraDriver

# ---------------------------------------------------------------------------
# SDK import -- probe several common installation locations
# ---------------------------------------------------------------------------

_SDK_AVAILABLE = False
_SDK = None                   # will hold the imported API module
_SDK_ENUMS = None             # will hold the enums module

_SEARCH_PATHS = [
    os.path.expanduser("~/ScepterSDK/MultilanguageSDK/Python"),
    "/opt/ScepterSDK/MultilanguageSDK/Python",
]

for _p in _SEARCH_PATHS:
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    _SDK = importlib.import_module("API.ScepterDS_api")
    _SDK_ENUMS = importlib.import_module("API.ScepterDS_enums")
    _SDK_AVAILABLE = True
except Exception:
    pass


def _sdk(attr, fallback=None):
    """Retrieve *attr* from the imported SDK modules, or *fallback*."""
    if _SDK is not None:
        val = getattr(_SDK, attr, None)
        if val is not None:
            return val
    if _SDK_ENUMS is not None:
        val = getattr(_SDK_ENUMS, attr, None)
        if val is not None:
            return val
    return fallback


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class NYX650Driver(BaseCameraDriver):
    """Captures RGB, Depth, and IR from a Vzense NYX650 ToF camera."""

    SDK_AVAILABLE = _SDK_AVAILABLE

    # Expected modalities -- used by CaptureController to pre-create FPS counters
    MODALITIES = ("RGB", "Depth", "IR")

    def __init__(self, config=None, parent=None):
        super().__init__(config, parent)
        self._cam = None

    # ================================================================
    # Device lifecycle
    # ================================================================

    def connect_device(self):
        if not _SDK_AVAILABLE:
            raise RuntimeError(
                "ScepterSDK Python API not found.  "
                "Searched: " + ", ".join(_SEARCH_PATHS)
            )

        ScepterTofCam = _sdk("ScepterTofCam")
        if ScepterTofCam is None:
            raise RuntimeError("ScepterTofCam class not found in SDK module")

        cam = ScepterTofCam()

        # Device enumeration (timeout 3 s)
        count = cam.scGetDeviceCount(3000)
        if count < 1:
            cam.scShutdown()
            raise RuntimeError("No Scepter/Vzense device found (count=0)")

        info_list = cam.scGetDeviceInfoList(count)
        if isinstance(info_list, tuple):
            info_list = info_list[-1]
        dev = info_list[0]

        sn = getattr(dev, "serialNumber", None) or getattr(dev, "sn", b"")
        rc = cam.scOpenDeviceBySN(sn)
        if rc != 0:
            cam.scShutdown()
            raise RuntimeError(f"scOpenDeviceBySN({sn}) returned {rc}")

        # Active mode (depth + IR)
        try:
            ScWorkMode = _sdk("ScWorkMode")
            if ScWorkMode is not None:
                cam.scSetWorkMode(ScWorkMode.SC_ACTIVE_MODE)
        except Exception:
            pass

        # Attempt to configure colour resolution
        try:
            cam.scSetColorResolution(
                self._cfg.get("rgb", {}).get("width", 1600),
                self._cfg.get("rgb", {}).get("height", 1200),
            )
        except Exception:
            pass

        rc = cam.scStartStream()
        if rc != 0:
            cam.scCloseDevice()
            cam.scShutdown()
            raise RuntimeError(f"scStartStream returned {rc}")

        self._cam = cam

    def disconnect_device(self):
        if self._cam is None:
            return
        for fn in ("scStopStream", "scCloseDevice", "scShutdown"):
            try:
                getattr(self._cam, fn)()
            except Exception:
                pass
        self._cam = None

    # ================================================================
    # Capture loop
    # ================================================================

    def _capture_loop(self):
        ScFrameType = _sdk("ScFrameType")
        ft_depth = ScFrameType.SC_DEPTH_FRAME if ScFrameType else 0
        ft_ir    = ScFrameType.SC_IR_FRAME    if ScFrameType else 1
        ft_color = ScFrameType.SC_COLOR_FRAME  if ScFrameType else 3

        consecutive_errors = 0

        while self._running:
            try:
                result = self._cam.scGetFrameReady(c_uint16(1200))
                if isinstance(result, tuple):
                    rc, ready = result[0], result[1]
                else:
                    rc, ready = 0, result

                if rc != 0:
                    consecutive_errors += 1
                    if consecutive_errors > 20:
                        self.error_occurred.emit(
                            "NYX650: too many consecutive read failures"
                        )
                        break
                    time.sleep(0.005)
                    continue

                consecutive_errors = 0
                ts = time.time_ns()

                if getattr(ready, "depth", 0) == 1:
                    self._try_emit("Depth", ft_depth, np.uint16, ts)

                if getattr(ready, "ir", 0) == 1:
                    self._try_emit("IR", ft_ir, np.uint8, ts)

                if getattr(ready, "color", 0) == 1:
                    self._try_emit_color("RGB", ft_color, ts)

            except Exception as exc:
                self.error_occurred.emit(f"NYX650 loop: {exc}")
                time.sleep(0.05)

    # ================================================================
    # Frame extraction
    # ================================================================

    def _try_emit(self, modality, frame_type, dtype, ts):
        """Get a single-channel frame and emit it."""
        result = self._cam.scGetFrame(frame_type)
        if isinstance(result, tuple):
            rc, raw = result[0], result[1]
        else:
            rc, raw = 0, result
        if rc != 0:
            return
        arr = self._to_ndarray(raw, dtype)
        if arr is not None:
            self.frame_captured.emit(modality, arr, ts)

    def _try_emit_color(self, modality, frame_type, ts):
        """Get the colour frame and emit it."""
        result = self._cam.scGetFrame(frame_type)
        if isinstance(result, tuple):
            rc, raw = result[0], result[1]
        else:
            rc, raw = 0, result
        if rc != 0:
            return
        arr = self._to_color(raw)
        if arr is not None:
            self.frame_captured.emit(modality, arr, ts)

    # -- numpy conversion helpers -------------------------------------------

    @staticmethod
    def _to_ndarray(raw, dtype):
        h = getattr(raw, "height", 0)
        w = getattr(raw, "width", 0)
        buf = getattr(raw, "pFrameData", None)
        if h == 0 or w == 0 or buf is None:
            return None
        try:
            ct = ctypes.c_uint16 if dtype == np.uint16 else ctypes.c_uint8
            ptr = ctypes.cast(buf, ctypes.POINTER(ct))
            return np.ctypeslib.as_array(ptr, shape=(h, w)).copy()
        except Exception:
            pass
        try:
            return np.frombuffer(buf, dtype=dtype).reshape(h, w).copy()
        except Exception:
            return None

    @staticmethod
    def _to_color(raw):
        h = getattr(raw, "height", 0)
        w = getattr(raw, "width", 0)
        buf = getattr(raw, "pFrameData", None)
        if h == 0 or w == 0 or buf is None:
            return None
        try:
            total = h * w * 3
            ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint8))
            return np.ctypeslib.as_array(ptr, shape=(total,)).reshape(h, w, 3).copy()
        except Exception:
            pass
        try:
            return np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3).copy()
        except Exception:
            return None