# CUHK-Y 多模态同步采集集成手册

> 版本：v1.1 | 最近修订：2026-04-20
> 集成模态：RGB / Depth / IR / Thermal（MACS）+ mmWave（TI IWR6843ISK）+ IMU（WitMotion WT9011DCL-BT50）

本文档现在以仓库中的真实实现为准，不再使用早期草稿里那套“在 main.py 外挂第二套会话系统”的方案。

---

## 第零部分：先说修订结论

这次审阅后，原草稿里最关键的 4 个问题已经改掉：

1. 会话所有权统一了。
   现在真正拥有 session_id、session_dir、recording_start_ns 的仍然是 MACS 现有的 CaptureController + SessionRecorder，而不是在 main.py 外再造一个新的 SessionCoordinator 去生成第二份 session。

2. 新模态不再单独建目录树。
   mmWave 和 IMU 现在复用同一个 session_dir，输出分别落到同一会话目录下的 mmwave 和 imu 子目录里。

3. 不再通过热改私有属性同步时间戳。
   原草稿里直接改 _session_start、_imu._session_start 的做法有竞态和失效风险。现在改成“CaptureController 创建统一 start_ns，然后在 start_session 时显式下发”。

4. IMU BLE 不再假设“一次 notify 就是一整帧”。
   现在实现里使用流式拆包，避免 WT901 通知分片或粘包时出现偶发错帧。

---

## 第一部分：当前正确的整体架构

### 1.1 单一会话源

当前仓库里的正确会话链路如下：

```
MainWindow
  └── recording_started(labels)
        └── CaptureController._on_recording_started()
              ├── 生成统一 session_start_ns = time.time_ns()
              ├── 创建 SessionRecorder
              │     └── data/raw/session_YYYYMMDD_HHMMSS/
              ├── 调用 SessionCoordinator.start_session(session_dir, session_start_ns)
              │     ├── mmWave 写入 session_dir/mmwave/
              │     └── IMU 写入 session_dir/imu/
              └── 相机继续按原链路写 RGB / Depth / IR / Thermal
```

也就是说：

- 相机模态的录制入口没有变，仍然在 CaptureController 里。
- 新增模态只是挂接到同一个 session 生命周期里。
- main.py 不需要再自己 connect recording_started / recording_stopped 去驱动第二套外部逻辑。

### 1.2 真实模块分工

仓库中的新增实现文件：

- MAC/MACS/capture/mmwave_driver.py
  - 持久化打开 CLI/Data 串口
  - 预热时下发配置
  - 后台线程持续读包
  - 只有在 session 被 arm 后才写入 frames.bin 和 timestamps.csv

- MAC/MACS/capture/imu_driver.py
  - 独立线程运行 asyncio 事件循环
  - 维持多个 WT901 BLE 连接
  - 使用流式拆包解析 0x55 0x61 测量帧
  - 只有在 session 被 arm 后才写入各设备 CSV

- MAC/MACS/capture/session_coordinator.py
  - 只负责外部模态
  - 不拥有 session_id
  - 不创建第二份 session_meta.json
  - 只是复用 CaptureController 生成的 session_dir 和 recording_start_ns

- MAC/MACS/capture/recorder.py
  - 现在会把外部模态摘要写入同一个 session_meta.json
  - 新增 session_id 字段
  - 新增 multimodal 字段

### 1.3 当前数据目录结构

```
data/raw/session_20260420_103000/
├── session_meta.json
├── timestamps.csv
├── RGB/
├── Depth/
├── IR/
├── Thermal/
├── mmwave/
│   ├── frames.bin
│   └── timestamps.csv
└── imu/
    ├── imu01_left_wrist.csv
    ├── imu02_right_wrist.csv
    └── ...
```

说明：

- session_meta.json 仍然是全局元数据入口。
- 相机 timestamps.csv 的格式不变，后处理流水线仍能正常工作。
- mmWave / IMU 的元数据被附加到 session_meta.json 的 multimodal 字段里。

---

## 第二部分：环境准备

### 2.1 树莓派侧硬件检查

```bash
# 相机
ls /dev/video*

# mmWave
lsusb | grep -i CP2105
ls /dev/ttyUSB*

# 蓝牙
hciconfig
```

期望：

- mmWave 至少能看到 CP2105 双串口桥。
- 一般会出现 /dev/ttyUSB0 和 /dev/ttyUSB1。
- 蓝牙控制器应显示 hci0 UP RUNNING。

### 2.2 Python 依赖

在 MACS 运行环境中安装新增依赖：

```bash
pip install pyserial bleak
```

验证：

```bash
python3 -c "import serial, bleak; print('OK')"
```

### 2.3 查找 IMU MAC 地址

先给 IMU 上电，再扫描：

