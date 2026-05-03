"""
tb4117_driver.py
----------------
Driver for the HikVision TB4117 thermal camera module in **UVC mode**.

Hardware background
~~~~~~~~~~~~~~~~~~~
The TB4117 (DS-2TM01-3XF/TB) is a 160×120 / 256×192 VOx thermal imaging
module.  When set to **UVC mode** (as opposed to NCM/network mode), it
registers as a standard USB video device (VID 2bdf, PID 0101/0102) and
can be accessed via V4L2 / OpenCV like any other webcam.

UVC descriptor (typical)::

    UncompressedFormat(1)  YUY2
        FrameDescriptor(1)  160x120  @25fps
        FrameDescriptor(2)  320x240  @30fps
        FrameDescriptor(3)  640x360  @30fps
    MJPEGFormat(2)  MJPG
        (same sizes)

Detection strategy
~~~~~~~~~~~~~~~~~~
1. Scan ``/sys/bus/usb/devices/*/idVendor`` for ``2bdf`` (HIK Camera).
2. Find the associated ``/dev/videoX`` node.
3. Fallback: match by ``/sys/class/video4linux/videoX/name`` keywords.
4. Fallback: probe all ``/dev/video*`` with OpenCV for target resolution.

Composite frame handling
~~~~~~~~~~~~~~~~~~~~~~~~
Some HIK thermal modules pack multiple sub-images (pseudo-colour thermal,
raw Y16 radiometric, visible-light, etc.) into a single tall UVC frame.
For example, requesting 256×192 may yield a frame of 256×(192*N).  The
driver detects this and crops to the first (pseudo-colour) sub-image.

Usage
~~~~~
Plug the TB4117 via USB, ensure it is in UVC mode, then::

    v4l2-ctl --list-devices          # find /dev/videoX
    v4l2-ctl -d /dev/videoX --all    # verify formats

The driver will handle the rest automatically.
"""

import os
import re
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

from .base_driver import BaseCameraDriver


# ───────────────────────── Constants ─────────────────────────────────────

_HIK_USB_VID = "2bdf"                 # Hikvision / HIKMICRO USB Vendor ID
_HIK_USB_PIDS = ("0101", "0102")      # known thermal module PIDs

_SYSFS_KEYWORDS = (
    "hik", "hikvision", "hikmicro",
    "thermal", "tb4117", "tb-4117",
    "ds-2tm",
)

# Supported FOURCC codes (order is rebuilt at runtime from config)
_FOURCC_SUPPORTED = [
    cv2.VideoWriter_fourcc(*"MJPG"),
    cv2.VideoWriter_fourcc(*"YUYV"),
]


# ─────────────────────────── Helpers ─────────────────────────────────────

def _find_video_node_by_usb_vid(vid=_HIK_USB_VID, pids=_HIK_USB_PIDS):
    """Walk sysfs to find /dev/videoX belonging to the given USB VID:PID.

    Returns
    -------
    int or None
        The ``/dev/video<N>`` index, or ``None`` if not found.
    """
    sysfs_usb = Path("/sys/bus/usb/devices")
    if not sysfs_usb.exists():
        return None

    for dev_dir in sysfs_usb.iterdir():
        vid_file = dev_dir / "idVendor"
        pid_file = dev_dir / "idProduct"
        if not vid_file.exists():
            continue
        try:
            found_vid = vid_file.read_text().strip().lower()
            found_pid = pid_file.read_text().strip().lower() if pid_file.exists() else ""
        except OSError:
            continue

        if found_vid != vid:
            continue
        if pids and found_pid not in pids:
            continue

        # This USB device matches — now find its video4linux child
        for vnode in dev_dir.glob("**/video4linux/video*"):
            name = vnode.name                      # e.g. "video2"
            idx_str = name.replace("video", "")
            if idx_str.isdigit():
                return int(idx_str)

    return None


def _find_video_node_by_name(keywords=_SYSFS_KEYWORDS):
    """Scan /sys/class/video4linux/videoX/name for keyword matches."""
    v4l_dir = Path("/sys/class/video4linux")
    if not v4l_dir.exists():
        return None

    for vdir in sorted(v4l_dir.iterdir()):
        name_file = vdir / "name"
        if not name_file.exists():
            continue
        try:
            card_name = name_file.read_text().strip().lower()
        except OSError:
            continue
        if any(kw in card_name for kw in keywords):
            idx_str = vdir.name.replace("video", "")
            if idx_str.isdigit():
                return int(idx_str)
    return None


