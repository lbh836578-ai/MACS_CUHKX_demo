# CUHK-Y 预实验执行手册：IWR6843ISK × Raspberry Pi mmWave 系统搭建

> 版本：v3.0 | 创建日期：2026-04-18
> SDK：mmWave SDK 03.05.00.04 | 平台：xWR68xx
>
> **本文档基于真实验证的搭建过程编写，所有步骤均已在实际硬件上测试通过。**

---

## 第零部分：系统全貌与复现原则

### 0.1 先用一句话理解这个项目

这不是"把雷达插上去就能用"的项目，而是一个**串口配置 + 实时点云采集 + 离线分析**的感知系统。你要搭起 3 条链路：

1. **配置链路**：RPi 通过 UART CLI 端口把 `.cfg` 配置文件下发给 IWR6843ISK，雷达开始扫描
2. **数据链路**：雷达通过 UART Data 端口实时输出帧数据（点云 + 多普勒 + 强度），RPi 解析并保存为 `.bin`
3. **分析链路**：离线把原始帧还原成点云图、距离-多普勒热图、目标轨迹，回答研究问题

你最终不是只要"雷达在转"，而是要回答 3 个研究问题：

- 单人动作能否从点云序列中稳定区分
- 双人场景下，两个目标的点云轨迹能否被分离追踪
- mmWave 数据与其他模态数据的时间对齐精度是否满足多模态融合要求

### 0.2 硬件参数

IWR6843ISK 是 TI 的 60GHz FMCW 毫米波雷达评估板。输出的不是图像，而是**每帧一组稀疏 3D 点**，每个点携带 `(x, y, z, velocity, snr, noise)`。

| 参数 | 值 |
|------|---|
| 工作频率 | 60 – 64 GHz |
| 发射天线 TX | 3 根 |
| 接收天线 RX | 4 根 |
| 水平视野角 | 120° |
| 垂直视野角 | 30° |
| 最大检测距离（人体） | ~10 m |
| 最小检测距离（盲区） | ~0.3 m |
| 供电 | USB 5V |

### 0.3 连接方式

一根 Micro-USB 数据线连接雷达和树莓派，这根线同时完成三件事：供电、CLI 配置、数据输出。

**必须用数据线，不能用充电线。** 充电线接上后 LED 会亮，但树莓派识别不到任何串口设备。

插上后树莓派会出现两个虚拟串口：

| 串口 | 波特率 | 用途 |
|------|--------|------|
| `/dev/ttyUSB0` | 115200 | CLI：发送配置命令 |
| `/dev/ttyUSB1` | 921600 | Data：接收点云帧数据 |

### 0.4 每个模块到底做什么

| 模块 | 跑在哪 | 输入 | 输出 | 作用 |
|------|--------|------|------|------|
| IWR6843ISK 雷达 | 硬件本身 | 60GHz 电磁波 | UART 串口帧数据 | 发射和接收毫米波，完成距离/速度/角度估计 |
| CLI 配置下发 | RPi | `.cfg` 文件 | 串口命令 | 告诉雷达用什么参数扫描 |
| 实时数据采集 | RPi | UART Data 串口 | `.bin` 原始帧 | 把雷达输出保存到磁盘 |
| 离线帧解析 | 分析电脑 | `.bin` 原始帧 | 点云数组、可视化图 | 从二进制帧中还原感知结果 |
| 时间同步 | 所有设备 | chrony + 拍手 | 对齐时间基准 | 让 mmWave 与其他模态对齐 |

### 0.5 工具清单

| 工具 | 跑在哪 | 作用 |
|------|--------|------|
| `pyserial` | RPi | Python 串口通信库，下发配置和读取数据 |
| `tmux` | RPi | 后台运行长时间采集任务，避免 SSH 断开后中止 |
| `chrony` | 所有设备 | 局域网时间同步 |
| `numpy` / `matplotlib` | 分析电脑 | 数值处理和点云可视化 |

### 0.6 新手最容易犯的错误

1. **用了充电线。** 充电线接上后 LED 亮但串口不出现，换数据线。
2. **波特率写错。** CLI 必须是 115200，Data 必须是 921600，写反了什么都收不到。
3. **先打开 Data 端口再发配置。** 必须先打开 Data 端口监听，再发 `sensorStart`，否则会错过最开始的帧。
4. **`.cfg` 命令不完整就发 `sensorStart`。** SDK 3.5 有严格的必选命令列表，缺任何一条都会报错，用本文档提供的完整配置文件即可。
5. **近距离有盲区。** 雷达正前方 0.3m 以内检测不到目标。
6. **串口被占用。** 用过 `screen` 之后串口会被锁住，运行脚本前先释放串口。

### 0.7 推荐的搭建顺序

1. 验证硬件连接：`lsusb` 看到 CP2105，`ls /dev/ttyUSB*` 看到两个端口
2. 用 `screen` 手动发 `version` 命令，确认 CLI 端口响应正常
3. 创建配置文件和采集脚本
4. 跑测试脚本，在雷达前方走动，确认帧数大于 0
5. 最后才做多模态集成和长时间采集

---

## 第一部分：验证硬件连接

```bash
# 确认雷达被识别
lsusb
# 应看到：Silicon Labs CP2105 Dual UART Bridge

# 确认串口设备
ls /dev/ttyUSB*
# 应看到：/dev/ttyUSB0 和 /dev/ttyUSB1

# 验证 CLI 端口响应
screen /dev/ttyUSB0 115200
# 输入：version
# 应看到固件信息，包含 mmWave SDK Version: 03.05.00.04
# 退出：Ctrl+A 然后 K 然后 Y
```

