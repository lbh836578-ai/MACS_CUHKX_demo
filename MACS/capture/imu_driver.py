"""
imu_driver.py
-------------
Persistent BLE collector for WitMotion WT9011DCL-BT50 IMUs.

The driver keeps BLE connections warm between sessions and only writes CSV
rows while a MACS session is armed. Notifications are parsed as a byte stream
because a single callback can contain fragmented or concatenated WT901 packets.
"""

import asyncio
import csv
import queue
import threading
import time
from pathlib import Path

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    BleakClient = None
    BleakScanner = None


NOTIFY_UUID = "0000ffe4-0000-1000-8000-00805f9a34fb"
WRITE_UUID = "0000ffe9-0000-1000-8000-00805f9a34fb"

SAMPLE_FIELDS = [
    "timestamp_ns",
    "acc_x",
    "acc_y",
    "acc_z",
    "gyro_x",
    "gyro_y",
    "gyro_z",
    "angle_x",
    "angle_y",
    "angle_z",
]


def _normalise_mac(mac):
    return (mac or "").strip().upper()


def _signed_16(value):
    return value if value < 32768 else value - 65536


def _rate_command(sample_rate_hz):
    mapping = {
        10: 0x06,
        20: 0x07,
        50: 0x08,
        100: 0x09,
        200: 0x0A,
    }
    code = mapping.get(int(sample_rate_hz), 0x08)
    return bytes([0xFF, 0xAA, 0x03, code, 0x00])


def _parse_measurement_frame(frame):
    if len(frame) != 20 or frame[0] != 0x55 or frame[1] != 0x61:
        return None

    words = [
        int.from_bytes(frame[idx:idx + 2], "little")
        for idx in range(2, 20, 2)
    ]
    return {
        "acc_x": _signed_16(words[0]) / 32768.0 * 16.0,
        "acc_y": _signed_16(words[1]) / 32768.0 * 16.0,
        "acc_z": _signed_16(words[2]) / 32768.0 * 16.0,
        "gyro_x": _signed_16(words[3]) / 32768.0 * 2000.0,
        "gyro_y": _signed_16(words[4]) / 32768.0 * 2000.0,
        "gyro_z": _signed_16(words[5]) / 32768.0 * 2000.0,
        "angle_x": _signed_16(words[6]) / 32768.0 * 180.0,
        "angle_y": _signed_16(words[7]) / 32768.0 * 180.0,
        "angle_z": _signed_16(words[8]) / 32768.0 * 180.0,
    }


def _format_exception(exc):
    text = str(exc).strip()
    if not text:
        text = exc.__class__.__name__
    if "org.bluez.Error.InProgress" in text:
        text += " (Bluetooth adapter is already handling another connect/start operation)"
    return text


class _Wt901StreamParser:
    FRAME_LEN = 20

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, chunk):
        self._buffer.extend(chunk)
        frames = []

        while True:
            idx = self._buffer.find(b"\x55")
            if idx < 0:
                keep = self.FRAME_LEN - 1
                if len(self._buffer) > keep:
                    del self._buffer[:-keep]
                break
            if idx > 0:
                del self._buffer[:idx]
            if len(self._buffer) < self.FRAME_LEN:
                break
            if self._buffer[1] != 0x61:
                del self._buffer[0]
                continue

            frames.append(bytes(self._buffer[:self.FRAME_LEN]))
            del self._buffer[:self.FRAME_LEN]

        return frames