```bash
python3 - << 'EOF'
import asyncio
from bleak import BleakScanner

async def scan():
    devices = await BleakScanner.discover(timeout=10)
    for d in devices:
        if d.name and "WT" in d.name:
            print(d.name, d.address)

asyncio.run(scan())
EOF
```

记录每只 IMU 的 MAC 地址，稍后填到配置里。

### 2.4 先跑仓库自检

MACS 的 setup_check.py 现在已经补上了新模态相关检查：

```bash
cd ~/MACS
python3 setup_check.py
```

它现在会检查：

- pyserial / bleak 是否已安装
- mmWave 的 CP2105 USB 桥和 /dev/ttyUSB* 是否存在
- 蓝牙控制器是否可用
- mmWave 配置文件是否在 config/profile_human.cfg

---

## 第三部分：配置方式

### 3.1 编辑默认配置

当前正确入口是：

`MAC/MACS/config/default.yaml`

新增配置段如下：

```yaml
multimodal:
  mmwave:
    enabled: false
    cli_port: "/dev/ttyUSB0"
    data_port: "/dev/ttyUSB1"
    config_path: "config/profile_human.cfg"

  imu:
    enabled: false
    sample_rate_hz: 50
    devices:
      - label: "imu01_left_wrist"
        mac: "AA:BB:CC:DD:EE:FF"
      - label: "imu02_right_wrist"
        mac: ""
      - label: "imu03_waist"
        mac: ""
      - label: "imu04_left_ankle"
        mac: ""
      - label: "imu05_right_ankle"
        mac: ""
```

实际使用时至少要做这几件事：

1. 把 mmwave.enabled 改成 true
2. 把 imu.enabled 改成 true
3. 把 5 个 IMU 的 MAC 地址填完整
4. 确认 cli_port / data_port 与树莓派实际枚举一致

### 3.2 mmWave 配置文件

仓库里已经补上：

`MAC/MACS/config/profile_human.cfg`

如果你已经有自己验证过的 TI profile，也可以替换它，但要注意：

- 配置里应包含完整的 sensorStop / flushCfg / ... / sensorStart 链路
- 现有实现默认按 40 字节 frame header 解析 totalPacketLen 和 numDetectedObj

---

## 第四部分：真实录制流程

### 4.1 启动阶段

执行：

```bash
cd ~/MACS
python3 main.py
```

当前代码中，CaptureController.initialize() 会：

1. 按原逻辑启动 NYX650 和 TB4117 驱动
2. 调用 SessionCoordinator.prepare()
3. 预热 mmWave 和 IMU

预热阶段的含义：

- mmWave：打开串口、下发 profile、启动后台读线程
- IMU：启动 BLE 事件循环并尝试建立连接

注意：

- 预热不创建会话目录
- 预热也不写任何 session 数据
- 真正写盘发生在用户点击 Start 之后

### 4.2 开始录制

点击 Start 或按空格后：

1. CaptureController 先生成统一的 session_start_ns
2. SessionRecorder 创建 session_YYYYMMDD_HHMMSS 目录
3. SessionCoordinator.start_session(session_dir, session_start_ns) 被调用
4. 相机、mmWave、IMU 都开始往同一个 session_dir 写数据

关键点：

- 这里没有第二份 session_id
- 这里没有 main.py 层的额外 connect
- 这里没有通过改私有变量同步时间戳

### 4.3 停止录制

点击 Stop 或按 Esc 后：

1. CaptureController 先让 SessionCoordinator.stop_session()
2. mmWave / IMU 关闭本轮 session 文件句柄
3. 外部模态摘要写回 SessionRecorder
4. SessionRecorder.finalize() 写出统一的 session_meta.json
5. 后处理流水线继续只处理相机模态

这一点要特别说明：

- 当前 PostProcessor / Segmenter / FrameExporter 仍然只面向 RGB / Depth / IR / Thermal
- mmWave / IMU 现在已经完成“同步采集 + 统一归档 + 统一元数据登记”
- 但它们还没有接进现有 processed/ 导出流水线

这是当前实现的边界，不是遗漏。

---

## 第五部分：独立 smoke test

仓库里已经补上独立测试脚本：

`MAC/MACS/tools/multimodal_smoke_test.py`

它不会启动 PyQt UI，只会复用同一个 SessionCoordinator 做外部模态冒烟测试。

运行方法：

```bash
cd ~/MACS
python3 tools/multimodal_smoke_test.py --duration 30
```

可选参数：

- --config
- --duration
- --output-root

这个脚本适合在两种场景下使用：

1. 先验证 mmWave / IMU 本身能不能采起来
2. 在不启动相机 UI 的情况下单独排查串口或 BLE 问题

---

## 第六部分：实验操作顺序

推荐顺序：

1. 实验前先给 IMU 充电，并确认手机或 Windows 软件能看到所有设备
2. 上树莓派后先释放串口