def _find_video_node_by_lsusb(vid=_HIK_USB_VID):
    """Use ``lsusb`` output to confirm device presence, then fall back to
    resolution probing."""
    try:
        out = subprocess.check_output(["lsusb"], timeout=5, text=True)
        for line in out.splitlines():
            if vid in line.lower():
                return True     # device is on the bus
    except Exception:
        pass
    return False


def _probe_video_node_by_resolution(target_w, target_h):
    """Open each /dev/video* with OpenCV and check resolution match.

    Also accepts transposed resolution (target_h x target_w) because some
    HikMicro firmware reports the sensor in portrait orientation, i.e.
    the UVC descriptor lists 120x160 when the logical size is 160x120.
    """
    candidates = sorted(Path("/dev").glob("video*"))
    for dev in candidates:
        idx_str = dev.name.replace("video", "")
        if not idx_str.isdigit():
            continue
        idx = int(idx_str)
        try:
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            # Accept exact match, composite, or firmware-transposed orientation
            dims_ok = (
                (w == target_w and (h == target_h or h % target_h == 0))
                or (w == target_h and (h == target_w or h % target_w == 0))
            )
            if dims_ok:
                return idx
        except Exception:
            continue
    return None


def _v4l2_ctl_setup(dev_idx, width, height, fps, pixfmt="YUYV"):
    """Pre-configure the device with ``v4l2-ctl`` before OpenCV opens it.

    This mirrors the bash commands the user previously ran manually.
    Errors are non-fatal — OpenCV will attempt its own negotiation.
    """
    dev = f"/dev/video{dev_idx}"
    cmds = [
        # Set pixel format and resolution
        [
            "v4l2-ctl", "-d", dev,
            "--set-fmt-video",
            f"width={width},height={height},pixelformat={pixfmt}",
        ],
        # Set frame rate
        [
            "v4l2-ctl", "-d", dev,
            "--set-parm", str(fps),
        ],
    ]
    results = []
    for cmd in cmds:
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
            )
            results.append((cmd, r.returncode, r.stderr.strip()))
        except FileNotFoundError:
            results.append((cmd, -1, "v4l2-ctl not found"))
        except Exception as exc:
            results.append((cmd, -1, str(exc)))
    return results


def _query_supported_formats(dev_idx):
    """Query device supported formats via v4l2-ctl.

    Returns
    -------
    str
        Raw text output of ``v4l2-ctl --list-formats-ext``.
    """
    dev = f"/dev/video{dev_idx}"
    try:
        out = subprocess.check_output(
            ["v4l2-ctl", "-d", dev, "--list-formats-ext"],
            timeout=5,
            text=True,
            stderr=subprocess.STDOUT,
        )
        return out
    except Exception:
        return ""


# ─────────────────────────── Driver ──────────────────────────────────────