class _ImuSessionState:
    STOP_SENTINEL = object()

    def __init__(self, labels):
        self._labels = list(labels)
        self._lock = threading.Lock()
        self._active = False
        self._session_dir = None
        self._session_start_ns = 0
        self._files = {}
        self._writers = {}
        self._row_queue = None
        self._writer_thread = None
        self._sample_counts = {label: 0 for label in self._labels}

    def activate(self, output_dir, session_start_ns):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        self.deactivate()

        with self._lock:
            self._session_dir = output_dir
            self._session_start_ns = int(session_start_ns)
            self._sample_counts = {label: 0 for label in self._labels}

            for label in self._labels:
                path = output_dir / f"{label}.csv"
                handle = open(path, "w", newline="")
                writer = csv.DictWriter(handle, fieldnames=SAMPLE_FIELDS)
                writer.writeheader()
                self._files[label] = handle
                self._writers[label] = writer

            self._row_queue = queue.Queue()
            self._active = True
            self._writer_thread = threading.Thread(
                target=self._writer_loop,
                args=(self._row_queue,),
                daemon=True,
            )
            self._writer_thread.start()

    def deactivate(self):
        row_queue = None
        writer_thread = None
        with self._lock:
            row_queue = self._row_queue
            writer_thread = self._writer_thread
            self._active = False
            self._row_queue = None
            self._writer_thread = None

        if row_queue is not None:
            row_queue.put(self.STOP_SENTINEL)
        if writer_thread is not None:
            writer_thread.join(timeout=5)

        with self._lock:
            counts = dict(self._sample_counts)
            session_dir = str(self._session_dir) if self._session_dir else None
            self._close_locked()
        return counts, session_dir

    def write_sample(self, label, timestamp_ns, sample):
        with self._lock:
            if not self._active:
                return False
            if timestamp_ns < self._session_start_ns:
                return False
            if label not in self._writers:
                return False
            row_queue = self._row_queue
            if row_queue is None:
                return False

            row = {"timestamp_ns": timestamp_ns}
            row.update(sample)

        row_queue.put((label, row))
        return True

    def _close_locked(self):
        self._active = False
        for handle in self._files.values():
            try:
                handle.flush()
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass
        self._files = {}
        self._writers = {}
        self._session_dir = None
        self._session_start_ns = 0

    def _writer_loop(self, row_queue):
        while True:
            item = row_queue.get()
            if item is self.STOP_SENTINEL:
                break

            label, row = item
            with self._lock:
                writer = self._writers.get(label)
                if writer is None:
                    continue
                writer.writerow(row)
                self._sample_counts[label] += 1