```bash
sudo fuser -k /dev/ttyUSB0 /dev/ttyUSB1
```

3. 启动 MACS

```bash
cd ~/MACS
python3 main.py
```

4. 等待终端里出现外部模态预热日志
5. 参与者佩戴 IMU，站到雷达前方
6. 在 MACS UI 里点击 Start
7. 执行动作任务
8. 点击 Stop

---

## 第七部分：录制后检查

### 7.1 检查原始目录

```bash
ls -lh data/raw/session_*
```

### 7.2 检查 mmWave 帧数

```bash
wc -l data/raw/session_*/mmwave/timestamps.csv
```

### 7.3 检查 IMU 采样数

```bash
wc -l data/raw/session_*/imu/*.csv
```

### 7.4 检查全局元数据

```bash
python3 - << 'EOF'
import json
from pathlib import Path

session = sorted(Path("data/raw").glob("session_*"))[-1]
meta = json.loads((session / "session_meta.json").read_text())

print("session_id:", meta.get("session_id"))
print("recording_start_ns:", meta.get("recording_start_ns"))
print("camera frame_counts:", meta.get("frame_counts"))
print("multimodal:", json.dumps(meta.get("multimodal", {}), indent=2))
EOF
```

### 7.5 快速对齐检查

```bash
python3 - << 'EOF'
import csv
import json
from pathlib import Path

session = sorted(Path("data/raw").glob("session_*"))[-1]
meta = json.loads((session / "session_meta.json").read_text())
cam_start = meta.get("recording_start_ns", 0)

mmw_ts = []
mmw_path = session / "mmwave" / "timestamps.csv"
if mmw_path.exists():
    with open(mmw_path) as fh:
        for row in csv.DictReader(fh):
            mmw_ts.append(int(row["timestamp_ns"]))

imu_ts = []
imu_files = sorted((session / "imu").glob("*.csv"))
if imu_files:
    with open(imu_files[0]) as fh:
        for row in csv.DictReader(fh):
            imu_ts.append(int(row["timestamp_ns"]))

print("session:", session.name)
if mmw_ts:
    print("camera start vs mmWave first frame:", abs(cam_start - mmw_ts[0]) / 1e6, "ms")
if mmw_ts and imu_ts:
    print("mmWave first frame vs IMU first sample:", abs(mmw_ts[0] - imu_ts[0]) / 1e6, "ms")
EOF
```

---

## 第八部分：常见问题

| 问题 | 现象 | 处理方式 |
|------|------|---------|
| mmWave prepare 失败 | 启动时日志提示 mmWave unavailable | 先检查 /dev/ttyUSB*、CP2105、profile_human.cfg 路径 |
| mmWave 帧数为 0 | session 里有 mmwave 目录但 timestamps.csv 只有表头 | 检查 sensorStart 是否成功，确认配置文件完整 |
| IMU CSV 为空 | 文件存在但只有表头 | 先确认 MAC 地址正确，设备未被手机占用，BLE 控制器正常 |
| `BleakError: No powered Bluetooth adapters found.` | 扫描脚本一启动就报错，连 WT 设备列表都没有 | 这不是 IMU 没上电，而是主机蓝牙控制器没上电或被屏蔽；先跑 `bluetoothctl list`、`bluetoothctl show`、`rfkill list bluetooth`、`hciconfig -a`，再执行 `sudo rfkill unblock bluetooth && sudo systemctl restart bluetooth hciuart && sudo bluetoothctl power on` |
| IMU 偶发错帧 | 姿态值突跳、不连续 | 当前代码已使用流式拆包；若仍异常，优先排查 BLE 丢包或设备端设置 |
| setup_check 全绿但采不到 | 往往是设备被占用或 MAC 地址错误 | setup_check 只做存在性检查，不等于链路端到端已录通 |
| processed/ 里没有 mmWave / IMU | 录制后 raw/ 下有数据，但后处理目录没有 | 当前 processed/ 流水线仍是相机专用，这是已知边界 |

---

## 第九部分：时间戳对齐原则

各模态都使用主机侧 time.time_ns() 打标。

当前代码里：

- 相机：驱动捕获帧时打 time.time_ns()
- mmWave：后台解析到完整 packet 时打 time.time_ns()
- IMU：通知流拆出完整测量帧时打 time.time_ns()

后处理时建议：

1. 先用 session_meta.json 中的 recording_start_ns 作为统一会话起点参考
2. 再比较 mmwave/timestamps.csv 与 imu/*.csv 的首帧时间
3. 如需跨设备精对齐，继续保留 NTP + 拍手 / 明显动作事件双保险

在局域网 NTP 正常的前提下，这种主机侧统一打标方式足够支持多模态同步采集与后续时间对齐。