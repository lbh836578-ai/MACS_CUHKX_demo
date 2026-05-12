#!/usr/bin/env python3
"""
multimodal_smoke_test.py
------------------------
Standalone smoke test for the external MACS modalities (mmWave + IMU).

It does not start the camera UI. Instead it reuses the same session
coordinator that CaptureController uses in production.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from capture.session_coordinator import SessionCoordinator
from runtime_config import apply_runtime_imu_selection


def load_config(path):
    path = Path(path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    with open(path, "r") as fh:
        return yaml.safe_load(fh) or {}


def main():
    parser = argparse.ArgumentParser(
        description="Smoke test mmWave and IMU capture without launching the UI"
    )
    parser.add_argument(
        "--config",
        default="config/default.yaml",
        help="Path to the MACS YAML config",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=15,
        help="Recording duration in seconds",
    )
    parser.add_argument(
        "--output-root",
        default="data/raw",
        help="Root directory for the smoke-test session",
    )
    parser.add_argument(
        "--imu-ready-timeout",
        type=float,
        default=0.0,
        help="Wait for IMU initial connect attempts before recording; 0 disables the wait",
    )
    parser.add_argument(
        "--imu-device",
        action="append",
        default=[],
        help="Only enable the named IMU label; repeat to keep multiple labels",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    apply_runtime_imu_selection(cfg, args.imu_device)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root

    session_dir = output_root / f"session_smoke_{stamp}"

    coordinator = SessionCoordinator(cfg, logger=lambda msg: print(msg))
    prepare_summary = coordinator.prepare()
    print(json.dumps(prepare_summary, indent=2))

    if args.imu_ready_timeout > 0:
        print(
            "Waiting for IMU initial connect attempts "
            f"(timeout={args.imu_ready_timeout:.1f}s)"
        )
        ready = coordinator.wait_for_imu_initial_attempts(args.imu_ready_timeout)
        print(f"IMU initial attempts complete: {ready}")
        print(json.dumps(coordinator.get_summary(), indent=2))

    session_start_ns = time.time_ns()
    coordinator.start_session(session_dir, session_start_ns)
    print(f"Recording external modalities into {session_dir} for {args.duration}s")

    try:
        for second in range(args.duration):
            time.sleep(1)
            print(f"  {second + 1}/{args.duration}s")
    except KeyboardInterrupt:
        print("Interrupted by user")

    summary = coordinator.stop_session()
    coordinator.shutdown()

    meta_path = session_dir / "multimodal_smoke_summary.json"
    session_dir.mkdir(parents=True, exist_ok=True)
    with open(meta_path, "w") as fh:
        json.dump(summary, fh, indent=2)

    print(json.dumps(summary, indent=2))
    print(f"Summary written to {meta_path}")


if __name__ == "__main__":
    main()