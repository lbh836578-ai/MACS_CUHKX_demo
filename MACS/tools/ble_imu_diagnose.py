#!/usr/bin/env python3
"""
ble_imu_diagnose.py
-------------------
Standalone BLE diagnostics for the configured WitMotion IMUs.

The script does not touch the MACS recording/session pipeline. For each
configured IMU it performs a sequential diagnostic flow:

1. Global BLE scan to see whether the MAC is advertising.
2. Connect to the device.
3. Resolve GATT services and verify the configured characteristics.
4. Write the sample-rate command.
5. Start notifications for a short window and count received frames.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    BleakClient = None
    BleakScanner = None


DEFAULT_NOTIFY_UUID = "0000ffe4-0000-1000-8000-00805f9a34fb"
DEFAULT_WRITE_UUID = "0000ffe9-0000-1000-8000-00805f9a34fb"


def load_config(path):
    path = Path(path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    with open(path, "r") as handle:
        return yaml.safe_load(handle) or {}


def normalise_mac(mac):
    return (mac or "").strip().upper()


def format_exception(exc):
    text = str(exc).strip()
    if not text:
        text = exc.__class__.__name__
    if "org.bluez.Error.InProgress" in text:
        text += " (BlueZ is already handling another BLE operation)"
    return text


def rate_command(sample_rate_hz):
    mapping = {
        10: 0x06,
        20: 0x07,
        50: 0x08,
        100: 0x09,
        200: 0x0A,
    }
    code = mapping.get(int(sample_rate_hz), 0x08)
    return bytes([0xFF, 0xAA, 0x03, code, 0x00])


def parse_measurement_frame(frame):
    if len(frame) != 20 or frame[0] != 0x55 or frame[1] != 0x61:
        return None
    return True


class Wt901StreamParser:
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


class NotifyProbe:
    def __init__(self):
        self.callback_count = 0
        self.frame_count = 0
        self.raw_bytes = 0
        self.first_notification_ns = None
        self.last_notification_ns = None
        self._parser = Wt901StreamParser()

    def handle(self, _sender, data):
        payload = bytes(data)
        self.callback_count += 1
        self.raw_bytes += len(payload)
        now_ns = time.time_ns()
        if self.first_notification_ns is None:
            self.first_notification_ns = now_ns
        self.last_notification_ns = now_ns

        for frame in self._parser.feed(payload):
            if parse_measurement_frame(frame):
                self.frame_count += 1


def extract_imu_devices(config, selected_labels):
    imu_cfg = ((config or {}).get("multimodal") or {}).get("imu") or {}
    wanted = {label.strip() for label in selected_labels if label.strip()}
    devices = []

    for index, item in enumerate(imu_cfg.get("devices", []), start=1):
        label = item.get("label") or f"imu{index:02d}"
        if wanted and label not in wanted:
            continue
        mac = normalise_mac(item.get("mac"))
        if not mac:
            continue
        devices.append({"label": label, "mac": mac})

    return imu_cfg, devices


def build_scan_index(scan_devices):
    indexed = {}
    for device in scan_devices:
        indexed[normalise_mac(getattr(device, "address", ""))] = {
            "name": getattr(device, "name", None),
            "address": getattr(device, "address", None),
            "rssi": getattr(device, "rssi", None),
            "details": str(getattr(device, "details", "")) or None,
        }
    return indexed


async def resolve_services(client):
    if hasattr(client, "get_services"):
        services = await client.get_services()
    else:
        services = client.services

    if hasattr(services, "services"):
        return list(services.services.values())
    return list(services)


async def diagnose_device(device, scan_index, notify_uuid, write_uuid, sample_rate_hz,
                          connect_timeout_s, notify_window_s, disconnect_wait_s):
    label = device["label"]
    mac = normalise_mac(device["mac"])
    result = {
        "label": label,
        "mac": mac,
        "scan_seen": mac in scan_index,
        "scan_name": None,
        "scan_rssi": None,
        "scan_details": None,
        "service_uuids": [],
        "characteristic_uuids": [],
        "notify_properties": None,
        "write_properties": None,
        "connect_ok": False,
        "services_ok": False,
        "notify_char_found": False,
        "write_char_found": False,
        "write_ok": False,
        "notify_ok": False,
        "notification_callbacks": 0,
        "measurement_frames": 0,
        "raw_notify_bytes": 0,
        "connect_elapsed_s": None,
        "notify_window_s": notify_window_s,
        "step_errors": [],
        "error": None,
    }

    if result["scan_seen"]:
        result.update({
            "scan_name": scan_index[mac].get("name"),
            "scan_rssi": scan_index[mac].get("rssi"),
            "scan_details": scan_index[mac].get("details"),
        })

    probe = NotifyProbe()
    client = BleakClient(mac, timeout=connect_timeout_s)
    notify_started = False
    start_ts = time.monotonic()

    try:
        print(f"[connect] {label} {mac}")
        await client.connect()
        result["connect_elapsed_s"] = round(time.monotonic() - start_ts, 3)
        if not client.is_connected:
            raise RuntimeError("BLE connect returned without an active link")
        result["connect_ok"] = True

        services = await resolve_services(client)
        characteristics = {}
        for service in services:
            result["service_uuids"].append(service.uuid)
            for characteristic in service.characteristics:
                characteristics[characteristic.uuid.lower()] = list(
                    characteristic.properties
                )

        result["characteristic_uuids"] = sorted(characteristics.keys())

        notify_props = characteristics.get(notify_uuid.lower())
        write_props = characteristics.get(write_uuid.lower())
        result["notify_properties"] = notify_props
        result["write_properties"] = write_props
        result["notify_char_found"] = notify_props is not None
        result["write_char_found"] = write_props is not None
        result["services_ok"] = result["notify_char_found"] and result["write_char_found"]

        if not result["services_ok"]:
            missing = []
            if not result["notify_char_found"]:
                missing.append(f"notify:{notify_uuid}")
            if not result["write_char_found"]:
                missing.append(f"write:{write_uuid}")
            message = "missing expected characteristics: " + ", ".join(missing)
            result["step_errors"].append(message)
            raise RuntimeError(message)

        print(f"[write]   {label} sample_rate={sample_rate_hz}")
        try:
            await client.write_gatt_char(
                write_uuid,
                rate_command(sample_rate_hz),
                response=False,
            )
            result["write_ok"] = True
        except Exception as exc:
            message = "write_gatt_char failed: " + format_exception(exc)
            result["step_errors"].append(message)
            print(f"[warn]    {label} {message}")

        print(f"[notify]  {label} window={notify_window_s:.1f}s")
        try:
            await client.start_notify(notify_uuid, probe.handle)
            notify_started = True
            await asyncio.sleep(notify_window_s)
            result["notification_callbacks"] = probe.callback_count
            result["measurement_frames"] = probe.frame_count
            result["raw_notify_bytes"] = probe.raw_bytes
            result["notify_ok"] = probe.callback_count > 0 and probe.frame_count > 0

            if not result["notify_ok"]:
                result["step_errors"].append(
                    "notify started but no valid measurement frames were received"
                )
        except Exception as exc:
            message = "start_notify failed: " + format_exception(exc)
            result["step_errors"].append(message)

    except Exception as exc:
        result["error"] = format_exception(exc)
    finally:
        if notify_started:
            try:
                await client.stop_notify(notify_uuid)
            except Exception:
                pass
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception:
            pass
        if disconnect_wait_s > 0:
            await asyncio.sleep(disconnect_wait_s)

    if result["error"] is None and result["step_errors"]:
        result["error"] = "; ".join(result["step_errors"])

    return result


async def diagnose_device_concurrent(device, scan_index, notify_uuid, write_uuid,
                                     sample_rate_hz, connect_timeout_s,
                                     notify_window_s, disconnect_wait_s,
                                     connect_lock, initial_delay_s):
    label = device["label"]
    mac = normalise_mac(device["mac"])
    result = {
        "label": label,
        "mac": mac,
        "scan_seen": mac in scan_index,
        "scan_name": None,
        "scan_rssi": None,
        "scan_details": None,
        "service_uuids": [],
        "characteristic_uuids": [],
        "notify_properties": None,
        "write_properties": None,
        "connect_ok": False,
        "services_ok": False,
        "notify_char_found": False,
        "write_char_found": False,
        "write_ok": False,
        "notify_ok": False,
        "notification_callbacks": 0,
        "measurement_frames": 0,
        "raw_notify_bytes": 0,
        "connect_elapsed_s": None,
        "notify_window_s": notify_window_s,
        "step_errors": [],
        "error": None,
    }

    if result["scan_seen"]:
        result.update({
            "scan_name": scan_index[mac].get("name"),
            "scan_rssi": scan_index[mac].get("rssi"),
            "scan_details": scan_index[mac].get("details"),
        })

    if initial_delay_s > 0:
        await asyncio.sleep(initial_delay_s)

    probe = NotifyProbe()
    client = BleakClient(mac, timeout=connect_timeout_s)
    notify_started = False
    start_ts = time.monotonic()

    try:
        print(f"[connect-concurrent] {label} {mac}")
        async with connect_lock:
            await client.connect()
            result["connect_elapsed_s"] = round(time.monotonic() - start_ts, 3)
            if not client.is_connected:
                raise RuntimeError("BLE connect returned without an active link")
            result["connect_ok"] = True

            services = await resolve_services(client)
            characteristics = {}
            for service in services:
                result["service_uuids"].append(service.uuid)
                for characteristic in service.characteristics:
                    characteristics[characteristic.uuid.lower()] = list(
                        characteristic.properties
                    )

            result["characteristic_uuids"] = sorted(characteristics.keys())
            notify_props = characteristics.get(notify_uuid.lower())
            write_props = characteristics.get(write_uuid.lower())
            result["notify_properties"] = notify_props
            result["write_properties"] = write_props
            result["notify_char_found"] = notify_props is not None
            result["write_char_found"] = write_props is not None
            result["services_ok"] = (
                result["notify_char_found"] and result["write_char_found"]
            )

            if not result["services_ok"]:
                missing = []
                if not result["notify_char_found"]:
                    missing.append(f"notify:{notify_uuid}")
                if not result["write_char_found"]:
                    missing.append(f"write:{write_uuid}")
                message = "missing expected characteristics: " + ", ".join(missing)
                result["step_errors"].append(message)
                raise RuntimeError(message)

            try:
                await client.write_gatt_char(
                    write_uuid,
                    rate_command(sample_rate_hz),
                    response=False,
                )
                result["write_ok"] = True
            except Exception as exc:
                message = "write_gatt_char failed: " + format_exception(exc)
                result["step_errors"].append(message)
                print(f"[warn]               {label} {message}")

            await client.start_notify(notify_uuid, probe.handle)
            notify_started = True

        print(f"[hold]               {label} window={notify_window_s:.1f}s")
        await asyncio.sleep(notify_window_s)
        result["notification_callbacks"] = probe.callback_count
        result["measurement_frames"] = probe.frame_count
        result["raw_notify_bytes"] = probe.raw_bytes
        result["notify_ok"] = probe.callback_count > 0 and probe.frame_count > 0
        if not result["notify_ok"]:
            result["step_errors"].append(
                "notify started but no valid measurement frames were received"
            )

    except Exception as exc:
        result["error"] = format_exception(exc)
    finally:
        if notify_started:
            try:
                await client.stop_notify(notify_uuid)
            except Exception:
                pass
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception:
            pass
        if disconnect_wait_s > 0:
            await asyncio.sleep(disconnect_wait_s)

    if result["error"] is None and result["step_errors"]:
        result["error"] = "; ".join(result["step_errors"])

    return result


async def async_main(args):
    if BleakClient is None or BleakScanner is None:
        raise RuntimeError("bleak is not installed; run pip install bleak")

    config = load_config(args.config)
    imu_cfg, devices = extract_imu_devices(config, args.device)
    if not devices:
        raise RuntimeError("no IMU devices found in config for the requested selection")

    notify_uuid = imu_cfg.get("notify_uuid", DEFAULT_NOTIFY_UUID)
    write_uuid = imu_cfg.get("write_uuid", DEFAULT_WRITE_UUID)
    sample_rate_hz = int(imu_cfg.get("sample_rate_hz", 50))
    connect_timeout_s = float(args.connect_timeout or imu_cfg.get("connect_timeout_s", 15.0))

    print(f"[scan]    discovering for {args.scan_seconds:.1f}s")
    scan_devices = await BleakScanner.discover(timeout=args.scan_seconds)
    scan_index = build_scan_index(scan_devices)

    if args.mode == "sequential":
        results = []
        for device in devices:
            results.append(
                await diagnose_device(
                    device=device,
                    scan_index=scan_index,
                    notify_uuid=notify_uuid,
                    write_uuid=write_uuid,
                    sample_rate_hz=sample_rate_hz,
                    connect_timeout_s=connect_timeout_s,
                    notify_window_s=args.notify_seconds,
                    disconnect_wait_s=args.disconnect_wait,
                )
            )
    else:
        connect_lock = asyncio.Lock()
        tasks = []
        for idx, device in enumerate(devices):
            tasks.append(asyncio.create_task(
                diagnose_device_concurrent(
                    device=device,
                    scan_index=scan_index,
                    notify_uuid=notify_uuid,
                    write_uuid=write_uuid,
                    sample_rate_hz=sample_rate_hz,
                    connect_timeout_s=connect_timeout_s,
                    notify_window_s=args.notify_seconds,
                    disconnect_wait_s=args.disconnect_wait,
                    connect_lock=connect_lock,
                    initial_delay_s=idx * args.connect_stagger,
                )
            ))
        results = await asyncio.gather(*tasks)

    ok_connect = sum(1 for item in results if item["connect_ok"])
    ok_notify = sum(1 for item in results if item["notify_ok"])
    summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": args.mode,
        "scan_seconds": args.scan_seconds,
        "notify_seconds": args.notify_seconds,
        "disconnect_wait": args.disconnect_wait,
        "connect_stagger": args.connect_stagger,
        "connect_timeout_s": connect_timeout_s,
        "notify_uuid": notify_uuid,
        "write_uuid": write_uuid,
        "sample_rate_hz": sample_rate_hz,
        "devices_requested": len(devices),
        "devices_scan_seen": sum(1 for item in results if item["scan_seen"]),
        "devices_connect_ok": ok_connect,
        "devices_notify_ok": ok_notify,
        "results": results,
    }
    return summary


def parse_args():
    parser = argparse.ArgumentParser(
        description="Standalone BLE diagnostics for configured WitMotion IMUs"
    )
    parser.add_argument(
        "--mode",
        choices=["sequential", "concurrent"],
        default="sequential",
        help="sequential: one device at a time; concurrent: connect all devices and hold notify simultaneously",
    )
    parser.add_argument(
        "--config",
        default="config/default.yaml",
        help="Path to MACS YAML config",
    )
    parser.add_argument(
        "--device",
        action="append",
        default=[],
        help="Only diagnose the named IMU label; repeatable",
    )
    parser.add_argument(
        "--scan-seconds",
        type=float,
        default=8.0,
        help="BLE scan duration before connecting",
    )
    parser.add_argument(
        "--notify-seconds",
        type=float,
        default=5.0,
        help="How long to keep notifications enabled per device",
    )
    parser.add_argument(
        "--disconnect-wait",
        type=float,
        default=1.0,
        help="Idle delay after disconnect before the next device",
    )
    parser.add_argument(
        "--connect-stagger",
        type=float,
        default=1.0,
        help="Per-device startup stagger used only in concurrent mode",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=None,
        help="Override connect timeout in seconds",
    )
    parser.add_argument(
        "--output",
        default="data/raw/ble_imu_diagnose_summary.json",
        help="Path to the JSON summary output",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        summary = asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("Interrupted by user", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"BLE diagnose failed: {format_exception(exc)}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as handle:
        json.dump(summary, handle, indent=2)

    print(json.dumps(summary, indent=2))
    print(f"Summary written to {output_path}")
    if summary["devices_notify_ok"] != summary["devices_requested"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())