# MultiModal Action Capture System (MACS)

> 基于 Scepter NYX650 (ToF) + HikVision TB4117 (Thermal) 双相机同步多模态动作数据采集系统
>
> 运行平台：Raspberry Pi 4B (8GB) → 后期迁移至 Jetson Orin

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 系统架构](#2-系统架构)
- [3. 硬件需求](#3-硬件需求)
- [4. 软件依赖](#4-软件依赖)
- [5. 安装与配置](#5-安装与配置)
- [6. 数据模态说明](#6-数据模态说明)
- [7. 采集 UI 操作流程](#7-采集-ui-操作流程)
- [8. 同步与健康监测机制](#8-同步与健康监测机制)
- [9. 数据后处理流水线](#9-数据后处理流水线)
- [10. 输出目录结构](#10-输出目录结构)
- [11. 已知限制与后续规划](#11-已知限制与后续规划)
- [12. 快速开始](#12-快速开始)
- [13. 项目代码结构](#13-项目代码结构)

---

## 1. 项目概述

本系统用于采集人体动作的多模态同步数据，服务于下游动作识别与行为分析等研究任务。

系统通过两台相机同步工作，单次录制可采集 **4 种模态**（RGB、Depth、IR、Thermal），并支持用户在一次连续录制中标注多个动作片段（Breakpoint 机制）。录制结束后自动按动作标签切分数据并归档到标准化目录结构中。

### 核心特性

- **双相机同步采集**：NYX650 提供 RGB + Depth + IR，TB4117 提供 Thermal
- **交互式 UI**：动作标签输入、开始 / 断点 / 结束控制、实时预览
- **4 模态健康监测**：实时检测帧丢失、相机掉线、同步偏移
- **自动后处理**：按动作标签切分 → 抽帧 → 归档到标准目录结构
- **可迁移架构**：Pi 4B 开发验证，Jetson Orin 部署生产

---

## 2. 系统架构

```
┌─────────────────────────── Capture UI (PyQt5) ────────────────────────────┐
│                                                                           │
│  ┌──────────────┐  ┌────────────┐  ┌──────────────┐  ┌───────────────┐   │
│  │ Label Input   │  │ Start Btn  │  │ Breakpoint   │  │ Stop Btn      │   │
│  │ "walk-sit-   │  │            │  │ Btn          │  │               │   │
│  │  read"        │  │            │  │              │  │               │   │
│  └──────────────┘  └─────┬──────┘  └──────┬───────┘  └───────┬───────┘   │
│                          │                │                   │           │
│  ┌───────────────────────┴────────────────┴───────────────────┘           │
│  │         Preview Panel (4-grid: RGB / Depth / IR / Thermal)             │
│  └────────────────────────────────────────────────────────────┘           │
│                                                                           │
│  ┌────────────────────────────────────────────────────────────┐           │
│  │       Status Bar: FPS | Sync Δt | Disk Usage | Health      │           │
│  └────────────────────────────────────────────────────────────┘           │
└───────────────────────────────────────────────────────────────────────────┘
        │                          │                        │
        ▼                          ▼                        ▼
┌──────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│  Camera Module    │  │ Sync & Health Monitor  │  │  Post-Processor        │
│                   │  │                        │  │                        │
│  NYX650 Driver    │  │ - Frame timestamp      │  │  - Segment by label   │
│  ├─ RGB stream    │  │   alignment check      │  │  - Export video clips │
│  ├─ Depth stream  │  │ - Modality liveness    │  │  - Extract frames     │
│  └─ IR stream     │  │   heartbeat            │  │  - Organize folders   │
│                   │  │ - Drift compensation   │  │                        │
│  TB4117 Driver    │  │ - Alert & auto-pause   │  │  (runs in background  │
│  └─ Thermal strm  │  │                        │  │   after recording)    │
└──────────────────┘  └────────────────────────┘  └────────────────────────┘
        │                                                    │
        ▼                                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                     Storage (USB 3.0 SSD recommended)                     │
│                                                                           │
│  raw/                               processed/                            │
│  └─ session_20260330_143000/        └─ session_20260330_143000/           │
│     ├─ nyx650_rgb.avi                  ├─ walk/                           │
│     ├─ nyx650_depth/                   │  ├─ RGB_video/                   │
│     ├─ nyx650_ir/                      │  ├─ RGB_frames/                  │
│     ├─ tb4117_thermal.avi              │  ├─ Depth_video/                 │
│     ├─ timestamps.csv                  │  ├─ Depth_frames/                │
│     └─ breakpoints.json               │  ├─ IR_video/                    │
│                                        │  ├─ IR_frames/                   │
│                                        │  ├─ Thermal_video/               │
│                                        │  └─ Thermal_frames/              │
│                                        ├─ sit/                            │
│                                        │  └─ ...                          │
│                                        └─ read/                           │
│                                           └─ ...                          │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 硬件需求

| 组件 | 型号 / 规格 | 备注 |
|------|------------|------|
| 计算平台 | Raspberry Pi 4B (8 GB) | 后期迁移至 Jetson Orin |
| ToF 相机 | Scepter NYX650 | USB 连接，提供 RGB + Depth + IR |
| 热成像相机 | HikVision TB4117 | 连接方式 TBD（USB / RTSP / SDK） |
| 存储 | USB 3.0 外接 SSD（≥ 256 GB） | **强烈推荐**，SD 卡写入速度不足 |
| USB Hub | USB 3.0 有源 Hub | 双相机同时供电需充足电流 |
| 电源 | 5V / 3A 官方电源（Pi） | 外设多时供电不足会导致设备掉线 |

---

## 4. 软件依赖

```
Python >= 3.8
├── opencv-python >= 4.5
├── numpy >= 1.21
├── PyQt5                        # UI 框架
├── ScepterSDK Python API        # NYX650 驱动
├── HikVision SDK / hikvisionapi # TB4117 驱动（TBD）
└── threading / multiprocessing  # 并发控制
```

---

## 5. 安装与配置

### 5.1 NYX650（Scepter SDK）

```bash
cd ~
git clone https://github.com/ScepterSW/ScepterSDK.git ~/ScepterSDK

ls ~/ScepterSDK/BaseSDK/AArch64/PrecompiledSamples
ls ~/ScepterSDK/MultilanguageSDK/Python/API
ls ~/ScepterSDK/MultilanguageSDK/Python/Samples/NYX650/DeviceConnectBySN


# SDK 已部署在如下路径
ls ~/ScepterSDK/BaseSDK/AArch64/PrecompiledSamples/NYX650_Samples/

# 验证预编译 Sample 可正常运行
cd ~/ScepterSDK/BaseSDK/AArch64/PrecompiledSamples/NYX650_Samples/
bash ./NYX650_OpenCVSample

cd ~/ScepterSDK/BaseSDK/AArch64/PrecompiledSamples
chmod +x ./NYX650_OpenCVSample
./NYX650_OpenCVSample

# 验证 Python API
cd ~/ScepterSDK/MultilanguageSDK/Python/Samples/NYX650/DeviceConnectBySN
python3 DeviceConnectBySN.py
```

设置临时网口ip
```
#先看你的接口名：
nmcli device status
ip -br addr
ip route
ip -br link
```

给这张口设一个临时静态 IP。下面用 eth0 和 192.168.1.100/24 举例，前提是你的 NYX650 IP 在同一个网段，比如 192.168.1.10。
```
sudo ip addr flush dev eth0
sudo ip addr add 192.168.1.100/24 dev eth0
sudo ip link set eth0 up
ip -br addr show eth0
```

```
#能 ping 通以后再跑 sample。
cd ~/ScepterSDK/BaseSDK/AArch64/PrecompiledSamples
chmod +x ./NYX650_OpenCVSample
./NYX650_OpenCVSample
```

### 5.2 TB4117（HikVision）

```bash
# TODO: TB4117 SDK 安装与配置
# 可能方案：
#   方案 A: HikVision SDK (Linux aarch64) + Python binding
#   方案 B: RTSP 取流 → OpenCV VideoCapture
#   方案 C: HikVision 官方 Python SDK
```

### 5.3 项目安装

```bash
# no need to download the SDK, we only need to code under uvc protocal

# 首次运行配置向导（检测相机连接状态）
python3 setup_check.py
```

---

## 6. 数据模态说明

| 模态 | 来源相机 | 分辨率（典型） | 数据格式 | 帧率 | 备注 |
|------|---------|--------------|---------|------|------|
| **RGB** | NYX650 | 1600 × 1200 | 8-bit BGR | 15 fps | 标准彩色图 |
| **Depth** | NYX650 | 640 × 480 | 16-bit uint16（mm） | 15 fps | 深度值单位为毫米，不可有损压缩 |
| **IR** | NYX650 | 640 × 480 | 16-bit uint16 | 15 fps | 近红外灰度图 |
| **Thermal** | TB4117 | TBD | TBD | TBD | 热成像温度图，接入后补充 |

### 存储策略

- **RGB / Thermal**：录制期间存为 `.avi`（MJPEG）；后处理阶段抽帧为 `.png`
- **Depth / IR**：录制期间逐帧存 `.npy`（无损 16-bit）；后处理阶段额外生成伪彩色 `.png` 用于可视化，并合成为 visualization-only 的 `.avi`

---

## 7. 采集 UI 操作流程

### 7.1 操作步骤

```
1. 启动系统
   $ python3 main.py

2. 输入动作标签序列
   ┌──────────────────────────────────────────┐
   │  Action Labels: walk-sit-read            │
   │  （多个动作用 "-" 分隔）                    │
   └──────────────────────────────────────────┘

3. 点击 [▶ Start]
   → 两台相机同步开始录制
   → 4 个预览窗格实时显示 RGB / Depth / IR / Thermal
   → 状态栏显示 FPS、同步状态、磁盘用量

4. 执行第一个动作（walk），完成后点击 [⏎ Breakpoint]
   → 系统记录断点时间戳
   → UI 提示 "walk ✓ → 下一个动作: sit"

5. 执行第二个动作（sit），完成后点击 [⏎ Breakpoint]
   → 系统记录断点时间戳
   → UI 提示 "sit ✓ → 下一个动作: read"

6. 执行第三个动作（read），完成后点击 [⏹ Stop]
   → 两台相机停止录制
   → 后台启动数据后处理流水线
   → UI 显示 "Processing... ██████░░ 75%"

7. 处理完成
   → UI 显示摘要：总帧数、各动作时长、输出路径
   → 可立即开始下一轮录制
```

### 7.2 UI 按钮定义

| 按钮 | 快捷键 | 功能 |
|------|--------|------|
| **Start** | `Space` | 双相机同步开始录制 |
| **Breakpoint** | `B` | 标记当前动作结束 / 下一动作开始的时间戳 |
| **Stop** | `Esc` | 停止录制，触发后处理 |
| **Cancel** | `C` | 放弃本次录制，删除已录数据 |

### 7.3 断点（Breakpoint）机制

用户输入的标签序列 `walk-sit-read` 会被解析为 **N 个动作片段**，需要 **N-1 个断点** 来分隔。断点信息存储在 `breakpoints.json` 中：

```json
{
  "session_id": "20260330_143000",
  "labels": ["walk", "sit", "read"],
  "breakpoints": [
    {
      "index": 0,
      "label_before": "walk",
      "label_after": "sit",
      "host_timestamp_ns": 1711806612345678000,
      "nyx650_frame_id": 342,
      "tb4117_frame_id": 340
    },
    {
      "index": 1,
      "label_before": "sit",
      "label_after": "read",
      "host_timestamp_ns": 1711806645123456000,
      "nyx650_frame_id": 837,
      "tb4117_frame_id": 834
    }
  ],
  "recording_start_ns": 1711806590000000000,
  "recording_stop_ns":  1711806678000000000
}
```

---

## 8. 同步与健康监测机制

### 8.1 同步策略

两台相机无法做到硬件级同步（无 genlock），因此采用 **软件时间戳对齐** 方案：

- 每帧记录 `host_timestamp_ns`（Pi 系统时钟）和 `device_timestamp`（相机内部时钟）
- 录制期间实时计算两台相机的帧间时间差 `Δt = |ts_nyx650 - ts_tb4117|`
- 若 `Δt` 持续超过阈值（默认 66 ms，即 1 帧 @15 fps），触发告警

### 8.2 健康监测（Health Monitor）

后台线程持续检测以下指标：

| 检测项 | 触发条件 | 响应动作 |
|--------|---------|---------|
| 帧率下降 | 任一模态 FPS < 阈值的 70 % | UI 黄色警告 |
| 模态丢失 | 任一模态连续 10 帧无数据 | UI 红色警告 + 暂停录制 |
| 相机断连 | USB 设备消失 | UI 红色警告 + 自动停止录制 |
| 同步偏移 | Δt 持续 > 阈值 | UI 黄色警告 |
| 磁盘空间 | 剩余 < 1 GB | UI 红色警告 + 自动停止录制 |

### 8.3 监测数据流

```
Camera Threads ──(frame + ts)──► Health Monitor Thread
                                     │
                                     ├─► 计算 FPS（滑动窗口）
                                     ├─► 计算 Δt（双相机同步差）
                                     ├─► 检查帧连续性
                                     └─► 发送 status → UI Status Bar
```

---

## 9. 数据后处理流水线

录制结束后自动触发（可在后台运行，不阻塞新一轮录制）：

```
Pipeline:

   raw session data
        │
        ▼
   ┌─────────────────────┐
   │ Step 1: Parse       │  读取 breakpoints.json
   │ Breakpoints         │  确定每个 action 的起止帧号 / 时间戳
   └─────────┬───────────┘
             │
             ▼
   ┌─────────────────────┐
   │ Step 2: Segment     │  按断点切分 raw 视频 / 帧序列
   │ Raw Data            │  → 每个 action label 一份切片
   └─────────┬───────────┘
             │
             ▼
   ┌─────────────────────┐
   │ Step 3: Export      │  对每个 action：
   │ Videos              │  - RGB     → RGB_video/*.avi
   └─────────┬───────────┘  - Depth   → 伪彩色 Depth_video/*.avi
             │               - IR      → 归一化 IR_video/*.avi
             ▼               - Thermal → Thermal_video/*.avi
   ┌─────────────────────┐
   │ Step 4: Extract     │  对每个 action 的视频：
   │ Frames              │  - RGB_video     → RGB_frames/（逐帧 .png）
   └─────────┬───────────┘  - Depth         → Depth_frames/（.npy + .png）
             │               - IR            → IR_frames/（.npy + .png）
             ▼               - Thermal       → Thermal_frames/（逐帧 .png）
   ┌─────────────────────┐
   │ Step 5: Validate    │  校验每个 action 文件夹：
   │ & Report            │  - 4 个模态帧数一致性检查
   └─────────────────────┘  - 生成 metadata.json（帧数 / 时长 / 分辨率）
```

---

## 10. 输出目录结构

### 10.1 Raw 数据（录制期间直接写入）

```
data/
└── raw/
    └── session_{YYYYMMDD}_{HHMMSS}/
        ├── nyx650_rgb.avi                  # NYX650 RGB 视频（MJPEG）
        ├── nyx650_depth/                   # NYX650 Depth 逐帧
        │   ├── depth_000000.npy
        │   ├── depth_000001.npy
        │   └── ...
        ├── nyx650_ir/                      # NYX650 IR 逐帧
        │   ├── ir_000000.npy
        │   ├── ir_000001.npy
        │   └── ...
        ├── tb4117_thermal.avi              # TB4117 Thermal 视频
        ├── timestamps.csv                  # 全局时间戳（所有帧）
        ├── breakpoints.json                # 断点信息
        └── session_meta.json               # 录制元信息
```

### 10.2 Processed 数据（后处理输出）

```
data/
└── processed/
    └── session_{YYYYMMDD}_{HHMMSS}/
        ├── walk/                           # Action Label 1
        │   ├── RGB_video/
        │   │   └── rgb.avi
        │   ├── RGB_frames/
        │   │   ├── frame_000000.png
        │   │   ├── frame_000001.png
        │   │   └── ...
        │   ├── Depth_video/
        │   │   └── depth_colorized.avi     # 伪彩色可视化视频
        │   ├── Depth_frames/
        │   │   ├── frame_000000.npy        # 原始 16-bit 深度
        │   │   ├── frame_000000.png        # 伪彩色可视化
        │   │   └── ...
        │   ├── IR_video/
        │   │   └── ir.avi
        │   ├── IR_frames/
        │   │   ├── frame_000000.npy        # 原始 16-bit IR
        │   │   ├── frame_000000.png        # 归一化可视化
        │   │   └── ...
        │   ├── Thermal_video/
        │   │   └── thermal.avi
        │   ├── Thermal_frames/
        │   │   ├── frame_000000.png
        │   │   └── ...
        │   └── metadata.json               # 该 action 的元信息
        │
        ├── sit/                            # Action Label 2
        │   └── （同上结构）
        │
        ├── read/                           # Action Label 3
        │   └── （同上结构）
        │
        └── session_report.json             # 整个 session 的处理报告
```

### 10.3 metadata.json 示例

```json
{
  "action_label": "walk",
  "session_id": "20260330_143000",
  "duration_sec": 22.8,
  "frame_count": {
    "RGB": 342,
    "Depth": 342,
    "IR": 342,
    "Thermal": 340
  },
  "resolution": {
    "RGB": [1600, 1200],
    "Depth": [640, 480],
    "IR": [640, 480],
    "Thermal": "TBD"
  },
  "fps": {
    "RGB": 15.0,
    "Depth": 15.0,
    "IR": 15.0,
    "Thermal": "TBD"
  },
  "sync_max_drift_ms": 12.3,
  "start_timestamp_ns": 1711806590000000000,
  "end_timestamp_ns": 1711806612800000000
}
```

---

## 11. 已知限制与后续规划

### 当前限制

| 项目 | 说明 |
|------|------|
| TB4117 尚未接入 | 需确认 SDK / 接口后补充驱动代码 |
| 软件同步精度 | 两相机同步精度约 ±30–60 ms，非硬件级同步 |
| Pi 4B 性能 | 4 模态同时预览 + 写盘可能导致帧率下降，建议关闭预览或降低分辨率 |
| SD 卡写入瓶颈 | 必须使用 USB 3.0 SSD，否则写盘速度不足 |

### 开发路线图

```
Phase 1（当前）  ✅  NYX650 单相机 RGB + Depth + IR 录制验证
Phase 2          🔲  TB4117 Thermal 相机接入与单独录制验证
Phase 3          🔲  双相机同步录制 + 时间戳对齐
Phase 4          🔲  采集 UI 开发（标签输入 / 断点 / 预览）
Phase 5          🔲  健康监测模块
Phase 6          🔲  后处理流水线（切分 / 抽帧 / 归档）
Phase 7          🔲  迁移至 Jetson Orin + 性能优化
```

---

## 12. 快速开始

```bash
# 1. 验证 NYX650 连接
cd ~/ScepterSDK/BaseSDK/AArch64/PrecompiledSamples/NYX650_Samples/
bash ./NYX650_OpenCVSample

# 2. 启动采集系统（Phase 1：仅 NYX650）
cd ~/MACS
python3 main.py

# 3. 在 UI 中输入标签、开始录制、标记断点、停止录制

# 4. 查看输出
ls data/processed/session_*/
```

---

## 13. 项目代码结构

```
MACS/
├── main.py                     # 入口
├── requirements.txt
├── setup_check.py              # 环境与设备检测
├── README.md
├── config/
│   └── default.yaml            # 默认配置（分辨率 / 帧率 / 阈值）
├── capture/
│   ├── __init__.py
│   ├── nyx650_driver.py        # NYX650 取流封装
│   ├── tb4117_driver.py        # TB4117 取流封装（TBD）
│   ├── sync_manager.py         # 双相机同步控制
│   └── health_monitor.py       # 健康监测线程
├── ui/
│   ├── __init__.py
│   ├── main_window.py          # 主窗口
│   ├── preview_panel.py        # 4 模态实时预览
│   └── control_panel.py        # 按钮与标签输入
├── processing/
│   ├── __init__.py
│   ├── segmenter.py            # 按断点切分 raw 数据
│   ├── frame_exporter.py       # 视频 → 帧、.npy → .png
│   ├── validator.py            # 帧数一致性校验
│   └── pipeline.py             # 后处理流水线编排
└── data/
    ├── raw/                    # 原始录制数据
    └── processed/              # 后处理归档数据
```

---

TB417：
MJPG\YUYV
## License

TBD

## Contributors

TBD