---

## 第二部分：安装依赖

```bash
pip install pyserial
```

验证：

```bash
python3 -c "import serial; print(serial.__version__)"
```

---

## 第三部分：创建配置文件

以下配置已在 SDK 03.05.00.04 + IWR6843ISK 上验证通过。

```bash
mkdir -p ~/mmwave/configs
cat > ~/mmwave/configs/profile_human.cfg << 'EOF'
sensorStop
flushCfg
dfeDataOutputMode 1
channelCfg 15 5 0
adcCfg 2 1
adcbufCfg -1 0 1 1 1
profileCfg 0 60 329 7 57.14 0 0 70 1 256 5209 0 0 30
chirpCfg 0 0 0 0 0 0 0 1
chirpCfg 1 1 0 0 0 0 0 4
frameCfg 0 1 16 0 100 1 0
lowPower 0 0
bpmCfg -1 0 0 0
guiMonitor -1 1 0 0 0 0 1
cfarCfg -1 0 2 8 4 3 0 15 1
cfarCfg -1 1 0 4 2 3 1 15 1
cfarFovCfg -1 0 0 8.92
cfarFovCfg -1 1 -1 1.0
multiObjBeamForming -1 1 0.5
clutterRemoval -1 0
calibDcRangeSig -1 0 -5 8 256
measureRangeBiasAndRxChanPhase 0 1.5 0.2
compRangeBiasAndRxChanPhase 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0
aoaFovCfg -1 -90 90 -40 40
extendedMaxVelocity -1 0
lvdsStreamCfg -1 0 0 0
analogMonitor 0 0
CQRxSatMonitor 0 3 5 121 0
CQSigImgMonitor 0 127 4
sensorStart
EOF
```

---

## 第四部分：创建采集脚本

```bash
mkdir -p ~/mmwave/scripts
cat > ~/mmwave/scripts/test_mmwave.py << 'EOF'
import serial
import time
import threading

CLI_PORT  = '/dev/ttyUSB0'
DATA_PORT = '/dev/ttyUSB1'
MAGIC     = b'\x02\x01\x04\x03\x06\x05\x08\x07'
CFG_FILE  = '/home/pi/mmwave/configs/profile_human.cfg'

frame_count = 0

def read_data():
    global frame_count
    data_ser = serial.Serial(DATA_PORT, 921600, timeout=1)
    start = time.time()
    while time.time() - start < 15:
        chunk = data_ser.read(4096)
        if chunk and MAGIC in chunk:
            frame_count += chunk.count(MAGIC)
            print(f"\rFrames: {frame_count}", end='', flush=True)
    data_ser.close()

print("=== Opening data port ===")
t = threading.Thread(target=read_data)
t.start()
time.sleep(1)

print("=== Sending config ===")
cli = serial.Serial(CLI_PORT, 115200, timeout=3)
time.sleep(0.5)

with open(CFG_FILE) as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('%'):
            continue
        cli.write((line + '\n').encode())
        resp = ''
        deadline = time.time() + 3
        while time.time() < deadline:
            chunk = cli.read(cli.in_waiting or 1)
            if chunk:
                resp += chunk.decode(errors='ignore')
                if 'Done' in resp or 'Error' in resp:
                    break
            time.sleep(0.05)
        status = 'OK' if 'Done' in resp else 'ERR'
        print(f"  [{status}] {line}")
        if 'Error' in resp:
            print(f"         -> {resp.strip()}")

cli.close()
print("\n=== Waiting for data (walk in front of radar) ===")
t.join()

print(f"\n=== Total frames: {frame_count} ===")
if frame_count > 0:
    print("SUCCESS!")
else:
    print("FAILED: No data received.")
EOF
```

---

## 第五部分：运行测试

```bash
sudo fuser -k /dev/ttyUSB0
sudo fuser -k /dev/ttyUSB1
python3 ~/mmwave/scripts/test_mmwave.py
```

运行期间在雷达正前方走动，15 秒采集窗口内观察帧数是否增加。

正常输出：
```
=== Opening data port ===
=== Sending config ===
  [OK] sensorStop
  [OK] flushCfg
  ...
  [OK] sensorStart
=== Waiting for data (walk in front of radar) ===
Frames: 119
=== Total frames: 119 ===
SUCCESS!
```

---

## 第六部分：故障排查

| 问题 | 原因 | 解决方法 |
|------|------|---------|
| `/dev/ttyUSB*` 不出现 | 充电线，无数据线路 | 换数据线 |
| 只出现一个 ttyUSB | 同上 | 换数据线 |
| `Device or resource busy` | screen 或其他进程占用串口 | 运行 `sudo fuser -k /dev/ttyUSB0` 和 `sudo fuser -k /dev/ttyUSB1` |
| 所有命令返回 `??` | CLI 和 Data 端口搞反了 | 脚本里交换 CLI_PORT 和 DATA_PORT |
| `sensorStart` 报错 | 缺少必选配置命令 | 使用第三部分的完整配置文件 |
| 收到 0 帧 | Data 端口在 sensorStart 之后才打开 | 使用第四部分的脚本，它会先打开 Data 端口 |

> `sensorStart` 返回 `Error: Full configuration must be provided` 说明配置命令不完整。解决方法是使用第三部分提供的完整配置文件，不要删减任何命令。