"""
mmwave_driver.py
----------------
Persistent mmWave collector for the TI IWR6843ISK.

The driver separates two phases:

* ``prepare()``: open serial ports, push the full radar configuration, and
  start a background reader thread.
* ``start_session()`` / ``stop_session()``: arm and disarm writes into the
  active MACS session directory while keeping the radar warm between runs.

This lets MACS share the same ``session_dir`` and ``recording_start_ns``
with the existing camera recorder instead of creating a second session tree.
"""

import csv
import queue
import struct
import threading
import time
from pathlib import Path

try:
    import serial
except ImportError:
    serial = None


MAGIC_WORD = b"\x02\x01\x04\x03\x06\x05\x08\x07"
HEADER_LEN = 40
WRITER_STOP = object()


class MmWaveDriver:
    """Persistent mmWave collector with session-based output gating."""

    def __init__(self, config=None, logger=None):
        self._cfg = config or {}
        self._log_fn = logger

        self._enabled = bool(self._cfg.get("enabled", False))
        self._cli_port = self._cfg.get("cli_port", "/dev/ttyUSB0")
        self._data_port = self._cfg.get("data_port", "/dev/ttyUSB1")
        self._cli_baudrate = int(self._cfg.get("cli_baudrate", 115200))
        self._data_baudrate = int(self._cfg.get("data_baudrate", 921600))
        self._read_chunk_size = int(self._cfg.get("read_chunk_size", 4096))
        self._max_packet_size = int(self._cfg.get("max_packet_size", 65536))
        self._writer_queue_size = int(self._cfg.get("writer_queue_size", 512))
        self._command_timeout_s = float(self._cfg.get("command_timeout_s", 3.0))
        self._post_config_delay_s = float(
            self._cfg.get("post_config_delay_s", 1.0)
        )

        self._config_path = self._resolve_config_path(
            self._cfg.get("config_path", "config/profile_human.cfg")
        )

        self._cli_ser = None
        self._data_ser = None
        self._thread = None
        self._running = False
        self._prepared = False

        self._buffer = bytearray()
        self._session_lock = threading.Lock()
        self._session_active = False
        self._session_dir = None
        self._session_start_ns = 0
        self._bin_file = None
        self._ts_file = None
        self._ts_writer = None
        self._writer_queue = None
        self._writer_thread = None
        self._session_frame_count = 0
        self._last_session_frame_count = 0
        self._writer_stats = {"written": 0, "dropped": 0, "errors": 0}
        self._last_writer_stats = dict(self._writer_stats)

        self._last_error = None
        self._warnings = []

    @property
    def enabled(self):
        return self._enabled

    def prepare(self):
        """Warm up the radar and start the background reader thread."""
        if not self._enabled:
            return False
        if self._prepared:
            return True
        if serial is None:
            self._last_error = "pyserial is not installed"
            self._log("mmWave disabled: pyserial is not installed")
            return False
        if not self._config_path.is_file():
            self._last_error = f"config file not found: {self._config_path}"
            self._log(f"mmWave prepare failed: {self._last_error}")
            return False

        try:
            self._data_ser = serial.Serial(
                self._data_port,
                self._data_baudrate,
                timeout=0.5,
            )
            self._cli_ser = serial.Serial(
                self._cli_port,
                self._cli_baudrate,
                timeout=0.2,
            )
            time.sleep(0.5)
            self._push_configuration()

            self._running = True
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            self._prepared = True
            self._last_error = None
            self._log(
                f"mmWave prepared on {self._cli_port}/{self._data_port} "
                f"using {self._config_path}"
            )
            return True
        except Exception as exc:
            self._last_error = str(exc)
            self._prepared = False
            self._running = False
            self._cleanup_ports()
            self._log(f"mmWave prepare failed: {exc}")
            return False

    def start_session(self, session_dir, session_start_ns):
        """Start writing mmWave data into *session_dir* / mmwave."""
        if not self._enabled:
            return False
        if not self._prepared:
            self._last_error = "mmWave is not prepared"
            self._log("mmWave session not started: driver not prepared")
            return False

        out_dir = Path(session_dir) / "mmwave"
        out_dir.mkdir(parents=True, exist_ok=True)

        self._stop_writer_and_close_files()

        writer_queue = queue.Queue(maxsize=self._writer_queue_size)
        writer_thread = threading.Thread(
            target=self._writer_loop,
            args=(writer_queue,),
            daemon=True,
        )

        with self._session_lock:
            self._session_dir = out_dir
            self._session_start_ns = int(session_start_ns)
            self._session_frame_count = 0
            self._bin_file = open(out_dir / "frames.bin", "wb")
            self._ts_file = open(out_dir / "timestamps.csv", "w", newline="")
            self._ts_writer = csv.writer(self._ts_file)
            self._ts_writer.writerow(["frame_idx", "timestamp_ns", "num_points"])
            self._writer_queue = writer_queue
            self._writer_thread = writer_thread
            self._writer_stats = {"written": 0, "dropped": 0, "errors": 0}
            self._session_active = True

        writer_thread.start()

        self._log(f"mmWave armed for session: {out_dir}")
        return True

    def stop_session(self):
        """Stop the active session and return a serialisable summary."""
        if not self._enabled:
            return self.get_summary()

        with self._session_lock:
            self._last_session_frame_count = self._session_frame_count
            self._session_active = False

        self._last_writer_stats = self._stop_writer_and_close_files()

        return self.get_summary()

    def discard_session(self):
        """Close any active session without preserving per-run counters."""
        summary = self.stop_session()
        self._last_session_frame_count = 0
        return summary

    def shutdown(self):
        """Stop the reader thread and close all serial resources."""
        self.stop_session()
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._send_sensor_stop()
        self._cleanup_ports()
        self._prepared = False

    def get_summary(self):
        with self._session_lock:
            session_dir = str(self._session_dir) if self._session_dir else None
            active = self._session_active
            frames = self._session_frame_count if active else self._last_session_frame_count
            queue_depth = self._writer_queue.qsize() if self._writer_queue is not None else 0
            writer_stats = dict(self._writer_stats if active else self._last_writer_stats)
        return {
            "enabled": self._enabled,
            "prepared": self._prepared,
            "recorded": bool(frames),
            "subdir": "mmwave",
            "session_dir": session_dir,
            "frames_captured": frames,
            "writer_queue_size": self._writer_queue_size,
            "writer_queue_depth": queue_depth,
            "writer_stats": writer_stats,
            "cli_port": self._cli_port,
            "data_port": self._data_port,
            "config_path": str(self._config_path),
            "error": self._last_error,
            "warnings": list(self._warnings),
        }

    def _run(self):
        while self._running and self._data_ser is not None:
            try:
                chunk = self._data_ser.read(self._read_chunk_size)
            except Exception as exc:
                self._last_error = str(exc)
                self._log(f"mmWave read error: {exc}")
                break

            if not chunk:
                continue

            self._buffer.extend(chunk)
            while True:
                packet = self._extract_packet()
                if packet is None:
                    break
                self._record_packet(packet, time.time_ns())

        self._running = False

    def _record_packet(self, packet, timestamp_ns):
        num_points = self._parse_num_points(packet)
        with self._session_lock:
            if not self._session_active:
                return
            if timestamp_ns < self._session_start_ns:
                return
            if self._bin_file is None or self._ts_writer is None:
                return
            frame_idx = self._session_frame_count
            if self._writer_queue is None:
                return
            try:
                self._writer_queue.put_nowait(
                    (frame_idx, timestamp_ns, num_points, packet)
                )
            except queue.Full:
                self._writer_stats["dropped"] += 1
                dropped = self._writer_stats["dropped"]
                if dropped <= 3 or dropped in (10, 50, 100):
                    self._warnings.append(
                        f"mmWave writer queue full, dropped frame_idx={frame_idx}"
                    )
                return
            self._session_frame_count += 1

    def _extract_packet(self):
        while True:
            idx = self._buffer.find(MAGIC_WORD)
            if idx < 0:
                keep = len(MAGIC_WORD) - 1
                if len(self._buffer) > keep:
                    del self._buffer[:-keep]
                return None

            if idx > 0:
                del self._buffer[:idx]

            if len(self._buffer) < HEADER_LEN:
                return None

            total_len = struct.unpack_from("<I", self._buffer, 12)[0]
            if total_len < HEADER_LEN or total_len > self._max_packet_size:
                self._warnings.append(
                    f"discarded malformed packet with total_len={total_len}"
                )
                del self._buffer[:len(MAGIC_WORD)]
                continue

            if len(self._buffer) < total_len:
                return None

            packet = bytes(self._buffer[:total_len])
            del self._buffer[:total_len]
            return packet

    def _push_configuration(self):
        lines = self._load_config_lines()
        for line in lines:
            self._cli_ser.write((line + "\n").encode("ascii"))
            response = self._read_cli_response()
            if "Error" in response and not line.startswith("sensorStop"):
                raise RuntimeError(
                    f"mmWave config rejected '{line}': {response.strip()}"
                )
            if "Done" not in response and line != "sensorStart":
                self._warnings.append(
                    f"command '{line}' returned no explicit Done marker"
                )
        time.sleep(self._post_config_delay_s)

    def _load_config_lines(self):
        lines = []
        with open(self._config_path, "r") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("%"):
                    continue
                lines.append(line)
        return lines

    def _read_cli_response(self):
        deadline = time.time() + self._command_timeout_s
        chunks = []
        while time.time() < deadline:
            waiting = getattr(self._cli_ser, "in_waiting", 0) or 1
            block = self._cli_ser.read(waiting)
            if block:
                text = block.decode(errors="ignore")
                chunks.append(text)
                if "Done" in text or "Error" in text:
                    break
            else:
                time.sleep(0.05)
        return "".join(chunks)

    def _send_sensor_stop(self):
        if self._cli_ser is None:
            return
        try:
            self._cli_ser.write(b"sensorStop\n")
            self._read_cli_response()
        except Exception:
            pass

    def _cleanup_ports(self):
        for handle in (self._cli_ser, self._data_ser):
            if handle is None:
                continue
            try:
                handle.close()
            except Exception:
                pass
        self._cli_ser = None
        self._data_ser = None

    def _close_session_files_locked(self):
        for handle in (self._ts_file, self._bin_file):
            if handle is None:
                continue
            try:
                handle.flush()
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass
        self._bin_file = None
        self._ts_file = None
        self._ts_writer = None

    def _stop_writer_and_close_files(self):
        writer_queue = None
        writer_thread = None
        with self._session_lock:
            writer_queue = self._writer_queue
            writer_thread = self._writer_thread
            self._writer_queue = None
            self._writer_thread = None

        if writer_queue is not None:
            writer_queue.put(WRITER_STOP)
        if writer_thread is not None:
            writer_thread.join(timeout=10)

        with self._session_lock:
            writer_stats = dict(self._writer_stats)
            self._close_session_files_locked()
        return writer_stats

    def _writer_loop(self, writer_queue):
        while True:
            item = writer_queue.get()
            if item is WRITER_STOP:
                break

            frame_idx, timestamp_ns, num_points, packet = item
            try:
                self._bin_file.write(packet)
                self._ts_writer.writerow([frame_idx, timestamp_ns, num_points])
                with self._session_lock:
                    self._writer_stats["written"] += 1
            except Exception as exc:
                with self._session_lock:
                    self._writer_stats["errors"] += 1
                    self._last_error = str(exc)
                self._log(f"mmWave write error: {exc}")

    @staticmethod
    def _parse_num_points(packet):
        if len(packet) < 32:
            return 0
        try:
            return struct.unpack_from("<I", packet, 28)[0]
        except struct.error:
            return 0

    @staticmethod
    def _resolve_config_path(config_path):
        path = Path(config_path)
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parent.parent / path

    def _log(self, msg):
        if self._log_fn is None:
            return
        self._log_fn(msg)