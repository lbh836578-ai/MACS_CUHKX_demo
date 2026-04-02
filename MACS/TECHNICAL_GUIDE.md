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

---

## 1. 系统总架构

```
┌─────────────────────────────────────────────────────┐
│                      main.py                        │
│   加载 config → 创建 QApplication → 创建 MainWindow  │
│   生产模式: 创建 CaptureController                   │
│   Demo 模式: 创建 DemoFrameGenerator                 │
└──────────────────────┬──────────────────────────────┘
                       │
         ┌─────────────▼──────────────┐
         │         UI 层               │
         │   MainWindow (状态机)        │
         │   ├── ControlPanel          │
         │   ├── PreviewPanel (2×2)    │
         │   └── StatusPanel           │
         └─────────────┬──────────────┘
                       │ Qt Signals (跨线程安全)
         ┌─────────────▼──────────────┐
         │       CaptureController    │
         │   (主线程 QObject)          │
         │   ├── NYX650Driver (线程)   │
         │   ├── TB4117Driver (线程)   │
         │   ├── FPSCounter × 4       │
         │   ├── SyncManager          │
         │   ├── HealthMonitor        │
         │   └── SessionRecorder      │
         │       └── AsyncFrameWriter │
         └─────────────┬──────────────┘
                       │ 录制结束后启动
         ┌─────────────▼──────────────┐
         │     后处理层 (线程)          │
         │   PostProcessor            │
         │   ├── Segmenter            │
         │   ├── FrameExporter        │
         │   └── Validator            │
         └────────────────────────────┘
```

整个系统有 **3 个运行层**：
- **UI 主线程**：PyQt5 事件循环，绝对不能阻塞
- **采集线程×2**：NYX650Driver、TB4117Driver 各跑一个 QThread
- **写盘线程**：AsyncFrameWriter 用 Python threading.Thread 异步写文件，让采集线程不被 I/O 卡住
- **后处理线程**：PostProcessor 是 QThread，录制结束后自动启动

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
if args.demo:
    generator = DemoFrameGenerator(window)
else:
    from capture.capture_controller import CaptureController
    controller = CaptureController(config, window)
    controller.initialize()
    app.aboutToQuit.connect(controller.shutdown)
```

生产模式下 `CaptureController` 在 `initialize()` 里启动相机线程。`app.aboutToQuit` 信号确保窗口关闭时 `shutdown()` 被调用，相机线程被正确停止和释放。

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

固定高度 28px 的深色横条，包含 5 个 QLabel：

```
FPS  RGB:15.0 | D:15.0 | IR:15.0 | T:25.0    Sync 12.3ms   📁 23.4GB    OK    00:01:23
└── _fps_lbl ──────────────────────────┘  └─_sync_lbl─┘  └─_disk_lbl┘  └─health┘  └─timer┘
```

**同步漂移颜色编码**：
- `drift < 33ms` → 绿色 `#4CAF50`（良好）
- `33ms ≤ drift < 66ms` → 橙色（警告）
- `drift ≥ 66ms` → 红色（超过一帧时长，需要注意）

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

#### 目录结构

```
data/raw/session_20260401_190000/
├── session_meta.json     会话元数据
├── timestamps.csv        每帧时间戳索引
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
└── Thermal/
    ├── frame_000000.jpg
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
  "save_formats": {"RGB": "jpg", "Depth": "npy", "IR": "npy", "Thermal": "jpg"}
}
```

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

**`_on_frame()` 是最高频调用**（每秒 70 次）：

```python
@pyqtSlot(str, object, object)
def _on_frame(self, modality, frame, timestamp_ns):
    fps_val = self._fps[modality].tick()         # 更新FPS计数
    self._sync.record_timestamp(modality, timestamp_ns)  # 更新同步追踪
    self._win.frame_received.emit(modality, frame, fps_val)  # 发给UI预览

    if self._recording and self._recorder is not None:
        self._recorder.write_frame(modality, frame, timestamp_ns)  # 写盘
```

**录制结束后自动启动后处理**：

```python
@pyqtSlot()
def _on_recording_stopped(self):
    self._recording = False
    session_path = self._recorder.finalize()  # 写 CSV 和 JSON
    self._recorder = None
    self._start_post_processing(session_path) # 启动后处理线程
```

---

## 5. 后处理层

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

`config/default.yaml` 是唯一配置入口，`yaml.safe_load` 解析后以 `dict` 形式传给各个模块：

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
  save_format:
    RGB: "jpg"       # 有损压缩，节省空间
    Depth: "npy"     # 保留完整 uint16 数值（mm 单位）
    IR: "npy"        # 保留原始数值
    Thermal: "jpg"   # 已是伪彩色图，jpg 足够
  jpg_quality: 95    # JPEG 质量系数

health:
  fps_warn_ratio: 0.7          # FPS告警线 = 目标×0.7
  frame_loss_threshold: 10     # 连续N次无帧则auto-pause
  sync_drift_threshold_ms: 66  # 超过一帧时长的漂移
  disk_min_gb: 1.0             # 最低磁盘剩余量

ui:
  status_update_interval_ms: 500  # 状态栏刷新间隔
```

各模块通过 `config.get("camera", {}).get("nyx650", {})` 逐级安全取值，未配置的键使用硬编码默认值。

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
│       └── Thermal/frame_000000.jpg ...
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

---

## 8. 线程模型与信号流

```
主线程 (Qt Event Loop)
│
├── QTimer 500ms → CaptureController._refresh_status()
│                    → HealthMonitor.tick()
│                    → StatusPanel 更新
│
├── QTimer 500ms → MainWindow._on_tick()
│                    → StatusPanel 磁盘/计时器更新
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

后处理线程 (PostProcessor, QThread, 仅在录制结束后存在)
└── Segmenter → FrameExporter → Validator → progress.emit()
```

**跨线程安全保证**：
- 相机线程通过 `emit` 把帧数据交给 Qt 信号系统，Qt 自动用 `QueuedConnection` 把槽函数调用排队到主线程执行，无需手动加锁
- `SyncManager` 和 `HealthMonitor` 内部用 `threading.Lock` 保护共享状态（因为虽然 slot 在主线程执行，但 `HealthMonitor.set_camera_connected()` 可能从不同点调用）
- `AsyncFrameWriter` 用 `queue.Queue`（线程安全）在采集侧 put、写盘侧 get

---

## 9. Demo 模式

`DemoFrameGenerator` 用于不接相机的测试，每 67ms（≈15fps 节奏）合成一帧：

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

*文档基于代码版本 2026-04-02 生成，覆盖所有 .py 源文件。*
