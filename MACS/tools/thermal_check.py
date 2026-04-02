#!/usr/bin/env python3
"""
tools/thermal_check.py
----------------------
Standalone diagnostic tool for the HikVision TB4117 thermal camera.

Replaces the manual bash workflow::

    lsusb | grep 2bdf
    v4l2-ctl --list-devices
    v4l2-ctl -d /dev/videoX --list-formats-ext
    v4l2-ctl -d /dev/videoX --set-fmt-video=width=256,height=192,pixelformat=YUYV
    v4l2-ctl -d /dev/videoX --stream-mmap --stream-count=1 --stream-to=frame.raw

Usage::

    python3 tools/thermal_check.py              # auto-detect
    python3 tools/thermal_check.py --device 2   # use /dev/video2
    python3 tools/thermal_check.py --show        # display live preview
    python3 tools/thermal_check.py --save        # save one test frame
"""

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np


# ─────────────────── USB / sysfs helpers ──────────────────────────────────

HIK_VID = "2bdf"

def check_lsusb():
    """Check if a HIK camera is on the USB bus."""
    print("\n" + "=" * 60)
    print("STEP 1: Checking USB bus (lsusb)")
    print("=" * 60)
    try:
        out = subprocess.check_output(["lsusb"], timeout=5, text=True)
        found = False
        for line in out.splitlines():
            if HIK_VID in line.lower():
                print(f"    Found: {line.strip()}")
                found = True
        if not found:
            print(f"    No USB device with VID={HIK_VID} found")
            print("      → Is the TB4117 connected via USB?")
            print("      → Is it powered? (check LED)")
        return found
    except FileNotFoundError:
        print("    lsusb not found.  Install: sudo apt install usbutils")
        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None


def find_video_device():
    """Find /dev/videoX for the HIK camera."""
    print("\n" + "=" * 60)
    print("STEP 2: Finding /dev/video* device node")
    print("=" * 60)

    # Method A: sysfs USB VID match
    sysfs_usb = Path("/sys/bus/usb/devices")
    if sysfs_usb.exists():
        for dev_dir in sysfs_usb.iterdir():
            vid_file = dev_dir / "idVendor"
            if not vid_file.exists():
                continue
            try:
                vid = vid_file.read_text().strip().lower()
            except OSError:
                continue
            if vid != HIK_VID:
                continue
            for vnode in dev_dir.glob("**/video4linux/video*"):
                idx = int(vnode.name.replace("video", ""))
                print(f"    Matched USB VID {HIK_VID} → /dev/video{idx}")
                return idx

    # Method B: card name match
    v4l_dir = Path("/sys/class/video4linux")
    if v4l_dir.exists():
        for vdir in sorted(v4l_dir.iterdir()):
            name_file = vdir / "name"
            if not name_file.exists():
                continue
            try:
                name = name_file.read_text().strip()
            except OSError:
                continue
            name_l = name.lower()
            if any(kw in name_l for kw in ("hik", "thermal", "tb4117")):
                idx = int(vdir.name.replace("video", ""))
                print(f"    Matched name '{name}' → /dev/video{idx}")
                return idx

    print("    Could not auto-detect.  Use --device <N>")
    return None


def list_formats(dev_idx):
    """Run v4l2-ctl --list-formats-ext."""
    print("\n" + "=" * 60)
    print(f"STEP 3: Querying formats for /dev/video{dev_idx}")
    print("=" * 60)
    dev = f"/dev/video{dev_idx}"
    try:
        out = subprocess.check_output(
            ["v4l2-ctl", "-d", dev, "--list-formats-ext"],
            timeout=5, text=True, stderr=subprocess.STDOUT,
        )
        print(out)
        return out
    except FileNotFoundError:
        print("    v4l2-ctl not found.  Install: sudo apt install v4l-utils")
        return ""
    except Exception as e:
        print(f"    Error: {e}")
        return ""


