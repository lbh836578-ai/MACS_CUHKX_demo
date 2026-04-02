"""
base_driver.py
--------------
Abstract base class for all MACS camera drivers.

Concrete subclasses must implement:
  * connect_device()   -- open hardware, configure streams
  * disconnect_device() -- release hardware
  * _capture_loop()    -- blocking read loop, emit ``frame_captured``

The driver runs its capture loop inside a dedicated QThread.
"""

from PyQt5.QtCore import QThread, pyqtSignal


class BaseCameraDriver(QThread):
    """Thread-safe camera driver base with a start/stop lifecycle."""

    # (modality: str, frame: numpy.ndarray, timestamp_ns: int)
    frame_captured = pyqtSignal(str, object, object)

    # (error_message: str)
    error_occurred = pyqtSignal(str)

    # Emitted once after connect_device() succeeds
    connected = pyqtSignal()

    # Emitted after disconnect_device() completes
    disconnected = pyqtSignal()

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self._cfg = config or {}
        self._running = False
        self._is_connected = False

    # -- abstract interface (override in subclasses) -------------------------

    def connect_device(self):
        """Open and configure the hardware device.

        Raise ``RuntimeError`` on failure.
        """
        raise NotImplementedError

    def disconnect_device(self):
        """Release all hardware resources.  Must be idempotent."""
        raise NotImplementedError

    def _capture_loop(self):
        """Blocking loop; read frames and ``emit frame_captured`` until
        ``self._running`` becomes ``False``.
        """
        raise NotImplementedError

    # -- public helpers ------------------------------------------------------

    def is_connected(self):
        return self._is_connected

    # -- QThread entry point -------------------------------------------------

    def run(self):
        self._running = True

        # --- connect --------------------------------------------------------
        try:
            self.connect_device()
            self._is_connected = True
            self.connected.emit()
        except Exception as exc:
            self.error_occurred.emit(
                f"{self.__class__.__name__} connect failed: {exc}"
            )
            self._running = False
            return

        # --- capture --------------------------------------------------------
        try:
            self._capture_loop()
        except Exception as exc:
            self.error_occurred.emit(
                f"{self.__class__.__name__} capture error: {exc}"
            )

        # --- disconnect -----------------------------------------------------
        try:
            self.disconnect_device()
        except Exception:
            pass

        self._is_connected = False
        self._running = False
        self.disconnected.emit()

    def stop(self, timeout_ms=5000):
        """Set the stop flag and block until the thread finishes."""
        self._running = False
        if self.isRunning():
            self.wait(timeout_ms)