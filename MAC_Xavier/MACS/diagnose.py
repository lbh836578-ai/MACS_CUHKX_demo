#!/usr/bin/env python3
"""
diagnose.py
-----------
独立诊断脚本，无需启动完整 MACS 即可排查 TB4117 和 NYX650 问题。

用法：
    python diagnose.py            # 运行全部检查
    python diagnose.py --tb       # 只检查 TB4117
    python diagnose.py --nyx      # 只检查 NYX650
    python diagnose.py --usb      # 只检查 USB 带宽
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


SEP = "=" * 60


def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")


def run(cmd, timeout=8):
    """运行命令，返回 (stdout, stderr, returncode)。"""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1
    except Exception as e:
        return "", str(e), -1


# ─────────────────────────────────────────────
# 1. 系统 USB 总线概览
# ─────────────────────────────────────────────

def check_usb():
    section("USB 设备列表 (lsusb)")
    out, _, _ = run("lsusb")
    print(out or "(无输出)")

    print()
    # 重点标注已知设备
    devices = {
        "2bdf": "TB4117 热像仪 (HikMicro)",
        "04b4": "NYX650 / Cypress USB",
        "0525": "NYX650 (可能)",
    }
    found = {k: False for k in devices}
    for line in out.lower().splitlines():
        for vid, name in devices.items():
            if vid in line:
                found[vid] = True
                print(f"  [FOUND] {name}  →  {line.strip()}")
    for vid, name in devices.items():
        if not found[vid]:
            print(f"  [MISS ] {name}  (VID {vid} 未在 lsusb 中出现)")

    section("USB 带宽占用 (lsusb -v 摘要)")
    out, _, rc = run("lsusb -t")
    print(out or "(需要 root 才能显示完整树)")

    section("USB 控制器与速度")
    out, _, _ = run("lsusb -v 2>/dev/null | grep -E 'bDeviceClass|bcdUSB|MaxPower|iProduct'")
    print(out[:2000] if out else "(权限不足，请用 sudo python diagnose.py --usb)")


# ─────────────────────────────────────────────
# 2. V4L2 设备枚举
# ─────────────────────────────────────────────

def check_v4l2():
    section("V4L2 设备 (v4l2-ctl --list-devices)")
    out, err, rc = run("v4l2-ctl --list-devices")
    if rc != 0:
        print(f"  v4l2-ctl 未安装或出错: {err}")
        print("  安装: sudo apt install v4l-utils")
    else:
        print(out or "(没有 V4L2 设备)")

    section("内核 UVC 模块状态")
    out, _, _ = run("lsmod | grep uvc")
    if out:
        print(f"  [OK] uvcvideo 已加载:\n  {out}")
    else:
        print("  [WARN] uvcvideo 未加载，尝试: sudo modprobe uvcvideo")

    section("/dev/video* 节点列表")
    out, _, _ = run("ls -la /dev/video* 2>/dev/null")
    print(out or "  (没有 /dev/video* 节点)")


# ─────────────────────────────────────────────
# 3. TB4117 详细诊断
# ─────────────────────────────────────────────

def check_tb4117():
    section("TB4117 热像仪诊断")

    # 3-1. USB 层
    print("[1] USB 层")
    out, _, _ = run("lsusb | grep -i '2bdf'")
    if out:
        print(f"  [OK] HikMicro 设备在总线上: {out}")
    else:
        print("  [FAIL] lsusb 未找到 VID=2bdf")
        print("         → 检查 USB 线是否接好，或设备是否处于 UVC 模式")
        print("         → 如设备处于 NCM(网络)模式，需切换为 UVC 模式")
        return

    # 3-2. sysfs VID 节点定位
    print("\n[2] sysfs 节点定位")
    sysfs = Path("/sys/bus/usb/devices")
    found_idx = None
    if sysfs.exists():
        for dev_dir in sysfs.iterdir():
            vid_f = dev_dir / "idVendor"
            if vid_f.exists():
                try:
                    if vid_f.read_text().strip().lower() == "2bdf":
                        for vnode in dev_dir.glob("**/video4linux/video*"):
                            idx_str = vnode.name.replace("video", "")
                            if idx_str.isdigit():
                                found_idx = int(idx_str)
                                print(f"  [OK] 找到 /dev/video{found_idx} (via sysfs VID)")
                except Exception:
                    pass
    if found_idx is None:
        print("  [WARN] sysfs VID 方法未定位到 /dev/video*")

    # 3-3. 格式探测
    print("\n[3] V4L2 支持格式 (v4l2-ctl --list-formats-ext)")
    if found_idx is not None:
        out, err, rc = run(f"v4l2-ctl -d /dev/video{found_idx} --list-formats-ext")
        if rc == 0:
            print(out[:1500])
            if "MJPG" in out or "mjpg" in out.lower():
                print("  [OK] 设备支持 MJPG")
            else:
                print("  [WARN] 设备未列出 MJPG 格式，建议改回 YUYV")
        else:
            print(f"  {err}")
    else:
        print("  (跳过，未确定设备节点)")

    # 3-4. OpenCV 直接测试
    print("\n[4] OpenCV 直接打开测试 (cv2.VideoCapture)")
    try:
        import cv2
        # 尝试所有 /dev/video* 节点
        for dev in sorted(Path("/dev").glob("video*")):
            idx_str = dev.name.replace("video", "")
            if not idx_str.isdigit():
                continue
            idx = int(idx_str)
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            if not cap.isOpened():
                cap.release()
                continue
            # 先尝试 MJPG
            for fmt_str, fmt_code in [
                ("MJPG", cv2.VideoWriter_fourcc(*"MJPG")),
                ("YUYV", cv2.VideoWriter_fourcc(*"YUYV")),
            ]:
                cap.set(cv2.CAP_PROP_FOURCC, fmt_code)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 160)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 120)
                actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
                fourcc_str = "".join(
                    chr((actual_fourcc >> (8 * i)) & 0xFF) for i in range(4)
                )
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                print(f"  video{idx}: 请求{fmt_str} → 实际FOURCC={fourcc_str!r}  {w}x{h}")
                if w in (160, 320) and h in (120, 240):
                    print(f"  [CANDIDATE] /dev/video{idx} 分辨率匹配，尝试读帧...")
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        print(f"  [OK] 读帧成功！shape={frame.shape}  dtype={frame.dtype}")
                        # 测量 10 帧的实际 FPS
                        t0 = time.time()
                        for _ in range(10):
                            cap.read()
                        elapsed = time.time() - t0
                        fps = 10 / elapsed if elapsed > 0 else 0
                        print(f"  [OK] 实测 FPS ≈ {fps:.1f}")
                    else:
                        print(f"  [FAIL] cap.read() 返回失败")
                    break
            cap.release()
    except ImportError:
        print("  cv2 未安装，跳过 OpenCV 测试")

    # 3-5. dmesg USB 错误
    print("\n[5] dmesg 中 USB 错误 (最近 20 条)")
    out, _, _ = run("dmesg | grep -iE 'usb|uvc|hik' | tail -20")
    print(out or "  (无相关消息，或需要 sudo)")


# ─────────────────────────────────────────────
# 4. NYX650 / FPS 下降诊断
# ─────────────────────────────────────────────

def check_nyx650():
    section("NYX650 Depth/IR FPS 下降诊断")

    print("[1] ScepterSDK 安装检查")
    sdk_paths = [
        os.path.expanduser("~/ScepterSDK/MultilanguageSDK/Python"),
        "/opt/ScepterSDK/MultilanguageSDK/Python",
    ]
    sdk_found = False
    for p in sdk_paths:
        if os.path.isdir(p):
            print(f"  [OK] SDK 路径存在: {p}")
            sdk_found = True
        else:
            print(f"  [MISS] {p}")
    if not sdk_found:
        print("  → SDK 未安装，NYX650 驱动会跳过")
        return

    print("\n[2] USB 带宽压力估算")
    print("  NYX650 RGB 1600×1200 @15fps (MJPG 压缩后约 2-5 MB/s)")
    print("  NYX650 Depth 640×480 @15fps (uint16 raw ≈ 9.2 MB/s)")
    print("  NYX650 IR   640×480 @15fps (uint8  raw ≈ 4.6 MB/s)")
    print("  TB4117  160×120  @25fps YUYV ≈ 0.9 MB/s / MJPG < 0.2 MB/s")
    print("  Pi USB 2.0 实际可用带宽 ~35 MB/s，理论合计可能超限")
    print()

    out, _, _ = run("lsusb -t")
    print("  USB 拓扑树:")
    print(out or "  (需要安装 usbutils 或 root 权限)")

    print("\n[3] CPU/内存压力")
    out, _, _ = run("top -bn1 | head -20")
    print(out[:800] if out else "  无输出")

    print("\n[4] dmesg USB 错误 / 过流警告")
    out, _, _ = run("dmesg | grep -iE 'over.current|cannot reset|disconnect|error' | tail -20")
    print(out or "  无告警")

    print("\n[5] 建议的 FPS 告警阈值调整")
    print("  当前配置 fps_warn_ratio=0.7, target=15 → 告警线=10.5fps")
    print("  Pi 实测 ToF depth 约 6fps，建议将 fps_warn_ratio 调低至 0.35")
    print("  或将 depth/IR fps 目标降至 10，在 config/default.yaml 中修改：")
    print()
    print("    camera:")
    print("      nyx650:")
    print("        depth:")
    print("          fps: 10    # 从 15 改为 10")
    print("        ir:")
    print("          fps: 10    # 从 15 改为 10")


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MACS 诊断脚本")
    parser.add_argument("--tb",  action="store_true", help="只检查 TB4117")
    parser.add_argument("--nyx", action="store_true", help="只检查 NYX650")
    parser.add_argument("--usb", action="store_true", help="只检查 USB")
    args = parser.parse_args()

    run_all = not any([args.tb, args.nyx, args.usb])

    print(f"MACS 诊断脚本  —  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Python: {sys.version}")

    if run_all or args.usb:
        check_usb()
    if run_all:
        check_v4l2()
    if run_all or args.tb:
        check_tb4117()
    if run_all or args.nyx:
        check_nyx650()

    print(f"\n{SEP}\n  诊断完成\n{SEP}\n")


if __name__ == "__main__":
    main()