def test_capture(dev_idx, width=256, height=192, fps=25, show=False, save=False):
    """Open the camera with OpenCV and try to read frames."""
    print("\n" + "=" * 60)
    print(f"STEP 4: Test capture from /dev/video{dev_idx}")
    print(f"        Requesting {width}x{height} @{fps}fps")
    print("=" * 60)

    # Pre-configure with v4l2-ctl
    dev = f"/dev/video{dev_idx}"
    try:
        subprocess.run(
            ["v4l2-ctl", "-d", dev,
             "--set-fmt-video",
             f"width={width},height={height},pixelformat=YUYV"],
            capture_output=True, timeout=5,
        )
        subprocess.run(
            ["v4l2-ctl", "-d", dev, "--set-parm", str(fps)],
            capture_output=True, timeout=5,
        )
        print("    v4l2-ctl pre-configuration done")
    except Exception:
        print("    v4l2-ctl pre-configuration skipped")

    cap = cv2.VideoCapture(dev_idx, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"    cv2.VideoCapture failed to open /dev/video{dev_idx}")
        print("      → Check permissions: ls -la /dev/video*")
        print("      → Try: sudo usermod -aG video $USER")
        return False

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_str = "".join(chr((fourcc_int >> (8 * i)) & 0xFF) for i in range(4))

    print(f"  Negotiated: {actual_w}x{actual_h} @{actual_fps:.1f}fps  "
          f"FOURCC={fourcc_str}")

    if actual_h > height and actual_h % height == 0:
        n = actual_h // height
        print(f"   Composite frame: {n} sub-images stacked vertically")
        print(f"      Will crop to top {width}x{height}")

    # Discard initial frames
    for _ in range(5):
        cap.read()

    # Read test frames
    success_count = 0
    t0 = time.monotonic()
    num_test = 30

    print(f"\n  Reading {num_test} frames...")
    for i in range(num_test):
        ret, frame = cap.read()
        if ret and frame is not None:
            success_count += 1
            if i == 0:
                print(f"  First frame shape: {frame.shape}  dtype={frame.dtype}")
                # Crop if composite
                if frame.shape[0] > height:
                    frame = frame[:height, :, :]
                    print(f"  After crop: {frame.shape}")
        else:
            print(f"  Frame {i}: FAILED")

    elapsed = time.monotonic() - t0
    measured_fps = success_count / elapsed if elapsed > 0 else 0

    print(f"\n  Results: {success_count}/{num_test} frames OK  "
          f"({measured_fps:.1f} fps measured)")

    if success_count == 0:
        print("    No frames captured!")
        cap.release()
        return False

    print("    Camera is working!")

    # Save test frame
    if save:
        ret, frame = cap.read()
        if ret and frame is not None:
            if frame.shape[0] > height:
                frame = frame[:height, :, :]
            fname = f"thermal_test_{width}x{height}.jpg"
            cv2.imwrite(fname, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            print(f"    Saved test frame to {fname}")

            # Also save full composite for inspection
            cap.read()  # skip
            ret2, frame2 = cap.read()
            if ret2 and frame2 is not None and frame2.shape[0] > height:
                fname2 = f"thermal_test_composite_{frame2.shape[1]}x{frame2.shape[0]}.jpg"
                cv2.imwrite(fname2, frame2, [cv2.IMWRITE_JPEG_QUALITY, 95])
                print(f"    Saved full composite to {fname2}")

    # Live preview
    if show:
        print("\n  Showing live preview.  Press 'q' to quit.")
        while True:
            ret, frame = cap.read()
            if not ret:
                continue
            if frame.shape[0] > height:
                frame = frame[:height, :, :]
            # Upscale for visibility
            display = cv2.resize(frame, (width * 2, height * 2),
                                 interpolation=cv2.INTER_NEAREST)
            cv2.imshow(f"TB4117 Thermal (/dev/video{dev_idx})", display)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        cv2.destroyAllWindows()

    cap.release()
    return True


def check_prerequisites():
    """Check that v4l-utils and opencv are available."""
    print("\n" + "=" * 60)
    print("STEP 0: Prerequisites")
    print("=" * 60)

    # v4l2-ctl
    try:
        out = subprocess.check_output(
            ["v4l2-ctl", "--version"], timeout=5, text=True,
            stderr=subprocess.STDOUT,
        )
        ver = out.strip().split("\n")[0]
        print(f"    v4l2-ctl: {ver}")
    except FileNotFoundError:
        print("    v4l2-ctl not found")
        print("      Install: sudo apt install v4l-utils")
    except Exception:
        print("    v4l2-ctl: could not determine version")

    # OpenCV
    try:
        print(f"    OpenCV: {cv2.__version__}")
    except Exception:
        print("    OpenCV not available")

    # uvcvideo kernel module
    try:
        out = subprocess.check_output(
            ["lsmod"], timeout=5, text=True,
        )
        if "uvcvideo" in out:
            print("   uvcvideo kernel module loaded")
        else:
            print("   uvcvideo kernel module NOT loaded")
            print("      Try: sudo modprobe uvcvideo")
    except Exception:
        pass

    # /dev/video* permissions
    videos = sorted(Path("/dev").glob("video*"))
    if videos:
        print(f"  Video devices: {', '.join(v.name for v in videos)}")
    else:
        print("    No /dev/video* devices found")


# ─────────────────────────── Main ────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TB4117 Thermal Camera Diagnostic Tool",
    )
    parser.add_argument(
        "--device", "-d", type=int, default=-1,
        help="Force /dev/video<N> index (skip auto-detect)",
    )
    parser.add_argument(
        "--width", "-W", type=int, default=256,
        help="Requested frame width (default: 256)",
    )
    parser.add_argument(
        "--height", "-H", type=int, default=192,
        help="Requested frame height (default: 192)",
    )
    parser.add_argument(
        "--fps", type=int, default=25,
        help="Requested FPS (default: 25)",
    )
    parser.add_argument(
        "--show", action="store_true",
        help="Show live preview window",
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Save a test frame to disk",
    )
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════════════╗")
    print("║   TB4117 Thermal Camera — Diagnostic Tool               ║")
    print("╚══════════════════════════════════════════════════════════╝")

    check_prerequisites()
    usb_ok = check_lsusb()

    if args.device >= 0:
        dev_idx = args.device
        print(f"\n  Using manually specified device: /dev/video{dev_idx}")
    else:
        dev_idx = find_video_device()
        if dev_idx is None:
            print("\n  Cannot proceed without a video device.")
            if usb_ok:
                print("   The USB device was found but has no /dev/video node.")
                print("   Possible fixes:")
                print("     1. sudo modprobe uvcvideo")
                print("     2. Check if the module is in UVC mode (not NCM)")
                print("     3. Replug the USB cable")
            sys.exit(1)

    list_formats(dev_idx)

    ok = test_capture(
        dev_idx,
        width=args.width,
        height=args.height,
        fps=args.fps,
        show=args.show,
        save=args.save,
    )

    print("\n" + "=" * 60)
    if ok:
        print("  ALL CHECKS PASSED — TB4117 is ready for MACS")
        print(f"   Config suggestion:")
        print(f"     device_index: {dev_idx}")
        print(f"     width: {args.width}")
        print(f"     height: {args.height}")
        print(f"     fps: {args.fps}")
    else:
        print("  CAMERA TEST FAILED")
    print("=" * 60)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()