class _ImuDeviceRunner:
    def __init__(self, driver, label, mac, initial_delay_s=0.0):
        self._driver = driver
        self._label = label
        self._mac = mac
        self._initial_delay_s = max(0.0, float(initial_delay_s))
        self._parser = _Wt901StreamParser()

    async def run(self):
        first_attempt_done = False
        if self._initial_delay_s > 0:
            await asyncio.sleep(self._initial_delay_s)

        while not self._driver.stop_requested:
            disconnected = asyncio.Event()
            target = self._driver.get_ble_target(self._mac)
            self._driver.mark_connect_attempt(self._label)
            client = BleakClient(
                target,
                timeout=self._driver.connect_timeout_s,
                disconnected_callback=lambda _client: disconnected.set(),
            )
            was_connected = False
            failure_stage = "connect"
            disconnect_reason = None
            try:
                self._driver.log(
                    f"IMU connect attempt: {self._label} ({self._mac})"
                )
                async with self._driver.connect_lock:
                    await client.connect()
                    if not client.is_connected:
                        raise RuntimeError(
                            "BLE connect returned without an active link"
                        )

                    failure_stage = "write_gatt_char"
                    try:
                        await client.write_gatt_char(
                            self._driver.write_uuid,
                            _rate_command(self._driver.sample_rate_hz),
                            response=False,
                        )
                        self._driver.record_device_event(
                            self._label,
                            "write_gatt_char",
                            "success",
                        )
                    except Exception as exc:
                        self._driver.set_device_error(
                            self._label,
                            f"failed to set sample rate: {_format_exception(exc)}",
                            stage="write_gatt_char",
                        )

                    failure_stage = "start_notify"
                    await client.start_notify(
                        self._driver.notify_uuid,
                        self._handle_notification,
                    )
                    self._driver.record_device_event(
                        self._label,
                        "start_notify",
                        "success",
                    )

                self._driver.set_device_connected(self._label, True)
                self._driver.mark_connect_success(self._label)
                self._driver.clear_device_error(self._label)
                self._driver.mark_initial_attempt(self._label)
                first_attempt_done = True
                was_connected = True
                self._driver.log(
                    f"IMU connected: {self._label} ({self._mac})"
                )

                stop_task = asyncio.create_task(self._driver.async_stop.wait())
                drop_task = asyncio.create_task(disconnected.wait())
                done, pending = await asyncio.wait(
                    {stop_task, drop_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()

                if drop_task in done and not self._driver.stop_requested:
                    disconnect_reason = "device disconnected unexpectedly"
                    self._driver.set_device_error(
                        self._label,
                        disconnect_reason,
                        stage="notify_stream",
                    )

            except Exception as exc:
                formatted_error = _format_exception(exc)
                self._driver.set_device_connected(self._label, False)
                self._driver.set_device_error(
                    self._label,
                    formatted_error,
                    stage=failure_stage,
                )
                if not first_attempt_done:
                    self._driver.mark_initial_attempt(self._label)
                    first_attempt_done = True
                if self._driver.stop_requested:
                    break
                if self._driver.should_refresh_scan(formatted_error):
                    await self._driver.refresh_scan_cache(self._driver.retry_scan_s)
                await asyncio.sleep(self._driver.reconnect_delay_s)
            finally:
                try:
                    if client.is_connected:
                        await client.stop_notify(self._driver.notify_uuid)
                except Exception:
                    pass
                try:
                    if client.is_connected:
                        await client.disconnect()
                except Exception:
                    pass
                if was_connected:
                    if disconnect_reason is None:
                        disconnect_reason = "shutdown" if self._driver.stop_requested else "connection closed"
                    self._driver.mark_disconnect(self._label, disconnect_reason)
                self._driver.set_device_connected(self._label, False)

    def _handle_notification(self, _sender, data):
        for frame in self._parser.feed(bytes(data)):
            parsed = _parse_measurement_frame(frame)
            if parsed is None:
                continue
            timestamp_ns = time.time_ns()
            self._driver.mark_notify_received(self._label, timestamp_ns)
            if self._driver.session_state.write_sample(
                self._label,
                timestamp_ns,
                parsed,
            ):
                self._driver.increment_sample_count(self._label, timestamp_ns)


class ImuDriver:
    """Persistent BLE collector for multiple WitMotion IMUs."""

    def __init__(self, config=None, logger=None):
        self._cfg = config or {}
        self._log_fn = logger

        self._enabled = bool(self._cfg.get("enabled", False))
        self._devices = self._normalise_devices(self._cfg.get("devices", []))
        self.notify_uuid = self._cfg.get("notify_uuid", NOTIFY_UUID)
        self.write_uuid = self._cfg.get("write_uuid", WRITE_UUID)
        self.sample_rate_hz = int(self._cfg.get("sample_rate_hz", 50))
        self.connect_timeout_s = float(self._cfg.get("connect_timeout_s", 20.0))
        self.reconnect_delay_s = float(self._cfg.get("reconnect_delay_s", 3.0))
        self.connect_stagger_s = float(self._cfg.get("connect_stagger_s", 2.0))
        self.scan_warmup_s = float(self._cfg.get("scan_warmup_s", 10.0))
        self.retry_scan_s = float(self._cfg.get("retry_scan_s", 5.0))
        self.initial_wait_s = float(self._cfg.get("ready_timeout_s", 60.0))

        self._thread = None
        self._loop = None
        self._async_stop = None
        self._connect_lock = None
        self._stop_requested = False
        self._prepared = False
        self._discovered_devices = {}
        self._last_scan_ns = None
        self._last_scan_count = 0

        self._loop_ready = threading.Event()
        self._initial_attempts_done = threading.Event()
        self._state_lock = threading.Lock()
        self._device_states = {
            device["label"]: {
                "mac": device["mac"],
                "connected": False,
                "samples_captured": 0,
                "last_seen_ns": None,
                "last_error": None,
                "last_failure_stage": None,
                "last_disconnect_reason": None,
                "initial_attempted": False,
                "connect_attempts": 0,
                "connect_successes": 0,
                "disconnect_count": 0,
                "last_connect_start_ns": None,
                "last_connect_success_ns": None,
                "last_disconnect_ns": None,
                "last_notify_ns": None,
                "last_notify_before_disconnect_ns": None,
                "last_first_notify_ns": None,
                "last_first_notify_latency_ms": None,
                "awaiting_first_notify": False,
                "current_connection_last_notify_ns": None,
                "recent_events": [],
            }
            for device in self._devices
        }
        self._last_error = None
        self._last_session_counts = {
            label: 0 for label in self._device_states
        }
        self._last_session_dir = None
        self._session_state = _ImuSessionState(self._device_states.keys())

        if not self._devices:
            self._initial_attempts_done.set()

    @property
    def enabled(self):
        return self._enabled

    @property
    def session_state(self):
        return self._session_state

    @property
    def async_stop(self):
        return self._async_stop

    @property
    def stop_requested(self):
        return self._stop_requested

    @property
    def connect_lock(self):
        return self._connect_lock

    def wait_until_initial_attempts_complete(self, timeout_s=None):
        return self._initial_attempts_done.wait(timeout=timeout_s)

    def get_ble_target(self, mac):
        return self._discovered_devices.get(_normalise_mac(mac), mac)

    def should_refresh_scan(self, error_text):
        if BleakScanner is None:
            return False
        if self.retry_scan_s <= 0:
            return False
        return (
            "TimeoutError" in error_text
            or "not found" in error_text.lower()
            or "No matching connection" in error_text
        )

    def prepare(self):
        if not self._enabled:
            return False
        if self._prepared:
            return True
        if BleakClient is None:
            self._last_error = "bleak is not installed"
            self.log("IMU disabled: bleak is not installed")
            return False
        if not self._devices:
            self._last_error = "no IMU devices configured"
            self.log("IMU enabled but no devices are configured")
            return False

        self._stop_requested = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        if not self._loop_ready.wait(timeout=5):
            self._last_error = "failed to start IMU asyncio loop"
            self.log(f"IMU prepare failed: {self._last_error}")
            return False

        self._prepared = True
        self._initial_attempts_done.wait(timeout=self.initial_wait_s)
        self.log(
            f"IMU prepare complete for {len(self._devices)} configured device(s)"
        )
        return True

    def start_session(self, session_dir, session_start_ns):
        if not self._enabled or not self._prepared:
            return False
        out_dir = Path(session_dir) / "imu"
        self._session_state.activate(out_dir, session_start_ns)
        with self._state_lock:
            for label, state in self._device_states.items():
                state["samples_captured"] = 0
                self._append_event_locked(
                    state,
                    "session",
                    "armed",
                    {
                        "session_start_ns": int(session_start_ns),
                        "session_dir": str(out_dir),
                        "label": label,
                    },
                )
        self.log(f"IMU armed for session: {out_dir}")
        return True

    def stop_session(self):
        if not self._enabled:
            return self.get_summary()
        counts, session_dir = self._session_state.deactivate()
        self._last_session_counts = counts
        self._last_session_dir = session_dir
        with self._state_lock:
            for label, state in self._device_states.items():
                self._append_event_locked(
                    state,
                    "session",
                    "stopped",
                    {
                        "samples_captured": counts.get(label, 0),
                        "session_dir": session_dir,
                        "label": label,
                    },
                )
        return self.get_summary()

    def discard_session(self):
        summary = self.stop_session()
        self._last_session_counts = {
            label: 0 for label in self._device_states
        }
        return summary

    def shutdown(self):
        self.stop_session()
        self._stop_requested = True
        if self._loop is not None and self._async_stop is not None:
            try:
                self._loop.call_soon_threadsafe(self._async_stop.set)
            except RuntimeError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
        self._prepared = False
        self._loop = None
        self._async_stop = None

    def get_summary(self):
        with self._state_lock:
            devices = []
            connected_count = 0
            attempted_count = 0
            for label, state in self._device_states.items():
                if state["connected"]:
                    connected_count += 1
                if state["initial_attempted"]:
                    attempted_count += 1
                devices.append({
                    "label": label,
                    "mac": state["mac"],
                    "connected": state["connected"],
                    "samples_captured": self._last_session_counts.get(label, 0),
                    "last_seen_ns": state["last_seen_ns"],
                    "last_error": state["last_error"],
                    "last_failure_stage": state["last_failure_stage"],
                    "last_disconnect_reason": state["last_disconnect_reason"],
                    "initial_attempted": state["initial_attempted"],
                    "connect_attempts": state["connect_attempts"],
                    "connect_successes": state["connect_successes"],
                    "disconnect_count": state["disconnect_count"],
                    "last_connect_start_ns": state["last_connect_start_ns"],
                    "last_connect_success_ns": state["last_connect_success_ns"],
                    "last_disconnect_ns": state["last_disconnect_ns"],
                    "last_notify_ns": state["last_notify_ns"],
                    "last_notify_before_disconnect_ns": state["last_notify_before_disconnect_ns"],
                    "last_first_notify_ns": state["last_first_notify_ns"],
                    "last_first_notify_latency_ms": state["last_first_notify_latency_ms"],
                    "recent_events": list(state["recent_events"]),
                })
        return {
            "enabled": self._enabled,
            "prepared": self._prepared,
            "recorded": any(self._last_session_counts.values()),
            "subdir": "imu",
            "session_dir": self._last_session_dir,
            "sample_rate_hz": self.sample_rate_hz,
            "notify_uuid": self.notify_uuid,
            "write_uuid": self.write_uuid,
            "devices_total": len(self._device_states),
            "devices_connected": connected_count,
            "devices_initial_attempted": attempted_count,
            "scan_warmup_s": self.scan_warmup_s,
            "retry_scan_s": self.retry_scan_s,
            "last_scan_ns": self._last_scan_ns,
            "scan_cache_size": self._last_scan_count,
            "error": self._last_error,
            "devices": devices,
        }

    def set_device_connected(self, label, connected):
        with self._state_lock:
            state = self._device_states[label]
            state["connected"] = connected

    def set_device_error(self, label, error, stage=None):
        with self._state_lock:
            state = self._device_states[label]
            state["last_error"] = error
            if stage is not None:
                state["last_failure_stage"] = stage
            self._append_event_locked(
                state,
                stage or "runtime",
                "error",
                {
                    "error": error,
                    "attempt": state["connect_attempts"],
                },
            )
        self.log(f"IMU {label}: {error}")

    def clear_device_error(self, label):
        with self._state_lock:
            self._device_states[label]["last_error"] = None

    def record_device_event(self, label, stage, event, extra=None, ts_ns=None):
        with self._state_lock:
            state = self._device_states[label]
            self._append_event_locked(state, stage, event, extra, ts_ns)

    def _append_event_locked(self, state, stage, event, extra=None, ts_ns=None):
        payload = {
            "ts_ns": int(time.time_ns() if ts_ns is None else ts_ns),
            "stage": stage,
            "event": event,
        }
        if extra:
            payload.update(extra)
        state["recent_events"].append(payload)
        if len(state["recent_events"]) > 25:
            del state["recent_events"][:-25]

    def mark_connect_attempt(self, label):
        with self._state_lock:
            state = self._device_states[label]
            state["connect_attempts"] += 1
            now_ns = time.time_ns()
            state["last_connect_start_ns"] = now_ns
            state["awaiting_first_notify"] = False
            state["current_connection_last_notify_ns"] = None
            self._append_event_locked(
                state,
                "connect",
                "attempt",
                {"attempt": state["connect_attempts"]},
                now_ns,
            )

    def mark_connect_success(self, label):
        with self._state_lock:
            state = self._device_states[label]
            state["connect_successes"] += 1
            now_ns = time.time_ns()
            state["last_connect_success_ns"] = now_ns
            state["last_failure_stage"] = None
            state["awaiting_first_notify"] = True
            state["current_connection_last_notify_ns"] = None
            state["last_first_notify_ns"] = None
            state["last_first_notify_latency_ms"] = None
            self._append_event_locked(
                state,
                "connect",
                "success",
                {"attempt": state["connect_attempts"]},
                now_ns,
            )

    def mark_disconnect(self, label, reason=None):
        with self._state_lock:
            state = self._device_states[label]
            state["disconnect_count"] += 1
            now_ns = time.time_ns()
            state["last_disconnect_ns"] = now_ns
            state["last_disconnect_reason"] = reason
            state["last_notify_before_disconnect_ns"] = state["current_connection_last_notify_ns"]
            state["awaiting_first_notify"] = False
            state["current_connection_last_notify_ns"] = None
            self._append_event_locked(
                state,
                "disconnect",
                "closed",
                {
                    "reason": reason,
                    "last_notify_before_disconnect_ns": state["last_notify_before_disconnect_ns"],
                },
                now_ns,
            )

    def mark_notify_received(self, label, timestamp_ns):
        with self._state_lock:
            state = self._device_states[label]
            state["last_notify_ns"] = timestamp_ns
            state["current_connection_last_notify_ns"] = timestamp_ns
            if state["awaiting_first_notify"]:
                state["awaiting_first_notify"] = False
                state["last_first_notify_ns"] = timestamp_ns
                latency_ms = None
                if state["last_connect_success_ns"] is not None:
                    latency_ms = round(
                        (timestamp_ns - state["last_connect_success_ns"]) / 1_000_000.0,
                        3,
                    )
                state["last_first_notify_latency_ms"] = latency_ms
                self._append_event_locked(
                    state,
                    "notify",
                    "first_frame",
                    {
                        "attempt": state["connect_attempts"],
                        "latency_ms": latency_ms,
                    },
                    timestamp_ns,
                )

    def increment_sample_count(self, label, timestamp_ns):
        with self._state_lock:
            state = self._device_states[label]
            state["samples_captured"] += 1
            state["last_seen_ns"] = timestamp_ns

    def mark_initial_attempt(self, label):
        with self._state_lock:
            self._device_states[label]["initial_attempted"] = True
            ready = all(
                state["initial_attempted"] for state in self._device_states.values()
            )
        if ready:
            self._initial_attempts_done.set()

    def log(self, msg):
        if self._log_fn is not None:
            self._log_fn(msg)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._async_stop = asyncio.Event()
        self._connect_lock = asyncio.Lock()
        self._loop_ready.set()
        try:
            self._loop.run_until_complete(self._async_main())
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _async_main(self):
        await self.refresh_scan_cache(self.scan_warmup_s)

        tasks = []
        for idx, device in enumerate(self._devices):
            runner = _ImuDeviceRunner(
                self,
                device["label"],
                device["mac"],
                initial_delay_s=idx * self.connect_stagger_s,
            )
            tasks.append(asyncio.create_task(runner.run()))

        if not tasks:
            self._initial_attempts_done.set()
            await self._async_stop.wait()
            return

        await asyncio.gather(*tasks, return_exceptions=True)

    async def refresh_scan_cache(self, timeout_s=None):
        timeout_s = float(self.scan_warmup_s if timeout_s is None else timeout_s)
        if BleakScanner is None or timeout_s <= 0:
            return 0

        async with self._connect_lock:
            try:
                self.log(f"IMU scan start: {timeout_s:.1f}s")
                devices = await BleakScanner.discover(timeout=timeout_s)
                indexed = {}
                for device in devices:
                    mac = _normalise_mac(getattr(device, "address", ""))
                    if mac:
                        indexed[mac] = device
                self._discovered_devices = indexed
                self._last_scan_ns = time.time_ns()
                self._last_scan_count = len(indexed)
                self.log(
                    f"IMU scan complete: cached {self._last_scan_count} device(s)"
                )
                return self._last_scan_count
            except Exception as exc:
                self.log(f"IMU scan failed: {_format_exception(exc)}")
                return 0

    @staticmethod
    def _normalise_devices(devices):
        normalised = []
        for idx, item in enumerate(devices, start=1):
            label = item.get("label") or f"imu{idx:02d}"
            mac = _normalise_mac(item.get("mac"))
            if not mac:
                continue
            normalised.append({"label": label, "mac": mac})
        return normalised