class TB4117Driver(BaseCameraDriver):
    """Captures thermal frames from a HikVision TB4117 via UVC / V4L2.

    The driver performs multi-strategy auto-detection of the camera device,
    pre-configures it with ``v4l2-ctl`` (if available), opens it with
    OpenCV, and handles composite-frame cropping automatically.
    """

    MODALITIES = ("Thermal",)

    def __init__(self, config=None, parent=None):
        super().__init__(config, parent)
        self._cap = None
        self._device_idx = None
        self._actual_fourcc = None
        self._actual_size = None
        self._selected_request_size = None
        self._frame_debug_logged = 0

        # Parse expected resolution from config
        th_cfg = (config or {}).get("thermal", {})
        self._target_w = th_cfg.get("width", 256)
        self._target_h = th_cfg.get("height", 192)
        self._target_fps = th_cfg.get("fps", 25)
        self._pixfmt = th_cfg.get("pixelformat", "YUYV")
        self._warmup_frames = int(th_cfg.get("warmup_frames", 5))
        self._warmup_sleep_s = float(th_cfg.get("warmup_sleep_s", 0.1))
        self._resolution_candidates = self._build_resolution_candidates(th_cfg)

        # Composite-frame cropping state
        self._crop_h = None   # determined on first frame

    # ================================================================
    #  Auto-detection  (multi-strategy)
    # ================================================================

    def _auto_detect(self):
        """Return /dev/video<N> index for the TB4117, or None.

        Strategy order:
          1. USB sysfs VID:PID match
          2. sysfs video4linux name match
          3. Resolution probe (OpenCV)
        """
        # Strategy 1 — USB VID:PID via sysfs
        idx = _find_video_node_by_usb_vid()
        if idx is not None:
            self._log(f"Detected TB4117 via USB VID:PID → /dev/video{idx}")
            return idx

        # Strategy 2 — sysfs card name
        idx = _find_video_node_by_name()
        if idx is not None:
            self._log(f"Detected TB4117 via sysfs name → /dev/video{idx}")
            return idx

        # Strategy 3 — Resolution probe
        idx = _probe_video_node_by_resolution(
            self._target_w, self._target_h,
        )
        if idx is not None:
            self._log(f"Detected TB4117 via resolution probe → /dev/video{idx}")
            return idx

        return None

    # ================================================================
    #  Device lifecycle
    # ================================================================

    def connect_device(self):
        cfg_idx = self._cfg.get("device_index", -1)

        if cfg_idx >= 0:
            self._device_idx = cfg_idx
        else:
            self._device_idx = self._auto_detect()
            if self._device_idx is None:
                # Last resort: check if the USB device exists at all
                if _find_video_node_by_lsusb():
                    raise RuntimeError(
                        "TB4117 USB device detected on bus but no "
                        "/dev/video* node found.  Is uvcvideo loaded?  "
                        "Try: sudo modprobe uvcvideo"
                    )
                raise RuntimeError(
                    "TB4117 not found.  Ensure the module is in UVC mode "
                    "(not NCM) and connected via USB.  "
                    "Run: lsusb | grep 2bdf"
                )

        # --- Query supported formats (informational) -------------------
        fmt_info = _query_supported_formats(self._device_idx)
        if fmt_info:
            self._log(f"Supported formats for /dev/video{self._device_idx}:\n"
                       f"{fmt_info[:500]}")

        # --- Pre-configure with v4l2-ctl --------------------------------
        results = _v4l2_ctl_setup(
            self._device_idx,
            self._target_w,
            self._target_h,
            self._target_fps,
            self._pixfmt,
        )
        for cmd, rc, err in results:
            cmd_str = " ".join(cmd)
            if rc == 0:
                self._log(f"v4l2-ctl OK: {cmd_str}")
            else:
                self._log(f"v4l2-ctl WARN (rc={rc}): {cmd_str}  {err}")

        # --- Open with OpenCV and probe content -------------------------
        cap, meta = self._open_capture_with_best_format()
        actual_w = meta["width"]
        actual_h = meta["height"]
        actual_fps = meta["fps"]
        fourcc_str = meta["fourcc"]
        self._actual_fourcc = fourcc_str
        self._actual_size = (actual_w, actual_h)
        self._selected_request_size = (
            int(meta.get("requested_width", actual_w)),
            int(meta.get("requested_height", actual_h)),
        )
        self._frame_debug_logged = 0

        self._log(
            f"Opened /dev/video{self._device_idx}: "
            f"{actual_w}x{actual_h} @{actual_fps:.1f}fps  FOURCC={fourcc_str}"
        )
        requested_w = meta.get("requested_width")
        requested_h = meta.get("requested_height")
        if requested_w is not None and requested_h is not None:
            self._log(
                f"Selected request profile: {requested_w}x{requested_h} "
                f"requested={meta.get('requested_fourcc', fourcc_str)}"
            )
        if meta.get("sample_stats"):
            self._log(
                "Initial sample stats: " + meta["sample_stats"]
            )

        # Detect composite-frame scenario
        expected_h = self._selected_request_size[1]
        if actual_h > expected_h and actual_h % expected_h == 0:
            n = actual_h // expected_h
            self._crop_h = expected_h
            self._log(
                f"Composite frame detected: {n} sub-images stacked.  "
                f"Will crop to top {actual_w}x{self._crop_h}"
            )
        elif actual_h != expected_h:
            # Non-standard height — use whatever the camera gives
            self._crop_h = None
            self._log(
                f"NOTE: actual height {actual_h} differs from target "
                f"{expected_h}.  Using full frame."
            )
        else:
            self._crop_h = None

        self._cap = cap

    def disconnect_device(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    # ================================================================
    #  Capture loop
    # ================================================================

    def _reopen_cap(self):
        """Release and re-open VideoCapture after a USB disconnect.

        Returns True on success, False if the device cannot be re-opened.
        The uvcvideo kernel driver needs ~1 s to re-enumerate after a
        "Failed to resubmit video URB" event.
        """
        self._log("Attempting to reopen device after read failure...")
        try:
            if self._cap is not None:
                self._cap.release()
                self._cap = None
        except Exception:
            pass

        for attempt in range(1, 6):          # up to 5 retries, 1 s apart
            time.sleep(1.0)
            try:
                cap, meta = self._open_capture_with_best_format()
                self._cap = cap
                self._actual_fourcc = meta["fourcc"]
                self._actual_size = (meta["width"], meta["height"])
                self._selected_request_size = (
                    int(meta.get("requested_width", meta["width"])),
                    int(meta.get("requested_height", meta["height"])),
                )
                self._frame_debug_logged = 0
                self._log(
                    f"Reopen succeeded on attempt {attempt}: "
                    f"{meta['width']}x{meta['height']} @{meta['fps']:.1f}fps "
                    f"FOURCC={meta['fourcc']}"
                )
                if meta.get("sample_stats"):
                    self._log("Reconnect sample stats: " + meta["sample_stats"])
                return True
            except Exception as exc:
                self._log(f"Reopen attempt {attempt}/5 exception: {exc}")

        self._log("All reopen attempts exhausted")
        return False

    def _capture_loop(self):
        consecutive_failures = 0
        _MAX_FAILURES = 30      # ~0.15 s at normal pace before trying reopen
        _MAX_RECONNECTS = 3
        reconnects = 0

        while self._running:
            ret, frame = self._cap.read()
            ts = time.time_ns()

            if not ret or frame is None:
                consecutive_failures += 1
                if consecutive_failures >= _MAX_FAILURES:
                    if reconnects < _MAX_RECONNECTS:
                        reconnects += 1
                        self._log(
                            f"USB read failure threshold reached — reconnect "
                            f"attempt {reconnects}/{_MAX_RECONNECTS}"
                        )
                        if self._reopen_cap():
                            consecutive_failures = 0
                            continue
                    self.error_occurred.emit(
                        "TB4117: too many consecutive read failures "
                        f"(/dev/video{self._device_idx})"
                    )
                    break
                time.sleep(0.005)
                continue

            consecutive_failures = 0
            reconnects = 0      # reset after a successful frame

            # ---- Composite-frame cropping -----------------------------
            if self._crop_h is not None:
                frame = frame[: self._crop_h, :, :]

            # ---- First-frame auto-crop detection ----------------------
            # Some cameras don't report composite height via the property
            # but actually deliver taller frames.  Detect on first frame.
            expected_h = (
                self._selected_request_size[1]
                if self._selected_request_size is not None else self._target_h
            )
            if self._crop_h is None and frame.shape[0] > expected_h:
                h = frame.shape[0]
                if h % expected_h == 0:
                    self._crop_h = expected_h
                    self._log(
                        f"Auto-detected composite frame ({h}px tall).  "
                        f"Cropping to {expected_h}px."
                    )
                    frame = frame[: self._crop_h, :, :]

            frame = self._normalise_frame(frame)
            self._log_frame_stats(frame)

            self.frame_captured.emit("Thermal", frame, ts)

    def _open_capture_with_best_format(self):
        preferred = cv2.VideoWriter_fourcc(*self._pixfmt[:4].ljust(4))
        fourcc_prefs = [preferred] + [f for f in _FOURCC_SUPPORTED if f != preferred]

        fallback_meta = None

        for req_w, req_h in self._resolution_candidates:
            for fourcc in fourcc_prefs:
                meta = self._probe_profile(req_w, req_h, fourcc)
                if meta is None:
                    continue

                if fallback_meta is None:
                    fallback_meta = meta

                if not meta.get("looks_black", True):
                    return self._open_profile(meta)

        if fallback_meta is not None:
            self._log(
                "WARNING: all probed formats produced near-black samples; "
                f"keeping fallback FOURCC={fallback_meta['fourcc']} for live capture"
            )
            return self._open_profile(fallback_meta)

        raise RuntimeError(
            f"cv2.VideoCapture could not produce frames from /dev/video{self._device_idx}"
        )

    def _probe_profile(self, req_w, req_h, fourcc):
        cap = self._configure_capture(req_w, req_h, fourcc)
        if cap is None:
            return None

        sample = None
        try:
            self._warmup_capture(cap)
            ok, frame = cap.read()
            if ok and frame is not None:
                sample = frame

            actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = cap.get(cv2.CAP_PROP_FPS)
            actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
            fourcc_str = self._fourcc_to_str(actual_fourcc)

            normalised = self._normalise_frame(sample)
            stats = self._frame_stats(normalised)
            looks_black = self._frame_looks_black(normalised)
            self._log(
                f"Probe /dev/video{self._device_idx}: request={req_w}x{req_h} "
                f"requested={self._fourcc_to_str(fourcc)} actual={fourcc_str} "
                f"{actual_w}x{actual_h} @{actual_fps:.1f}fps sample={stats}"
            )

            if sample is None:
                return None

            return {
                "requested_width": req_w,
                "requested_height": req_h,
                "requested_fourcc": self._fourcc_to_str(fourcc),
                "requested_fourcc_value": fourcc,
                "width": actual_w,
                "height": actual_h,
                "fps": actual_fps,
                "fourcc": fourcc_str,
                "sample_stats": stats,
                "looks_black": looks_black,
            }
        finally:
            cap.release()

    def _open_profile(self, meta):
        cap = self._configure_capture(
            meta["requested_width"],
            meta["requested_height"],
            meta["requested_fourcc_value"],
        )
        if cap is None:
            raise RuntimeError(
                f"failed to reopen /dev/video{self._device_idx} with "
                f"{meta['requested_width']}x{meta['requested_height']} "
                f"{meta['requested_fourcc']}"
            )

        self._warmup_capture(cap)
        ok, frame = cap.read()
        sample = frame if ok and frame is not None else None
        normalised = self._normalise_frame(sample)

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))

        chosen_meta = dict(meta)
        chosen_meta.update({
            "width": actual_w,
            "height": actual_h,
            "fps": actual_fps,
            "fourcc": self._fourcc_to_str(actual_fourcc),
            "sample_stats": self._frame_stats(normalised),
            "looks_black": self._frame_looks_black(normalised),
        })
        return cap, chosen_meta

    def _configure_capture(self, req_w, req_h, fourcc):
        cap = cv2.VideoCapture(self._device_idx, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            return None

        cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, req_w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, req_h)
        cap.set(cv2.CAP_PROP_FPS, self._target_fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        return cap

    def _warmup_capture(self, cap):
        for _ in range(max(0, self._warmup_frames)):
            cap.read()
            if self._warmup_sleep_s > 0:
                time.sleep(self._warmup_sleep_s)

    def _build_resolution_candidates(self, thermal_cfg):
        candidates = []

        def add(width, height):
            try:
                pair = (int(width), int(height))
            except (TypeError, ValueError):
                return
            if pair[0] <= 0 or pair[1] <= 0:
                return
            if pair not in candidates:
                candidates.append(pair)

        for item in thermal_cfg.get("probe_resolutions", []) or []:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                add(item[0], item[1])
                continue
            if isinstance(item, str):
                match = re.match(r"^\s*(\d+)\s*[xX/]\s*(\d+)\s*$", item)
                if match:
                    add(match.group(1), match.group(2))

        add(self._target_w, self._target_h)
        add(self._target_h, self._target_w)
        add(240, 320)
        add(320, 240)
        return candidates

    @staticmethod
    def _normalise_frame(frame):
        if frame is None:
            return None
        if frame.ndim == 3 and frame.shape[2] == 2:
            return cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_YUY2)
        if frame.ndim == 3 and frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        if frame.ndim == 3 and frame.shape[2] == 1:
            return frame[:, :, 0]
        return frame

    @staticmethod
    def _frame_stats(frame):
        if frame is None:
            return "no-frame"
        return (
            f"shape={frame.shape} dtype={frame.dtype} "
            f"min={int(frame.min())} max={int(frame.max())} mean={float(frame.mean()):.2f}"
        )

    @staticmethod
    def _frame_looks_black(frame):
        if frame is None:
            return True
        try:
            return int(frame.max()) <= 1 and float(frame.mean()) <= 0.5
        except Exception:
            return False

    def _log_frame_stats(self, frame):
        if frame is None or self._frame_debug_logged >= 5:
            return
        self._frame_debug_logged += 1
        self._log(
            f"Live frame {self._frame_debug_logged}/5 ({self._actual_fourcc or 'unknown'}): "
            f"{self._frame_stats(frame)}"
        )
        if self._frame_looks_black(frame):
            self._log(
                "WARNING: thermal frame looks near-black after normalisation; "
                "check FOURCC, gain/palette mode, and direct OpenCV frame dump"
            )

    @staticmethod
    def _fourcc_to_str(value):
        return "".join(chr((value >> (8 * i)) & 0xFF) for i in range(4))

    # ================================================================
    #  Logging
    # ================================================================

    @staticmethod
    def _log(msg):
        ts = time.strftime("%H:%M:%S")
        print(f"[TB4117 {ts}] {msg}")