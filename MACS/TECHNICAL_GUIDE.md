# MACS 技术文档
## MultiModal Action Capture System — 全代码深度解析

---

## 目录

1. [系统总架构](#1-系统总架构)
2. [启动流程 — main.py](#2-启动流程--mainpy)
3. [UI 层](#3-ui-层)
   - 3.1 [MainWindow 状态机](#31-mainwindow-状态机)
   - 3.2 [ControlPanel 控制栏](#32-controlpanel-控制栏)
   - 3.3 [PreviewPanel 预览面板](#33-previewpanel-预览面板)
   - 3.4 [StatusPanel 状态栏](#34-statuspanel-状态栏)
4. [采集层](#4-采集层)
   - 4.1 [BaseCameraDriver 抽象基类](#41-basecameradriver-抽象基类)
   - 4.2 [NYX650Driver ToF 相机驱动](#42-nyx650driver-tof-相机驱动)
   - 4.3 [TB4117Driver 热像仪驱动](#43-tb4117driver-热像仪驱动)
   - 4.4 [FPSCounter 帧率计数器](#44-fpscounter-帧率计数器)
   - 4.5 [SyncManager 同步管理器](#45-syncmanager-同步管理器)
   - 4.6 [FramePacket 帧数据包](#46-framepacket-帧数据包)
   - 4.7 [HealthMonitor 健康监控](#47-healthmonitor-健康监控)
   - 4.8 [SessionRecorder 会话录制器](#48-sessionrecorder-会话录制器)
   - 4.9 [CaptureController 采集总协调器](#49-capturecontroller-采集总协调器)
    - 4.10 [MmWaveDriver 雷达驱动](#410-mmwavedriver-雷达驱动)
    - 4.11 [ImuDriver BLE IMU 驱动](#411-imudriver-ble-imu-驱动)
    - 4.12 [SessionCoordinator 外设会话协调器](#412-sessioncoordinator-外设会话协调器)
5. [后处理层](#5-后处理层)
   - 5.1 [Segmenter 分段器](#51-segmenter-分段器)
   - 5.2 [FrameExporter 帧导出器](#52-frameexporter-帧导出器)
   - 5.3 [Validator 验证器](#53-validator-验证器)
   - 5.4 [PostProcessor 后处理流水线](#54-postprocessor-后处理流水线)
6. [配置系统](#6-配置系统)
7. [数据目录结构](#7-数据目录结构)
8. [线程模型与信号流](#8-线程模型与信号流)
9. [Demo 模式](#9-demo-模式)
10. [键盘快捷键](#10-键盘快捷键)
11. [多模态诊断与运维工具](#11-多模态诊断与运维工具)
12. [批判性评审与优化建议](#12-批判性评审与优化建议)

---

## 1. 系统总架构

当前的 MACS 已经不再是“4 路相机 + 后处理”的单一流水线，而是一个以 `CaptureController + SessionRecorder` 为核心、向外扩展 mmWave 与 IMU 的多模态采集骨架。

```
┌────────────────────────────────────────────────────────────┐
│                         main.py                            │
│  load_config → apply_runtime_imu_selection → QApplication │
│  → MainWindow → CaptureController / DemoFrameGenerator    │
└──────────────────────────────┬─────────────────────────────┘
                               │
                 ┌─────────────▼─────────────┐
                 │           UI 层            │
                 │  MainWindow (状态机)       │
                 │  ├── ControlPanel         │
                 │  ├── PreviewPanel         │
                 │  └── StatusPanel          │
                 └─────────────┬─────────────┘
                               │ Qt Signals / Slots
┌──────────────────────────────▼─────────────────────────────┐
│                    CaptureController                        │
│                      (主线程 QObject)                       │
│  ├── NYX650Driver / TB4117Driver                            │
│  ├── FPSCounter × 4 / SyncManager / HealthMonitor          │
│  ├── SessionRecorder  ── owns session_id/session_dir/start │
│  │    └── AsyncFrameWriter                                  │
│  └── SessionCoordinator                                     │
│       ├── MmWaveDriver  ── frames.bin + timestamps.csv      │
│       └── ImuDriver     ── one CSV per IMU label            │
└──────────────────────────────┬─────────────────────────────┘
                               │ raw/session_xxx/ 统一归档
                 ┌─────────────▼─────────────┐
                 │      PostProcessor         │
                 │  Segmenter / Exporter /    │
                 │  Validator  (当前仅相机)   │
                 └───────────────────────────┘
```

这里最重要的设计变化不是“多加了两个驱动”，而是 **会话所有权没有外移**：

- `SessionRecorder` 仍然是唯一的 `session_id / session_dir / recording_start_ns` 生产者。
- `SessionCoordinator` 只是把 mmWave 和 IMU 挂接到同一会话目录，而不是再建第二棵会话树。
- `raw/` 目录现在已经是多模态完备的；但 `processed/` 后处理目前仍然只覆盖 `RGB / Depth / IR / Thermal` 四路相机数据。

整个系统现在可以分成 **5 类运行平面**：
- **UI 主线程**：PyQt5 事件循环、状态栏刷新、录制状态机、健康检查入口。
- **相机采集线程 × 2**：NYX650Driver 与 TB4117Driver 各自运行在 `QThread` 中。
- **外设后台工作平面**：mmWave 的串口 reader 线程 + writer 线程；IMU 的 asyncio 事件循环线程 + 每设备 BLE 协程 + CSV writer 线程。
- **相机写盘线程**：`AsyncFrameWriter` 异步落盘相机帧，避免主线程被 I/O 阻塞。
- **后处理线程**：`PostProcessor(QThread)`，录制结束后自动启动，但当前仍是相机中心流水线。

---

## 2. 启动流程 — main.py

### 2.1 Qt 插件路径保护

```python
_qt_plugin_path_before = os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH")

from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow  # 这一步会触发 import cv2

if _qt_plugin_path_before is None:
    os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
else:
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = _qt_plugin_path_before
```

**为什么需要这段代码**：`opencv-python`（非 headless 版本）在被 import 时会把 `QT_QPA_PLATFORM_PLUGIN_PATH` 覆盖为自己内置的 Qt 插件目录。如果这发生在 `QApplication` 创建之前，PyQt5 就找不到正确的平台插件（xcb/wayland），程序 Abort。这段代码在 import 前保存原值，在 import 后恢复，彻底规避这个冲突。

### 2.2 配置加载

```python
def load_config(path):
    if not os.path.isfile(path):
        return {}
    try:
        import yaml
        with open(path, "r") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:
        print(f"[config] failed to parse {path}: {exc}")
        return {}
```

使用 `yaml.safe_load`（而非 `yaml.load`），禁止 YAML 中执行任意 Python 对象，防止配置文件注入攻击。返回空字典而不是抛异常，确保程序可以用内置默认值继续运行。

### 2.3 生产模式 vs Demo 模式

```python
parser.add_argument("--imu-device", action="append", default=[])

config = load_config(args.config)
apply_runtime_imu_selection(config, args.imu_device)

if args.demo:
    generator = DemoFrameGenerator(window)
else:
    from capture.capture_controller import CaptureController
    controller = CaptureController(config, window)
    controller.initialize()
    app.aboutToQuit.connect(controller.shutdown)
```

生产模式下，`CaptureController.initialize()` 不仅启动两路相机，还会调用 `SessionCoordinator.prepare()` 预热 mmWave 和 IMU。也就是说，从启动那一刻开始，程序就会完成以下事情：

- 根据 `default.yaml` 和 `--imu-device` 组合出本次真正启用的 IMU 集合。
- 启动相机线程。
- 预热雷达串口并下发 profile。
- 做 BLE 扫描与 IMU 建链尝试。
- 在 terminal 与 UI 状态栏中显示 IMU 的 configured / visible / connected 名称。

Demo 模式仍然只合成 4 路相机帧，不模拟 mmWave / IMU，因此它适合 UI 验证，不适合多模态端到端验证。

---

## 3. UI 层

### 3.1 MainWindow 状态机

`MainWindow` 是整个应用的核心，它实现了一个 **3 状态机**：

```
IDLE ──(Start)──→ RECORDING ──(Stop)──→ PROCESSING ──(完成)──→ IDLE
  ↑                   │
  └───(Cancel)────────┘  取消时直接回 IDLE，丢弃数据
```

状态转换通过 `_set_state(new)` 实现：

```python
def _set_state(self, new):
    self._state = new
    if new == AppState.IDLE:
        self.control_panel.set_idle_state()    # 按钮恢复
        self.status_panel.reset()              # 状态栏清空
    elif new == AppState.RECORDING:
        multi = len(self._labels) > 1
        self.control_panel.set_recording_state(has_multiple_labels=multi)
    elif new == AppState.PROCESSING:
        self.control_panel.set_processing_state()
        self.status_panel.stop_timer()         # 停止计时
```

### 3.2 Breakpoint（动作切换点）机制

这是 MACS 的核心功能之一。用户输入多个标签（如 `walk-sit-read`），录制时按 Breakpoint 按钮切换到下一个动作：

```python
def _on_breakpoint(self):
    bp = {
        "index":         len(self._breakpoints),
        "label_before":  self._labels[self._label_idx],
        "label_after":   self._labels[self._label_idx + 1],
        "host_timestamp_ns": time.time_ns(),
    }
    self._breakpoints.append(bp)
    self._label_idx += 1
    self.breakpoint_marked.emit(bp["index"], bp["label_before"], bp["label_after"])
```

`breakpoint_marked` 信号被 `CaptureController` 接收后，转发给 `SessionRecorder.add_breakpoint()`，记录切换时刻的纳秒时间戳。后处理阶段用这个时间戳把连续帧流切割成各个动作片段。

### 3.3 ControlPanel 控制栏

标签解析逻辑：用 `-` 分割输入字符串，过滤空字符串：

```python
# 用户输入: "walk-sit-read"
# 解析结果: ["walk", "sit", "read"]
labels = [l.strip() for l in text.split("-") if l.strip()]
```

4 个按钮的状态在三种 UI 状态下的可用性：

| 按钮 | IDLE | RECORDING | PROCESSING |
|------|------|-----------|------------|
| Start | ✓ | ✗ | ✗ |
| Breakpoint | ✗ | ✓(多标签) | ✗ |
| Stop | ✗ | ✓ | ✗ |
| Cancel | ✗ | ✓ | ✗ |

### 3.3 PreviewPanel 预览面板

2×2 网格布局，每个格子是一个 `ModalityView`：

```
┌────────────┬────────────┐
│    RGB     │   Depth    │  row=0
├────────────┼────────────┤
│     IR     │  Thermal   │  row=1
└────────────┴────────────┘
```

**帧渲染流程**（`_to_pixmap` 方法）：

```
numpy ndarray
    │
    ├── 2D uint16 (Depth/IR 16位)
    │       cv2.normalize → uint8 灰度
    │       QImage(Format_Grayscale8)
    │
    ├── 2D uint8 (IR 8位)
    │       直接 QImage(Format_Grayscale8)
    │
    └── 3D (H,W,3) uint8 BGR (RGB/Thermal)
            cv2.cvtColor BGR→RGB
            QImage(Format_RGB888)
            │
            └── QPixmap.scaled(KeepAspectRatio, SmoothTransformation)
                → 自适应 QLabel 尺寸
```

`import cv2` 被放在 `_to_pixmap()` 内部（懒加载），这样 cv2 只在第一帧到来时才被 import，此时 `QApplication` 已经完全初始化，避免插件路径冲突。

### 3.4 StatusPanel 状态栏

固定高度 28px 的深色横条，现在包含 6 个 QLabel：

```
FPS  RGB:15.0 | D:15.0 | IR:15.0 | T:25.0    Sync 12.3ms    IMU 2/5 online: imu03_waist, imu04_left_ankle
└── _fps_lbl ──────────────────────────┘  └─_sync_lbl─┘    └───────────── _imu_lbl ─────────────┘

Disk 23.4GB    Health OK    REC 00:01:23
└─_disk_lbl┘   └health┘     └─timer┘
```

**同步漂移颜色编码**：
- `drift < 33ms` → 绿色 `#4CAF50`（良好）
- `33ms ≤ drift < 66ms` → 橙色（警告）
- `drift ≥ 66ms` → 红色（超过一帧时长，需要注意）

**IMU 状态编码**：
- `target`：配置里启用了哪些 IMU label，但还未扫描到或未建链。
- `visible`：BLE 扫描已看到配置内设备，但还未建立稳定通知流。
- `online`：已有设备真正进入通知状态，状态栏显示 `connected/total` 和设备名。
- `error`：启用了 IMU 但 prepare 失败或没有任何设备可用。

StatusPanel 的 IMU 文案来自 `CaptureController._sync_external_status()`，其 tooltip 还会展开显示 Active / Visible / Connected 的完整设备名集合。当前 UI 层只显式展示了 IMU 的外设状态，mmWave 仍然只在 terminal summary 和 `session_meta.json` 中可见。

**磁盘用量**：通过 `shutil.disk_usage()` 读取 `data/` 目录所在分区的剩余空间，每 500ms 刷新一次。

---

## 4. 采集层

### 4.1 BaseCameraDriver 抽象基类

所有相机驱动继承自 `BaseCameraDriver(QThread)`。核心是 `run()` 方法，定义了设备生命周期：

```python
def run(self):
    self._running = True
    try:
        self.connect_device()      # 子类实现：打开硬件
        self._is_connected = True
        self.connected.emit()      # 通知主线程：连接成功
    except Exception as exc:
        self.error_occurred.emit(...)
        self._running = False
        return

    try:
        self._capture_loop()       # 子类实现：循环读帧
    except Exception as exc:
        self.error_occurred.emit(...)

    self.disconnect_device()       # 子类实现：释放硬件
    self.disconnected.emit()
```

`stop(timeout_ms=5000)` 设置 `self._running = False`，然后调用 `wait(timeout_ms)` 等待线程退出。

### 4.2 NYX650Driver ToF 相机驱动

**SDK 加载策略**（模块级，只执行一次）：

```python
_SEARCH_PATHS = [
    "~/ScepterSDK/MultilanguageSDK/Python",  # 用户安装
    "/opt/ScepterSDK/MultilanguageSDK/Python",
]
for _p in _SEARCH_PATHS:
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    _SDK = importlib.import_module("API.ScepterDS_api")
    _SDK_AVAILABLE = True
except Exception:
    pass
```

如果 SDK 不存在，`SDK_AVAILABLE = False`，`CaptureController.initialize()` 会直接跳过 NYX650 的启动，不会报错崩溃。

**设备连接流程**：
1. `scGetDeviceCount(3000)` — 等待最多 3 秒枚举设备
2. `scGetDeviceInfoList(count)` — 获取设备列表（返回值可能是 tuple，需要特殊处理）
3. `scOpenDeviceBySN(sn)` — 用序列号打开（比用索引更稳定）
4. `scSetWorkMode(SC_ACTIVE_MODE)` — 主动模式（同时输出 Depth+IR+Color）
5. `scSetColorResolution(1600, 1200)` — 设置 RGB 分辨率
6. `scStartStream()` — 开始流

**帧读取循环**：

```python
while self._running:
    result = self._cam.scGetFrameReady(c_uint16(1200))  # 最长等 1200ms
    rc, ready = result[0], result[1]
    if rc != 0:
        consecutive_errors += 1
        continue

    if getattr(ready, "depth", 0) == 1:
        self._try_emit("Depth", ft_depth, np.uint16, ts)

    if getattr(ready, "ir", 0) == 1:
        self._try_emit("IR", ft_ir, np.uint8, ts)

    if getattr(ready, "color", 0) == 1:
        self._try_emit_color("RGB", ft_color, ts)
```

`scGetFrameReady` 是阻塞调用，SDK 告知哪种帧已就绪（通过 ready 结构体的字段），再按需提取对应数据。这样一个循环迭代可能产出 1~3 个帧事件。

### 4.3 TB4117Driver 热像仪驱动

#### 多策略自动检测流程

```
Strategy 1: USB sysfs VID:PID 匹配
    /sys/bus/usb/devices/*/idVendor == "2bdf"  (HikMicro)
    → 从对应子目录找 video4linux/videoX
    → 返回 /dev/videoX 的数字索引

Strategy 2: sysfs 设备名关键词匹配
    /sys/class/video4linux/videoX/name
    → 包含 "hik"/"hikvision"/"thermal"/"tb4117" 等
    → 返回索引

Strategy 3: 分辨率探测
    遍历所有 /dev/video*，用 OpenCV 打开
    → 设置目标分辨率，读回实际分辨率
    → 接受精确匹配或宽高互换（横竖方向问题）

配置文件 device_index >= 0 时跳过以上全部
```

**宽高互换问题**（根据实际硬件发现）：你的 TB4117 固件以竖向方向报告传感器，V4L2 列出的是 `120×160`（宽×高），而常识上这个传感器是 `160×120`。`_probe_video_node_by_resolution` 已修复为同时匹配正置和转置情况：

```python
dims_ok = (
    (w == target_w and (h == target_h or h % target_h == 0))
    or
    (w == target_h and (h == target_w or h % target_w == 0))  # 转置情况
)
```

#### FOURCC 协商

```python
preferred = cv2.VideoWriter_fourcc(*self._pixfmt[:4].ljust(4))
fourcc_prefs = [preferred] + [f for f in _FOURCC_SUPPORTED if f != preferred]
for fourcc in fourcc_prefs:
    cap.set(cv2.CAP_PROP_FOURCC, fourcc)
    actual = int(cap.get(cv2.CAP_PROP_FOURCC))
    if actual == fourcc:
        break
```

从配置（MJPG 或 YUYV）构建优先级列表，逐个尝试，实际能用的才退出循环。v4l2-ctl 也提前用同样格式预配置，确保 OpenCV 接管时设备已处于正确状态。

#### 复合帧（Composite Frame）处理

某些 HikMicro 模块把多个子图像（伪彩色热图、Y16 辐射测温图、可见光图）垂直拼接在一帧中。例如请求 `192` 行，实际得到 `384` 行（2 个子图叠加）：

```python
# connect_device() 中检测
if actual_h > self._target_h and actual_h % self._target_h == 0:
    n = actual_h // self._target_h  # 子图数量
    self._crop_h = self._target_h   # 只保留第一个（伪彩色热图）

# _capture_loop() 中裁剪
if self._crop_h is not None:
    frame = frame[: self._crop_h, :, :]

# 运行时首帧检测（设备属性没有明确告知时）
if self._crop_h is None and frame.shape[0] > self._target_h:
    h = frame.shape[0]
    if h % self._target_h == 0:
        self._crop_h = self._target_h
```

#### USB 断连自动重连（_reopen_cap）

dmesg 显示 `Failed to resubmit video URB (-1)` 是 uvcvideo 内核驱动的 USB 通信失败，通常是瞬态问题，重新打开设备即可恢复：

```python
def _reopen_cap(self):
    cap.release()  # 释放旧句柄
    for attempt in range(1, 6):    # 最多重试 5 次
        time.sleep(1.0)            # 等内核重新枚举
        cap = cv2.VideoCapture(self._device_idx, cv2.CAP_V4L2)
        # 重新应用 FOURCC / 分辨率 / FPS / BUFFERSIZE
        ok, _ = cap.read()         # 读一帧验证
        if ok:
            self._cap = cap
            return True
```

`_capture_loop` 中连续失败 30 次（约 0.15 秒）才触发重连，最多重连 3 次，全部失败才 emit `error_occurred`。

### 4.4 FPSCounter 帧率计数器

使用**滑动窗口**（默认 60 帧）精确估算实时帧率：

```python
def tick(self):
    now = time.monotonic()         # 单调时钟，不受系统时间调整影响
    self._times.append(now)        # deque 满了自动丢最旧的
    n = len(self._times)
    if n < 2:
        return 0.0
    elapsed = self._times[-1] - self._times[0]
    return (n - 1) / elapsed       # 窗口内的平均帧率
```

`time.monotonic()` 而非 `time.time()` 是关键——前者不会因 NTP 校时跳变。

### 4.5 SyncManager 同步管理器

跟踪两台相机的**帧间时间漂移**（drift）：

```
NYX650 时间线:   |RGB|Depth|IR|  ts_nyx
TB4117 时间线:   |Thermal|         ts_thermal

drift = |ts_nyx_latest - nearest_thermal_ts|
```

**计算方式**：

```python
def _update_drift(self):
    latest_nyx = max(self._history[m][-1] for m in NYX_MODALITIES)
    # 在热像仪时间戳历史中找最近的一个
    nearest_thermal = min(thermal_buf, key=lambda t: abs(t - latest_nyx))
    drift_ns = abs(latest_nyx - nearest_thermal)
    self._drift_samples.append(drift_ns)
```

返回 `get_drift_ms()` 时对最近 60 个样本取平均，平滑抖动。

**健康等级判定**：
- `drift < 33ms`（半帧 @30fps）→ OK
- `33ms ≤ drift < 66ms`（一帧 @15fps）→ WARN
- `drift ≥ 66ms` → ERROR

additionally，`get_intra_nyx_spread_ms()` 检查 NYX650 内部三路流（RGB/Depth/IR）的时间戳分散度，正常应 < 1ms（因为它们共用同一个触发器）。

### 4.6 FramePacket 帧数据包

轻量值对象（`__slots__` 避免字典开销），目前主要用于组织数据，driver 直接通过信号传递 tuple。

```python
class FramePacket:
    __slots__ = ("modality", "data", "timestamp_ns", "seq")
```

`__slots__` 使每个实例不使用 `__dict__`，在每秒数十帧 × 4 路的场景下，内存和构造速度都更优。

### 4.7 HealthMonitor 健康监控

**不独立开线程**，而是搭载在 `CaptureController` 已有的 500ms 定时器上，每次定时器触发时调用 `tick()`：

```python
def tick(self, fps_values, drift_ms):
    if not self._active:          # 仅在录制期间激活
        return AlertLevel.OK

    worst = AlertLevel.OK
    worst = max(worst, self._check_fps(fps_values))       # FPS 下降检测
    worst = max(worst, self._check_frame_loss(fps_values)) # 断帧检测
    worst = max(worst, self._check_camera_disconnect())    # 相机断连检测
    worst = max(worst, self._check_sync_drift(drift_ms))  # 同步漂移检测
    worst = max(worst, self._check_disk_space())           # 磁盘空间检测
    return worst
```

**5 类健康检查详解**：

| 检查项 | 触发条件 | 等级 | 动作 |
|--------|----------|------|------|
| fps_drop | 实测FPS < 目标×warn_ratio | WARN | 打印日志 |
| frame_loss | 连续N次tick FPS≈0 | ERROR | auto_pause_requested |
| camera_disconnect | NYX650断连 | ERROR | auto_stop_requested |
| camera_disconnect | TB4117断连 | WARN | 仅告警 |
| sync_drift | 漂移 > 66ms | WARN | 打印日志 |
| disk_space | 剩余 < min_gb | ERROR | auto_stop_requested |

`auto_stop_requested` 触发时，`CaptureController._on_auto_stop()` 会自动调用 `recorder.finalize()` 保存已录数据，然后通知 UI 弹出对话框。

### 4.8 SessionRecorder 会话录制器

`SessionRecorder` 仍然只负责四路相机帧的时间戳与文件落盘，但它现在同时承担 **整个系统唯一的会话所有权**：`session_id`、`session_dir` 和 `recording_start_ns` 都由它生成，外部模态只能通过 `set_external_metadata()` 把 summary 附着进来。

#### 目录结构

```
data/raw/session_20260401_190000/
├── session_meta.json     会话元数据
├── timestamps.csv        相机四模态的逐帧时间戳索引
├── RGB/
│   ├── frame_000000.jpg
│   ├── frame_000001.jpg
│   └── ...
├── Depth/
│   ├── frame_000000.npy  (uint16, 单位mm)
│   └── ...
├── IR/
│   ├── frame_000000.npy
│   └── ...
├── Thermal/
│   ├── frame_000000.jpg
│   └── ...
├── mmwave/
│   ├── frames.bin
│   └── timestamps.csv
└── imu/
    ├── imu01_left_wrist.csv
    ├── imu03_waist.csv
    └── ...
```

#### AsyncFrameWriter 异步写盘

相机线程每产生一帧就通过 `enqueue()` 塞入队列，由独立写盘线程消费，避免 I/O 阻塞采集线程：

```python
class AsyncFrameWriter(threading.Thread):
    def __init__(self, maxsize=600, jpg_quality=95):
        self._queue = queue.Queue(maxsize=600)  # 最多缓存 600 帧

    def enqueue(self, filepath, data, fmt="npy"):
        try:
            self._queue.put_nowait(...)          # 满了就丢帧，不阻塞
        except queue.Full:
            self.stats["dropped"] += 1

    def _write(self, item):
        if fmt == "npy":
            np.save(filepath, data)             # 深度/IR 保存原始数值
        elif fmt in ("jpg", "jpeg"):
            cv2.imwrite(filepath, data, [cv2.IMWRITE_JPEG_QUALITY, 95])
```

`flush_and_stop(timeout=30)` 在录制结束时调用，设置停止事件 → 等待队列 drain → 等待线程退出，最长等 30 秒。

#### timestamps.csv 格式

```csv
seq,modality,timestamp_ns,label
0,RGB,1743504000000000000,walk
1,Depth,1743504000066000000,walk
0,Thermal,1743504000000000000,walk
...
1234,RGB,1743504082000000000,sit
```

每行代表一帧，`seq` 是该模态的独立序号（用于拼接文件名 `frame_000000.jpg`），`timestamp_ns` 是 `time.time_ns()` 主机时钟。

#### session_meta.json 格式

```json
{
    "session_id": "20260401_190000",
  "labels": ["walk", "sit", "read"],
  "breakpoints": [
    {"index": 0, "label_before": "walk", "label_after": "sit", "timestamp_ns": 1743504045000000000},
    {"index": 1, "label_before": "sit", "label_after": "read", "timestamp_ns": 1743504060000000000}
  ],
  "recording_start_ns": 1743504000000000000,
  "recording_stop_ns": 1743504090000000000,
  "duration_s": 90.0,
  "frame_counts": {"RGB": 1350, "Depth": 1350, "IR": 1350, "Thermal": 2250},
  "writer_stats": {"written": 6300, "dropped": 0, "errors": 0},
    "save_formats": {"RGB": "jpg", "Depth": "npy", "IR": "npy", "Thermal": "jpg"},
    "modalities": ["RGB", "Depth", "IR", "Thermal", "mmwave", "imu"],
    "multimodal": {
        "modalities": {
            "mmwave": {
                "enabled": true,
                "prepared": true,
                "frames_captured": 146,
                "writer_stats": {"written": 146, "dropped": 0, "errors": 0}
            },
            "imu": {
                "enabled": true,
                "active_devices": ["imu03_waist", "imu04_left_ankle"],
                "scan_visible_devices": ["imu03_waist", "imu04_left_ankle"],
                "devices_connected": 2,
                "devices": [
                    {"label": "imu03_waist", "samples_captured": 4312},
                    {"label": "imu04_left_ankle", "samples_captured": 4298}
                ]
            }
        }
    }
}
```

要注意：`timestamps.csv` 目前仍然只记录四路相机逐帧索引；外部模态不走这张统一索引表，而是走各自目录内的专用文件格式。

### 4.9 CaptureController 采集总协调器

`CaptureController` 是**胶水层**，运行在主线程（是 `QObject`，不是 `QThread`）：

**信号连接图**：

```
NYX650Driver.frame_captured  →  _on_frame()
TB4117Driver.frame_captured  →  _on_frame()
NYX650Driver.connected       →  _on_nyx_connected()
NYX650Driver.disconnected    →  _on_nyx_disconnected()
TB4117Driver.connected       →  _on_tb_connected()
TB4117Driver.disconnected    →  _on_tb_disconnected()

MainWindow.recording_started  →  _on_recording_started()
MainWindow.breakpoint_marked  →  _on_breakpoint_marked()
MainWindow.recording_stopped  →  _on_recording_stopped()
MainWindow.recording_cancelled → _on_recording_cancelled()

HealthMonitor.alert_fired         →  _on_health_alert()
HealthMonitor.auto_pause_requested → _on_auto_pause()
HealthMonitor.auto_stop_requested  → _on_auto_stop()
```

**`_on_frame()` 仍然是最高频调用**（每秒数十次）：

```python
@pyqtSlot(str, object, object)
def _on_frame(self, modality, frame, timestamp_ns):
    fps_val = self._fps[modality].tick()         # 更新FPS计数
    self._sync.record_timestamp(modality, timestamp_ns)  # 更新同步追踪
    self._win.frame_received.emit(modality, frame, fps_val)  # 发给UI预览

    if self._recording and self._recorder is not None:
        self._recorder.write_frame(modality, frame, timestamp_ns)  # 写盘
```

但现在 `CaptureController` 还承担了两个以前不存在的职责：

1. 在 `initialize()` 阶段预热 `SessionCoordinator.prepare()`，统一准备 mmWave / IMU。
2. 在 `_refresh_status()` 阶段把外设 summary 同步到 terminal 与 `StatusPanel.update_imu()`。

真正的录制启动逻辑也已经变成“共享会话起点”的单会话模式：

```python
@pyqtSlot(list)
def _on_recording_started(self, labels):
    session_start_ns = time.time_ns()
    self._recorder = SessionRecorder(base_dir, labels, self._cfg, start_ns=session_start_ns)
    self._session_coordinator.start_session(
        self._recorder.session_dir,
        session_start_ns,
    )
    self._recording = True
```

这段代码的含义非常关键：外部模态并不拥有独立 session，它们只是复用 `SessionRecorder` 生成的 `session_dir + session_start_ns`。

**录制结束后自动启动后处理**：

```python
@pyqtSlot()
def _on_recording_stopped(self):
    self._recording = False
    self._recorder.set_external_metadata(
        self._session_coordinator.stop_session()
    )
    session_path = self._recorder.finalize()  # 写 CSV 和 JSON
    self._recorder = None
    self._start_post_processing(session_path) # 启动后处理线程
```

也就是说，后处理现在已经能“看见”多模态 summary，但它还不会真正 export / validate 这些外模态数据。

### 4.10 MmWaveDriver 雷达驱动

`MmWaveDriver` 是 TI IWR6843ISK 的持久化采集器，设计上刻意拆成两个阶段：

- `prepare()`：打开 CLI/Data 两个串口、下发 `profile_human.cfg`、启动后台 reader 线程。
- `start_session()/stop_session()`：仅负责把写盘目标绑定到当前 MACS 会话目录。

这意味着雷达不会在每次点击 Start 时重复重启，而是保持 warm 状态，只在会话开始时切换输出目录。

**输出格式**：

```
session_xxx/mmwave/
├── frames.bin         原始 packet 字节流顺序拼接
└── timestamps.csv     frame_idx, timestamp_ns, num_points
```

实现上它有两个值得特别注意的技术点：

1. **reader / writer 分离**：串口读取线程只做 packet 提取与入队，真实写盘由独立 writer 线程完成。
2. **弱解析、强保真**：当前只从 header 提取 `num_points`，TLV 本体仍保持原始二进制，不在采集时做重解析。

这种设计避免了在串口线程里做重 CPU 或重 I/O 操作，但也意味着 downstream 如果要做点云级分析，需要再单独解码 `frames.bin`。

### 4.11 ImuDriver BLE IMU 驱动

`ImuDriver` 负责多设备 WitMotion WT9011DCL-BT50 的长期 BLE 采集。它和相机驱动完全不同，不是 `QThread` 拉帧模型，而是：

- 一个后台 Python 线程承载 asyncio 事件循环。
- 每个设备一个 `_ImuDeviceRunner` 协程。
- 建链过程通过 `asyncio.Lock` 串行化，避免 BlueZ `Operation already in progress`。
- BLE scan 结果被缓存，用扫描到的 `BLEDevice` 优先连接，而不是盲连 MAC 字符串。

**数据路径**：

```
FFE4 notify bytes
    → _Wt901StreamParser 拆 20-byte frame
    → _parse_measurement_frame 解 acc/gyro/angle
    → host receive timestamp_ns
    → session_dir/imu/<label>.csv
```

每个 IMU label 都有独立 CSV 文件，字段固定为：

```csv
timestamp_ns,acc_x,acc_y,acc_z,gyro_x,gyro_y,gyro_z,angle_x,angle_y,angle_z
```

`ImuDriver` 现在还承担了可观测性职责：

- `active_devices`：当前配置真正启用的 label 集合。
- `scan_visible_devices`：BLE 扫描中看见且在配置内的设备名。
- `devices[*].recent_events`：最近 25 条阶段事件，用于排查在哪个阶段失败。
- `last_first_notify_latency_ms` / `last_failure_stage` / `disconnect_count`：用于定位不稳定设备。

要强调的一点是：IMU 时间戳是 **主机收到 notify 的时间**，不是设备内部硬件时钟，因此它只能实现“共享主机时间线”，不能等价于严格硬件同步。

### 4.12 SessionCoordinator 外设会话协调器

`SessionCoordinator` 是一个非常薄但非常关键的适配层。它不生产 session，只做三件事：

1. `prepare()`：预热所有启用的外设。
2. `start_session(session_dir, session_start_ns)`：把外设绑定到相机会话。
3. `stop_session()/discard_session()`：返回可序列化 summary，供 `SessionRecorder` 写入 `session_meta.json`。

这使得 UI 主程序、`multimodal_smoke_test.py`、后续可能的新入口都能共用同一外设生命周期抽象，而不必重复写 mmWave / IMU 的 session 管理逻辑。

---

## 5. 后处理层

后处理层是当前代码库中“最像单模态遗留系统”的部分。虽然 raw 会话目录已经包含 mmWave / IMU，且 `session_meta.json` 会保留它们的 summary，但 `Segmenter / FrameExporter / Validator / PostProcessor` 仍然硬编码为四种相机模态：`RGB / Depth / IR / Thermal`。因此，当前的 processed 目录是 **相机完备、外模态缺席** 的。

录制结束后，`PostProcessor(QThread)` 在后台执行 5 步流水线，通过 `progress(int, str)` 信号实时更新 UI 标题栏。

### 5.1 Segmenter 分段器

**输入**：`data/raw/session_XXXXXXXX_XXXXXX/`  
**输出**：`List[ActionSegment]`（每个动作一个对象，包含该动作的所有帧引用）

**工作流程**：

```
1. 读 session_meta.json → 获取 labels、breakpoints、save_formats
2. 读 timestamps.csv    → 每行解析为 FrameRef（含磁盘路径）
3. 按 label 分组         → 每个 label 一个 ActionSegment
4. 计算每段的 start/end timestamp_ns
```

**ActionSegment 数据结构**：

```python
@dataclass
class ActionSegment:
    label: str                       # "walk"
    start_timestamp_ns: int          # 该动作第一帧的时间戳
    end_timestamp_ns: int            # 该动作最后一帧的时间戳
    frames: Dict[str, List[FrameRef]]  # {"RGB": [...], "Depth": [...], ...}
```

**FrameRef 数据结构**：

```python
@dataclass
class FrameRef:
    seq: int           # 帧序号
    modality: str      # "RGB"
    timestamp_ns: int  # 时间戳
    label: str         # "walk"
    path: Path         # data/raw/session_.../RGB/frame_000000.jpg
```

### 5.2 FrameExporter 帧导出器

**针对每种模态的处理差异**：

#### RGB
- 源文件：`.jpg`（已压缩），直接 `cv2.imread` 读取
- 输出帧：`.png`（无损，供后续分析用）
- 视频：`MJPG` 编码 `.avi`

#### Depth（深度图）
- 源文件：`.npy`（uint16，值为毫米距离）
- 保留原始数值：输出 `.npy`（供数值分析）
- 可视化：JET 伪彩色 `.png` + 编入视频

```python
@staticmethod
def _colorize_depth(depth):
    max_val = np.max(depth) if np.max(depth) > 0 else 1
    norm = (depth.astype(np.float32) / max_val * 255).astype(np.uint8)
    return cv2.applyColorMap(norm, cv2.COLORMAP_JET)
    # 近处=蓝色, 远处=红色 (JET colormap)
```

#### IR（红外图）
- 源文件：`.npy`（uint8 或 uint16）
- 保留原始数值：`.npy`
- 归一化可视化：`cv2.normalize → uint8` 灰度图 → 编入视频

#### Thermal（热像）
- 源文件：`.jpg`（已是伪彩色 BGR 图）
- 直接复制为 `.png`，编入视频

**输出目录结构**（每个动作）：

```
data/processed/session_XXXXXXXX_XXXXXX/
└── walk/
    ├── RGB_video/rgb.avi
    ├── RGB_frames/frame_000000.png  frame_000001.png  ...
    ├── Depth_video/depth_colorized.avi
    ├── Depth_frames/frame_000000.npy  frame_000000.png  ...
    ├── IR_video/ir.avi
    ├── IR_frames/frame_000000.npy  frame_000000.png  ...
    ├── Thermal_video/thermal.avi
    ├── Thermal_frames/frame_000000.png  ...
    └── metadata.json
```

### 5.3 Validator 验证器

对每个动作目录进行完整性检查：

**检查项**：

1. **逐模态帧目录是否存在**
2. **计数 PNG 文件数量**（Depth/IR 额外有 npy，但用 png 数量代表有效帧数）
3. **NYX650 三路帧数是否一致**：RGB/Depth/IR 帧数相差 > 0 则报 warning（同一相机触发同步，不应差太多）
4. **视频文件是否存在**
5. **最大帧间同步漂移**（段内 RGB 帧 vs 最近 Thermal 帧的距离）

**写出 metadata.json**：

```json
{
  "action_label": "walk",
  "session_id": "20260401_190000",
  "duration_sec": 45.0,
  "frame_count": {"RGB": 675, "Depth": 675, "IR": 675, "Thermal": 1125},
  "resolution": {"RGB": [1600, 1200], "Depth": [640, 480], ...},
  "fps": {"RGB": 15, "Depth": 15, "IR": 15, "Thermal": 25},
  "sync_max_drift_ms": 18.4,
  "start_timestamp_ns": 1743504000000000000,
  "end_timestamp_ns": 1743504045000000000,
  "validation_warnings": []
}
```

### 5.4 PostProcessor 后处理流水线

进度报告机制：用 `progress.emit(percent, text)` 信号更新 UI：

```
5%   → Parsing session metadata
10%  → Found 3 action(s)
10%~80% → Exporting [1/3] walk / [2/3] sit / [3/3] read
           (每 20 帧 emit 一次进度，避免信号洪水)
80%~95% → Validating actions
95%  → Writing session report
100% → Done
```

完成后 emit `finished_ok(output_dir)` → `CaptureController._on_pp_ok()` → `MainWindow.on_post_processing_done()` → 弹出完成对话框，UI 回到 IDLE。

**session_report.json** 汇总全局信息：

```json
{
  "labels": ["walk", "sit", "read"],
  "num_actions": 3,
  "recording_duration_sec": 90.0,
  "processing_duration_sec": 12.3,
  "all_valid": true,
  "actions": [
    {"label": "walk", "frame_counts": {...}, "duration_sec": 45.0, "validation_ok": true, "warnings": []},
    ...
  ]
}
```

---

## 6. 配置系统

`config/default.yaml` 现在已经演变成 5 个逻辑名字空间：`camera`、`recording`、`health`、`ui`、`multimodal`。其中 `multimodal` 是本轮架构扩展的核心。

```yaml
camera:
  nyx650:
    rgb:   {width: 1600, height: 1200, fps: 15}
    depth: {width: 640,  height: 480,  fps: 15}
    ir:    {width: 640,  height: 480,  fps: 15}
  tb4117:
    device_index: 0        # -1 = 自动检测，固定值跳过扫描
    thermal:
      width: 120            # 实际固件报告宽度（竖向方向）
      height: 160           # 实际固件报告高度
      fps: 25
      pixelformat: "MJPG"   # MJPG 带宽低且速度快

recording:
  output_dir: "data"
    raw_subdir: "raw"
    processed_subdir: "processed"
  save_format:
        RGB: "jpg"
        Depth: "npy"
        IR: "npy"
        Thermal: "jpg"
    jpg_quality: 95

health:
    fps_warn_ratio: 0.7
    frame_loss_threshold: 10
    sync_drift_threshold_ms: 66
    disk_min_gb: 1.0

ui:
    status_update_interval_ms: 500

multimodal:
    mmwave:
        enabled: true
        cli_port: "/dev/ttyUSB0"
        data_port: "/dev/ttyUSB1"
        cli_baudrate: 115200
        data_baudrate: 921600
        writer_queue_size: 512
        config_path: "config/profile_human.cfg"

    imu:
        enabled: true
        sample_rate_hz: 50
        connect_timeout_s: 20
        connect_stagger_s: 2.0
        scan_warmup_s: 10.0
        retry_scan_s: 5.0
        ready_timeout_s: 60
        active_devices: []
        devices:
            - label: "imu01_left_wrist"
                mac: "DC:E1:B0:1F:67:6E"
                enabled: true
            - label: "imu02_right_wrist"
                mac: "E5:9E:9B:1F:CE:48"
                enabled: false
```

配置系统现在有 3 层 IMU 选择语义：

1. `multimodal.imu.enabled`：整套 IMU 采集总开关。
2. `multimodal.imu.devices[*].enabled`：适合把 5 个 IMU 固定分配给不同树莓派的长期静态开关。
3. `multimodal.imu.active_devices`：适合同一份配置内做临时白名单。

运行时，`runtime_config.resolve_enabled_imu_devices()` 会先过滤设备级 `enabled`，再过滤 `active_devices`；命令行的 `--imu-device <label>` 则通过 `apply_runtime_imu_selection()` 覆盖内存里的 `active_devices`，不会改写磁盘配置文件。

各模块仍然通过 `config.get(...).get(...)` 逐级安全取值，但要注意：当前代码还没有 schema 校验，非法键名或字段类型错误通常要等到运行时才暴露出来。

---

## 7. 数据目录结构

```
data/
├── raw/
│   └── session_20260401_190000/    每次点击 Start 创建
│       ├── session_meta.json
│       ├── timestamps.csv
│       ├── RGB/frame_000000.jpg ...
│       ├── Depth/frame_000000.npy ...
│       ├── IR/frame_000000.npy ...
│       ├── Thermal/frame_000000.jpg ...
│       ├── mmwave/
│       │   ├── frames.bin
│       │   └── timestamps.csv
│       └── imu/
│           ├── imu01_left_wrist.csv
│           ├── imu03_waist.csv
│           └── ...
│
└── processed/
    └── session_20260401_190000/    后处理完成后创建（同名）
        ├── session_report.json
        ├── walk/
        │   ├── metadata.json
        │   ├── RGB_video/rgb.avi
        │   ├── RGB_frames/frame_000000.png ...
        │   ├── Depth_video/depth_colorized.avi
        │   ├── Depth_frames/frame_000000.npy  frame_000000.png ...
        │   ├── IR_video/ir.avi
        │   ├── IR_frames/frame_000000.npy  frame_000000.png ...
        │   ├── Thermal_video/thermal.avi
        │   └── Thermal_frames/frame_000000.png ...
        ├── sit/
        │   └── ...
        └── read/
            └── ...
```

这个目录结构体现了当前系统的一个真实边界：

- `raw/` 已经是完整多模态采集结果。
- `processed/` 目前仍然只是相机四模态的动作级重组织结果。

因此，如果你当前要做 mmWave / IMU 下游分析，原始数据入口仍然是 `raw/session_xxx/mmwave` 与 `raw/session_xxx/imu`，而不是 `processed/`。

---

## 8. 线程模型与信号流

```
主线程 (Qt Event Loop)
│
├── main.py
│   → load_config()
│   → apply_runtime_imu_selection()
│   → CaptureController.initialize()
│
├── QTimer 500ms → CaptureController._refresh_status()
│                    → HealthMonitor.tick()
│                    → SessionCoordinator.get_summary()
│                    → StatusPanel.update_fps/sync/imu/health()
│
├── QTimer 500ms → MainWindow._on_tick()
│                    → StatusPanel.update_disk()/refresh_timer()
│
├── frame_received(str, ndarray, float) 信号 [Qt::QueuedConnection]
│   ← 来自相机线程，Qt 自动跨线程排队
│   → MainWindow._on_frame_received()
│       → PreviewPanel.update_frame()
│
└── CaptureController._on_frame() [主线程 slot]
    ← 接收来自相机线程的 frame_captured 信号
    → FPSCounter.tick()
    → SyncManager.record_timestamp()
    → win.frame_received.emit()         → UI 预览
    → SessionRecorder.write_frame()
        → AsyncFrameWriter._queue.put_nowait()

写盘线程 (AsyncFrameWriter, Python threading.Thread)
└── queue.get(timeout=0.25) → _write() → np.save / cv2.imwrite

采集线程 1 (NYX650Driver, QThread)
└── scGetFrameReady() 阻塞 → 解析帧 → frame_captured.emit()

采集线程 2 (TB4117Driver, QThread)
└── cap.read() 阻塞 → 裁剪 → frame_captured.emit()

mmWave reader 线程 (Python threading.Thread)
└── serial.read() → magic word 对齐 → extract packet → writer_queue.put_nowait()

mmWave writer 线程 (Python threading.Thread)
└── queue.get() → frames.bin / timestamps.csv

IMU asyncio 线程 (Python threading.Thread + event loop)
└── refresh_scan_cache()
    ├── _ImuDeviceRunner(label_1)
    ├── _ImuDeviceRunner(label_2)
    └── ...
        └── connect → write_gatt_char → start_notify → parse notify frame

IMU CSV writer 线程 (Python threading.Thread)
└── queue.get() → <label>.csv writer.writerow()

后处理线程 (PostProcessor, QThread, 仅在录制结束后存在)
└── Segmenter → FrameExporter → Validator → progress.emit()
```

**跨线程安全保证**：
- 相机线程通过 `emit` 把帧数据交给 Qt 信号系统，Qt 自动用 `QueuedConnection` 把槽函数调用排队到主线程执行，无需手动加锁
- `SyncManager` 和 `HealthMonitor` 内部用 `threading.Lock` 保护共享状态。
- mmWave 通过有界 `queue.Queue(maxsize=writer_queue_size)` 隔离串口读取与磁盘写入。
- IMU 通过 `asyncio.Lock` 串行化 BLE 建链，通过单独 CSV writer 线程把 notify 回调从磁盘 I/O 中解耦。
- `SessionCoordinator.get_summary()` 返回纯 Python 可序列化结构，因此可以被 UI、smoke test、session meta 共同消费。

---

## 9. Demo 模式

`DemoFrameGenerator` 用于不接相机的测试，每 67ms（≈15fps 节奏）合成一帧。它只模拟 `RGB/Depth/IR/Thermal`，不会模拟 mmWave 或 IMU，所以它更接近“UI 演示模式”而不是“全链路系统仿真模式”：

```python
def _generate(self):
    if self._win.state.name != "RECORDING":
        return       # 只在录制状态生成帧，不占用资源

    # RGB: 渐变背景 + 水平滚动的绿色竖条
    # Depth: 4000mm 背景 + 1200mm 的圆形物体（位置随时间移动）
    # IR: 随机噪声背景 + 移动高亮点
    # Thermal: 黑色背景 + 红色热源（位置随时间移动）
```

同时模拟状态栏数据（固定 FPS、随时间变化的同步漂移），让整个 UI 在没有硬件时也能正常工作。

---

## 10. 键盘快捷键

| 键 | 状态 | 效果 |
|----|------|------|
| `Space` | IDLE（非标签输入框焦点） | 等同于点击 Start |
| `B` | RECORDING | 标记 Breakpoint |
| `Esc` | RECORDING | 等同于点击 Stop |
| `C` | RECORDING | 等同于点击 Cancel（会弹确认框） |

---

## 11. 多模态诊断与运维工具

随着 mmWave / IMU 引入，MACS 已经不适合只靠 UI 点 Start 来排查问题。当前代码库里实际可用的诊断入口有 3 个：

### 11.1 setup_check.py

`setup_check.py` 是环境级体检工具，负责检查：

- Python 版本和核心依赖包。
- NYX650 SDK 路径与导入情况。
- `/dev/video*` 与 `v4l2-ctl` 探测结果。
- mmWave CP2105 串口桥与 Bluetooth 适配器可用性。
- 磁盘空间和 USB 枚举结果。

它适合在一台新树莓派刚部署完、还没开始录制之前执行，用来回答“环境是否具备最起码的运行条件”。

### 11.2 tools/multimodal_smoke_test.py

这是 **不启动 UI** 的外设冒烟测试入口，直接复用 `SessionCoordinator`：

```bash
python3 tools/multimodal_smoke_test.py \
    --config config/default.yaml \
    --imu-device imu03_waist \
    --imu-device imu04_left_ankle \
    --duration 15 \
    --imu-ready-timeout 20
```

它最适合回答两个问题：

- 外设在当前配置下能不能准备成功。
- 在不掺杂 UI、相机线程和后处理的情况下，mmWave / IMU 能不能稳定写到会话目录。

### 11.3 tools/ble_imu_diagnose.py

这是专门为 WitMotion IMU 提供的 BLE 级诊断工具，路径上完全绕开 MACS session pipeline。它会对配置中的 IMU 做：

1. BLE 扫描。
2. connect。
3. GATT service / characteristic 验证。
4. sample rate 写入。
5. notify 窗口内帧统计。

这个工具适合回答“到底是 BlueZ / BLE 本身不稳，还是 MACS 生产路径上的会话写盘 / 调度放大了问题”。

## 12. 批判性评审与优化建议

下面这一节不是功能清单，而是从 ACM 教授 / 资深系统工程师角度，对这套系统中 **已经解决、但还没有被深度解决** 的问题进行逆向审视。

### 12.1 多模态时间同步仍然只是“共享会话起点”，不是严格同步

当前系统做对了两件事：

- 所有模态共用同一个 `session_dir`。
- 所有模态共用同一个 `session_start_ns`。

但这离“严格多模态同步”还有明显距离。相机有各自驱动时间线，mmWave 时间戳取自主机收到 packet 的时间，IMU 时间戳取自主机收到 BLE notify 的时间。换言之，系统现在实现的是 **shared host-time anchoring**，不是硬件触发同步，也不是经过时延建模校正后的统一时钟。

如果后续目标是论文级多模态对齐或定量行为分析，那么当前模型还缺：

- 设备到主机的链路时延分布建模。
- 各模态时钟偏差与漂移标定。
- 可重复的同步基准事件。
- 动作级、会话级的跨模态对齐误差报告。

### 12.2 后处理流水线仍然是“相机中心”的，外模态只停留在 raw 层

这是当前架构最显著的结构性缺口之一。

- `Segmenter.ALL_MODALITIES` 只包含 `RGB/Depth/IR/Thermal`。
- `FrameExporter` 只实现四种相机导出函数。
- `Validator` 只验证四种相机输出。
- `session_report.json` 的完整性判断也只基于相机动作导出结果。

这意味着当前系统虽然已经能采到 mmWave 和 IMU，但它们还没有真正被纳入“标准数据产品”。从研究产出角度看，这会带来一个隐性风险：**采集层已经多模态，分析层仍然单模态**。

建议优先级很高的下一步是：

1. 为外模态建立 segment-level 索引与导出规范。
2. 在 processed/ 中加入 `imu/` 与 `mmwave/` 的动作级组织形式。
3. 把外模态完整性验证纳入 `metadata.json` 与 `session_report.json`。

### 12.3 健康监控对外部模态几乎是盲的

`HealthMonitor.ALL_MODALITIES` 仍然硬编码为四种相机模态。它会检查 FPS、断帧、相机断连、同步漂移和磁盘空间，但不会检查：

- IMU 是否全部掉线。
- 某个 IMU 是否只有表头、没有数据。
- mmWave writer queue 是否已经开始丢包。
- mmWave / IMU 的 writer errors 是否持续累积。

这会导致一种很危险的错觉：UI 显示 `Health OK`，但外模态可能已经部分或全部失效。

下一步应该把外模态的健康语义正式引入：

- IMU connected ratio。
- IMU first-notify latency。
- mmWave queue depth / dropped count。
- 外模态长时间无样本的 timeout 判据。

### 12.4 auto-pause 的语义当前并不闭合

`CaptureController._on_auto_pause()` 当前只做了两件事：

- `self._recording = False`
- `self._win.status_panel.update_health("ERROR")`

但它没有：

- 调用 `SessionCoordinator.stop_session()`。
- 调用 `SessionRecorder.finalize()`。
- 显式停止 mmWave / IMU 的当前会话写盘。

结果是“相机不再写入 SessionRecorder，但外部模态仍可能继续写各自文件”。从系统语义看，这不是一个真正的 pause，而是一个 **partial write stop**。如果后续要保留 auto-pause 机制，它至少应该定义清楚：暂停的是全部模态，还是只有相机主链路。

### 12.5 启动路径把外设预热放在 UI 主路径上，扩展后会越来越重

`main.py` 在进入 Qt 事件循环之前调用 `controller.initialize()`；而 `initialize()` 内部会同步调用 `SessionCoordinator.prepare()`。这意味着：

- mmWave 串口配置。
- IMU BLE 扫描。
- IMU 初始连接等待。

都发生在 UI 主启动路径上。`ImuDriver.prepare()` 甚至会等待 `_initial_attempts_done` 直到 `ready_timeout_s`。随着设备数量上升，这个路径会越来越重，最终表现为“窗口出来慢、启动阶段看起来像卡死”。

更合理的演进方向是把 prepare 拆成：

- 非阻塞启动。
- 后台 warm-up。
- UI 中可见的 readiness state。
- 录制开始前的显式 readiness gate。

### 12.6 IMU 异步 writer 解决了回调阻塞，但引入了无界内存风险

IMU 的 CSV 写盘确实已经从 notify 回调中剥离出来，这是正确方向；但 `_ImuSessionState.activate()` 里使用的是无界 `queue.Queue()`。这意味着在下列情况下：

- SD 卡抖动。
- 文件系统瞬时变慢。
- 蓝牙数据持续涌入。

队列会无限增长，系统会用内存去吸收 I/O 失配，而不是显式暴露背压。这是一个典型的“把阻塞问题换成内存问题”的设计折中，还没有完全闭环。

建议方向是：

- 改成有界队列。
- 统计 dropped / backlog / flush latency。
- 把这些指标接入 UI 与健康监控。

### 12.7 数据模型仍然缺一张统一的多模态事件索引表

当前系统的数据组织是分裂的：

- 相机四模态有统一 `timestamps.csv`。
- mmWave 有自己的 `timestamps.csv`。
- 每个 IMU 各有一份 CSV。
- `session_meta.json` 只保存 summary，不保存逐事件级统一索引。

这对于工程实现很方便，但对于跨模态检索和离线研究并不理想。未来一旦要做：

- 给定时间窗回放所有模态。
- 动作切换点附近的多模态联合切片。
- 多设备跨会话对比。

你会很快发现缺一张统一索引表会显著增加数据工程复杂度。

### 12.8 配置治理和自动化验证还不够工程化

现在的配置系统已经足够灵活，但工程化程度还不够高：

- 没有 schema 校验。
- 没有配置版本号。
- 没有自动化集成测试目录。
- 没有覆盖“相机 + mmWave + IMU + 后处理”的回归测试。

这会导致一个典型问题：系统越复杂，越依赖人工 smoke test 和记忆里的操作经验。短期内还能靠作者本人维持，长期则会变成知识债务。

更成熟的路线应包括：

1. 配置 schema 与启动前校验。
2. 最小可复现 smoke test 套件。
3. 针对多模态 `session_meta.json` 的回归检查。
4. 针对后处理产物结构的自动化验证。

---

*文档基于 2026-04-23 的 MACS 代码状态更新，已纳入 mmWave / IMU 扩展、运行时 IMU 设备筛选、StatusPanel 外设显示，以及一份批判性架构评审。*
