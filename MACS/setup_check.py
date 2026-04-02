#!/usr/bin/env python3
"""
setup_check.py
--------------
System environment and device connectivity checker for MACS.

Checks performed:
  1. Python version and required packages
  2. NYX650 (ToF) camera - ScepterSDK availability and device probe
  3. TB4117 (Thermal) camera - V4L2 device enumeration and OpenCV probe
  4. USB device listing
  5. Disk space availability
"""

import sys
import os
import shutil
import subprocess
import importlib
from pathlib import Path


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

class CheckResult:
    """Holds the outcome of a single diagnostic check."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"

    def __init__(self, name, status, message=""):
        self.name = name
        self.status = status
        self.message = message

    def __str__(self):
        icons = {self.PASS: "[+]", self.WARN: "[!]", self.FAIL: "[-]"}
        line = f"  {icons[self.status]} {self.name}: {self.status}"
        if self.message:
            line += f" -- {self.message}"
        return line


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

class SystemChecker:
    """Runs all system checks and prints a summary report."""

    # Known search paths for ScepterSDK Python API
    SDK_SEARCH_PATHS = [
        os.path.expanduser("~/ScepterSDK/MultilanguageSDK/Python"),
        "/opt/ScepterSDK/MultilanguageSDK/Python",
    ]

    # Python packages required by MACS
    REQUIRED_PACKAGES = {
        "cv2":   "opencv-python",
        "numpy": "numpy",
        "PyQt5": "PyQt5",
        "yaml":  "PyYAML",
    }

    def __init__(self):
        self.results = []

    # -- helpers -------------------------------------------------------------

    def _add(self, result):
        self.results.append(result)
        print(result)

    @staticmethod
    def _run_cmd(cmd, timeout=5):
        """Run a shell command and return (returncode, stdout)."""
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return proc.returncode, proc.stdout
        except FileNotFoundError:
            return -1, ""
        except subprocess.TimeoutExpired:
            return -2, ""

    # -- individual checks ---------------------------------------------------

    def check_python_version(self):
        v = sys.version_info
        if v.major >= 3 and v.minor >= 8:
            self._add(CheckResult(
                "Python version", CheckResult.PASS,
                f"{v.major}.{v.minor}.{v.micro}"
            ))
        else:
            self._add(CheckResult(
                "Python version", CheckResult.FAIL,
                f"{v.major}.{v.minor}.{v.micro} (need >= 3.8)"
            ))

    def check_packages(self):
        for imp_name, pip_name in self.REQUIRED_PACKAGES.items():
            try:
                mod = importlib.import_module(imp_name)
                ver = getattr(mod, "__version__", "unknown")
                self._add(CheckResult(
                    f"Package {pip_name}", CheckResult.PASS, f"v{ver}"
                ))
            except ImportError:
                self._add(CheckResult(
                    f"Package {pip_name}", CheckResult.FAIL,
                    f"not found  ->  pip install {pip_name}"
                ))

    # -- NYX650 --------------------------------------------------------------

    def check_nyx650_sdk(self):
        """Locate and try to import the Scepter Python API."""
        api_dir = None
        for p in self.SDK_SEARCH_PATHS:
            if os.path.isdir(p):
                api_dir = p
                break

        if api_dir is None:
            self._add(CheckResult(
                "NYX650 SDK path", CheckResult.FAIL,
                "ScepterSDK Python API directory not found in known paths"
            ))
            return

        self._add(CheckResult(
            "NYX650 SDK path", CheckResult.PASS, api_dir
        ))

        # Attempt import
        if api_dir not in sys.path:
            sys.path.insert(0, api_dir)

        import_names = ["API.ScepterDS_api"]
        imported = False
        for name in import_names:
            try:
                importlib.import_module(name)
                self._add(CheckResult(
                    "NYX650 SDK import", CheckResult.PASS,
                    f"module '{name}' importable"
                ))
                imported = True
                break
            except Exception:
                continue

        if not imported:
            self._add(CheckResult(
                "NYX650 SDK import", CheckResult.WARN,
                "directory exists but none of the known modules could be imported"
            ))

    def check_nyx650_device(self):
        """Quick heuristic: look for Vzense / Scepter in lsusb output."""
        rc, stdout = self._run_cmd(["lsusb"])
        if rc != 0:
            self._add(CheckResult(
                "NYX650 USB probe", CheckResult.WARN,
                "lsusb unavailable"
            ))
            return

        keywords = ["vzense", "scepter", "nyx"]
        lines = stdout.strip().splitlines()
        matches = [
            l for l in lines
            if any(k in l.lower() for k in keywords)
        ]
        if matches:
            self._add(CheckResult(
                "NYX650 USB probe", CheckResult.PASS,
                matches[0].strip()
            ))
        else:
            self._add(CheckResult(
                "NYX650 USB probe", CheckResult.WARN,
                "no Vzense/Scepter device found in lsusb "
                "(camera may use a generic descriptor)"
            ))

    # -- TB4117 --------------------------------------------------------------

    def check_tb4117_v4l2(self):
        """Enumerate /dev/video* and probe with v4l2-ctl."""
        video_devs = sorted(Path("/dev").glob("video*"))
        if not video_devs:
            self._add(CheckResult(
                "V4L2 devices", CheckResult.FAIL,
                "no /dev/video* found"
            ))
            return

        self._add(CheckResult(
            "V4L2 devices", CheckResult.PASS,
            f"{len(video_devs)} device(s): "
            + ", ".join(d.name for d in video_devs)
        ))

        # Probe each device
        for dev in video_devs:
            rc, stdout = self._run_cmd(["v4l2-ctl", "-d", str(dev), "--info"])
            if rc == -1:
                self._add(CheckResult(
                    "v4l2-ctl", CheckResult.WARN,
                    "not installed  ->  sudo apt install v4l-utils"
                ))
                break
            if rc == 0:
                card = ""
                for line in stdout.splitlines():
                    if "Card type" in line:
                        card = line.split(":", 1)[-1].strip()
                        break
                self._add(CheckResult(
                    f"  {dev.name}", CheckResult.PASS, card or "(no card name)"
                ))

    def check_tb4117_opencv(self):
        """Try opening each /dev/video* with OpenCV and report resolution."""
        try:
            import cv2
        except ImportError:
            self._add(CheckResult(
                "TB4117 OpenCV probe", CheckResult.WARN,
                "opencv-python not installed, skipping"
            ))
            return

        video_devs = sorted(Path("/dev").glob("video*"))
        for dev in video_devs:
            idx = int(str(dev).replace("/dev/video", ""))
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                cap.release()
                self._add(CheckResult(
                    f"  {dev.name} (OpenCV)", CheckResult.PASS,
                    f"{w}x{h} @ {fps:.1f} fps"
                ))
            else:
                cap.release()
                self._add(CheckResult(
                    f"  {dev.name} (OpenCV)", CheckResult.WARN,
                    "could not open"
                ))

    # -- USB -----------------------------------------------------------------

    def check_usb_devices(self):
        rc, stdout = self._run_cmd(["lsusb"])
        if rc != 0:
            self._add(CheckResult(
                "USB enumeration", CheckResult.WARN,
                "lsusb not available"
            ))
            return

        lines = stdout.strip().splitlines()
        self._add(CheckResult(
            "USB enumeration", CheckResult.PASS,
            f"{len(lines)} device(s)"
        ))
        for line in lines:
            print(f"        {line.strip()}")

    # -- Disk ----------------------------------------------------------------

    def check_disk_space(self):
        paths_to_check = ["data", os.path.expanduser("~")]
        checked = set()

        for path in paths_to_check:
            real = os.path.realpath(path) if os.path.exists(path) else None
            if real is None:
                continue
            mount = os.path.dirname(real) if not os.path.isdir(real) else real
            if mount in checked:
                continue
            checked.add(mount)

            usage = shutil.disk_usage(mount)
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            if free_gb >= 10:
                status = CheckResult.PASS
            elif free_gb >= 2:
                status = CheckResult.WARN
            else:
                status = CheckResult.FAIL
            self._add(CheckResult(
                f"Disk ({mount})", status,
                f"{free_gb:.1f} GB free / {total_gb:.1f} GB total"
            ))

        # Scan common external mount points
        for base in ("/media", "/mnt"):
            if not os.path.isdir(base):
                continue
            for entry in os.listdir(base):
                mp = os.path.join(base, entry)
                if os.path.ismount(mp) and mp not in checked:
                    checked.add(mp)
                    usage = shutil.disk_usage(mp)
                    free_gb = usage.free / (1024 ** 3)
                    total_gb = usage.total / (1024 ** 3)
                    self._add(CheckResult(
                        f"External ({mp})", CheckResult.PASS,
                        f"{free_gb:.1f} GB free / {total_gb:.1f} GB total"
                    ))

    # -- runner --------------------------------------------------------------

    def run_all(self):
        sep = "=" * 64
        print(sep)
        print("  MACS  -  System & Device Check")
        print(sep)

        print("\n[Python Environment]")
        self.check_python_version()
        self.check_packages()

        print("\n[NYX650 ToF Camera]")
        self.check_nyx650_sdk()
        self.check_nyx650_device()

        print("\n[TB4117 Thermal Camera (V4L2)]")
        self.check_tb4117_v4l2()
        self.check_tb4117_opencv()

        print("\n[USB Devices]")
        self.check_usb_devices()

        print("\n[Storage]")
        self.check_disk_space()

        # Summary
        passes = sum(1 for r in self.results if r.status == CheckResult.PASS)
        warns  = sum(1 for r in self.results if r.status == CheckResult.WARN)
        fails  = sum(1 for r in self.results if r.status == CheckResult.FAIL)
        total  = len(self.results)

        print(f"\n{sep}")
        print(f"  Summary:  {passes}/{total} PASS,  {warns} WARN,  {fails} FAIL")
        if fails:
            print("  Verdict:  NOT READY  -- fix FAIL items before running MACS")
        elif warns:
            print("  Verdict:  READY (with warnings)")
        else:
            print("  Verdict:  ALL CLEAR")
        print(sep)

        return fails == 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    checker = SystemChecker()
    ok = checker.run_all()
    sys.exit(0 if ok else 1)