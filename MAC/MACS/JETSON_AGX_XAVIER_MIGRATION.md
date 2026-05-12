# MACS 迁移到 Jetson AGX Xavier 开发者套件操作手册

> 适用对象：NVIDIA Jetson AGX Xavier Developer Kit
>
> 目标：把当前 MACS 项目从树莓派环境迁移到 AGX Xavier，并完成从刷机、接线、环境准备、设备验证到正式运行的全流程落地。

---

## 1. 先说结论

这次迁移的推荐路线只有一条：

1. 先用 Ubuntu 主机给 AGX Xavier 刷 JetPack 5.1.x。
2. 再在 Xavier 上安装系统依赖和 Python 运行环境。
3. 再逐个接入 NYX650、TB4117、mmWave、IMU 做单设备验证。
4. 单设备都通过后，再跑 `setup_check.py`、`multimodal_smoke_test.py`、`main.py`。

不要一开始就把所有外设同时接上然后直接运行 UI。那样一旦失败，你无法判断是刷机、USB、串口、蓝牙、SDK 还是代码路径的问题。

---

## 2. 本文档覆盖范围

本文档覆盖以下内容：

1. AGX Xavier 开发者套件从零上电与刷机。
2. 迁移 MACS 到 Jetson 的系统依赖与 Python 环境。
3. 当前仓库中 MACS 主系统的关键文件与运行入口。
4. 相机、雷达、蓝牙 IMU 的接入顺序与验证方法。
5. 正式运行前的冒烟测试和常见故障排查。

本文档不覆盖以下内容：

1. 前端演示应用 `figure2-app` 的部署。这不是采集主链路的阻塞项。
2. Jetson 内核裁剪、驱动二次开发、生产级镜像封装。这些属于下一阶段工作。

---

## 3. 先明确几个关键事实

### 3.1 你手上的板子是什么

你当前设备是 Jetson AGX Xavier Developer Kit，不是 Xavier NX，也不是 Orin。

这意味着：

1. 推荐使用 JetPack 5.1.x。
2. 不要按 Orin 的 JetPack 6.x 或 7.x 文档来做。
3. 不要按 Xavier NX 的 microSD 镜像路线来做。
4. 你的开发板通常走内部 eMMC 启动，推荐用 Ubuntu 主机刷机。

### 3.2 你当前这套仓库的 MACS 主入口在哪里

当前 MACS 采集主链路位于以下文件：

1. 主入口：`main.py`
2. 系统检查：`setup_check.py`
3. 独立诊断：`diagnose.py`
4. 外设冒烟测试：`tools/multimodal_smoke_test.py`
5. IMU 诊断：`tools/ble_imu_diagnose.py`
6. 默认配置：`config/default.yaml`

当前运行逻辑是：

1. `main.py` 启动 PyQt5 UI 和 `CaptureController`。
2. `CaptureController` 协调 NYX650、TB4117，以及外部模态协调器。
3. `SessionCoordinator` 把 mmWave 和 IMU 挂到同一个 session 目录下。

### 3.3 最推荐的 JetPack 版本

建议优先使用 JetPack 5.1.6 或同代 JetPack 5.1.x sustaining release。

原因：

1. Xavier 仍在 JetPack 5.x 支持序列中。
2. 这一代系统与当前项目要求的 Python 3.8+、PyQt5、OpenCV、BlueZ、串口工具链更匹配。
3. 比较适合稳定 bring-up，不建议为了“新”去上 JetPack 6/7。

---

## 4. 迁移前准备清单

在开始之前，你需要准备以下物品。

### 4.1 硬件

1. Jetson AGX Xavier Developer Kit 本体。
2. 原装或匹配规格电源，满足 9V10A 到 20V4.5A 输入范围。
3. 一台显示器。
4. USB 键盘和鼠标。
5. 网线。
6. 一块 USB 3.0 外接 SSD，建议至少 256GB。
7. 一个 USB 3.0 有源 Hub。
8. USB-C 数据线，用于刷机连接 Ubuntu 主机。
9. Scepter NYX650 相机。
10. HikVision TB4117 热像仪。
11. mmWave 雷达及其 USB 转串口连接线。
12. WitMotion BLE IMU 设备。

### 4.2 主机与软件

1. 一台 Ubuntu 20.04 x86_64 主机。
2. NVIDIA SDK Manager。
3. NVIDIA Developer 账号。
4. 当前项目仓库的访问方式。

### 4.3 为什么你不能直接用 macOS 完成整个刷机流程

你现在工作机是 macOS，但 AGX Xavier 的标准刷机路径依赖 Ubuntu 主机和 NVIDIA 官方工具链。

所以建议：

1. 如果你手边有 Ubuntu 物理机，直接用它。
2. 如果没有，就先借一台 Ubuntu 20.04 x86_64 主机。
3. 不建议把刷机这一步强行放在虚拟机里做，USB 恢复模式透传常常不稳定。

---

## 5. 总体迁移路线图

你可以把整个迁移分成 8 个阶段：

1. 刷机到 JetPack 5.1.x。
2. 完成首次开机和系统基线设置。
3. 接上 SSD，规划数据落盘路径。
4. 拉取仓库，创建 Python 环境，安装依赖。
5. 安装 NYX650 SDK，确认 TB4117 处于 UVC 模式。
6. 分别验证视频、串口、蓝牙三类设备。
7. 运行系统检查与外设冒烟测试。
8. 启动 MACS UI，执行首轮真实采集。

任何一个阶段没通过，都不要跳到下一阶段。

---

## 6. 阶段一：刷 JetPack 到 AGX Xavier

### 6.1 推荐方案

推荐你使用 Ubuntu 主机上的 NVIDIA SDK Manager 进行刷机。

这是最稳妥的路径，因为它会把：

1. Jetson Linux。
2. JetPack 组件。
3. 目标板刷机步骤。
4. 部分依赖安装流程。

整合到一套可视化流程里。

### 6.2 在 Ubuntu 主机上安装 SDK Manager

在 Ubuntu 主机上完成：

1. 登录 NVIDIA Developer 网站。
2. 下载适用于 Ubuntu 的 SDK Manager。
3. 安装后启动 `sdkmanager`。

如果系统里没有它，通常安装方式类似：

```bash
sudo apt install ./sdkmanager_*.deb
sdkmanager
```

### 6.3 AGX Xavier 进入 Recovery Mode

刷机前，先把 AGX Xavier 接到 Ubuntu 主机。

连接方式：

1. 给 AGX Xavier 接上电源。
2. 用 USB-C 数据线连接 AGX Xavier 与 Ubuntu 主机。
3. 使用靠近电源按钮的 USB-C 口进行刷机连接。

进入恢复模式的推荐操作：

1. 关机。
2. 按住 Recovery 按钮不放。
3. 再按一下 Power 按钮。
4. 先松开 Power。
5. 再松开 Recovery。

完成后，在 Ubuntu 主机上检查：

```bash
lsusb
```

你应该能看到 NVIDIA 设备，AGX Xavier 常见识别为：

```text
0955:7019
```

如果看不到，说明板子没有正确进入恢复模式，或者 USB 线不是数据线。

### 6.4 在 SDK Manager 中选择目标

推荐选择：

1. Product Category：Jetson。
2. Hardware：Jetson AGX Xavier Developer Kit。
3. SDK Version：JetPack 5.1.6 或可用的 5.1.x sustaining 版本。
4. Target OS：Jetson Linux。

建议：

1. 首次 bring-up 先刷标准系统，不要一开始就自定义太多组件。
2. Host 侧附加组件不是必须，目标是先让板子正常启动。

### 6.5 如果你不用 SDK Manager，命令行刷机的思路

只在你熟悉 NVIDIA Linux_for_Tegra 工具链时才用命令行。

典型流程是：

1. 下载 Jetson Linux release package。
2. 下载 sample root filesystem。
3. 解包并执行 `apply_binaries.sh`。
4. 让板子进入 recovery。
5. 执行 `flash.sh jetson-agx-xavier-devkit internal`。

示例命令：

```bash
tar xf Jetson_Linux_*.tbz2
sudo tar xpf Tegra_Linux_Sample-Root-Filesystem_*.tbz2 -C Linux_for_Tegra/rootfs/
cd Linux_for_Tegra
sudo ./apply_binaries.sh
sudo ./tools/l4t_flash_prerequisites.sh
sudo ./flash.sh jetson-agx-xavier-devkit internal
```

如果你对 Xavier 完全陌生，优先使用 SDK Manager，不要先走命令行。

### 6.6 刷机完成标准

刷机完成后，你的板子需要满足：

1. 能正常启动进入 Jetson 首次初始化流程。
2. 能创建用户、设置密码、进入桌面或命令行。
3. `cat /etc/nv_tegra_release` 能返回 NVIDIA Jetson 版本信息。

---

## 7. 阶段二：首次开机后的系统基线设置

### 7.1 首次开机建议必须接显示器

第一次启动时，不建议直接走纯 headless。

原因很简单：

1. 你对设备还不熟。
2. 首次用户初始化用显示器最快。
3. 这样能最快确认图形环境、网络和 USB 是否正常。

### 7.2 基础命令

开机后，先执行：

```bash
uname -a
cat /etc/nv_tegra_release
lsb_release -a
```

再做系统更新：

```bash
sudo apt update
sudo apt upgrade -y
```

### 7.3 打开 SSH

为了后续远程调试，建议第一时间启用 SSH：

```bash
sudo systemctl enable ssh
sudo systemctl start ssh
ip addr show
```

然后在你的电脑上测试：

```bash
ssh <your_user>@<jetson_ip>
```

### 7.4 设置高性能模式

迁移和 bring-up 阶段先锁定高性能，不要引入动态降频变量。

```bash
sudo nvpmodel -m 0
sudo jetson_clocks
```

说明：

1. `nvpmodel -m 0` 常用于切到高性能模式。
2. `jetson_clocks` 会把 CPU/GPU/EMC 固定到更高频率，便于排查是否是性能瓶颈。

### 7.5 建议接入外接 SSD

MACS 会持续写原始数据。不要把正式采集数据长期写在系统盘上。

建议：

1. 仓库代码可以先放在系统盘。
2. 采集数据目录最好放到外接 SSD。
3. 首次 bring-up 先确认 SSD 可以稳定挂载和写入。

查看磁盘：

```bash
lsblk
df -h
```

如果 SSD 是新盘，可先格式化为 ext4，然后挂载到例如：

```text
/mnt/macs_ssd
```

---

## 8. 阶段三：获取代码并建立运行环境

### 8.1 拉取代码

在 Xavier 上执行：

```bash
cd ~
git clone <你的仓库地址> CUHK-Y
cd ~/CUHK-Y/MAC/MACS
```

### 8.2 系统层依赖安装

建议优先使用 apt 安装 OpenCV 与 PyQt5。

```bash
sudo apt install -y \
  git curl wget vim tmux htop \
  build-essential pkg-config \
  python3-pip python3-venv python3-dev \
  python3-opencv python3-pyqt5 python3-numpy \
  v4l-utils usbutils \
  bluez bluetooth rfkill \
  libgl1 libglib2.0-0 libusb-1.0-0-dev
```

如果你要排查串口和蓝牙，也建议装：

```bash
sudo apt install -y minicom screen
```

### 8.3 创建 Python 虚拟环境

推荐使用带 `--system-site-packages` 的 venv，这样可以复用 apt 安装的 PyQt5 和 OpenCV。

```bash
cd ~/CUHK-Y/MAC/MACS
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
```

### 8.4 安装 Python 包

当前项目至少需要这些包：

```bash
source .venv/bin/activate
python -m pip install PyYAML pyserial bleak
```

你也可以顺手验证导入：

```bash
python - <<'PY'
import cv2
import numpy
import PyQt5
import yaml
import serial
import bleak
print('python deps ok')
PY
```

### 8.5 用户权限

给当前用户补充串口、视频、蓝牙相关组权限：

```bash
sudo usermod -aG dialout,video,plugdev,bluetooth $USER
```

执行后建议重启一次：

```bash
sudo reboot
```

补充说明：

1. `usermod` 不会影响当前已经打开的 shell。
2. 如果你刚加完组就立刻运行 `main.py`，仍然看到 `Permission denied: '/dev/ttyUSB1'`，这通常不是代码问题，而是新组尚未生效。
3. 最稳妥的做法是重新登录一次，或者至少开一个新的 shell 会话。

可以用下面的命令快速确认：

```bash
id
groups
newgrp dialout
groups
```

只有当 `groups` 里出现 `dialout` 后，再去排查 mmWave 串口映射才有意义。

---

## 9. 阶段四：把外设前提条件准备好

### 9.1 NYX650 的前提

当前 NYX650 驱动会在以下路径搜索 ScepterSDK Python API：

```text
~/ScepterSDK/MultilanguageSDK/Python
/opt/ScepterSDK/MultilanguageSDK/Python
```

所以你应该把 SDK 安装到这两个路径之一。

补充说明：当前已验证可以直接从公开仓库获取 SDK：

```bash
cd ~
git clone https://github.com/ScepterSW/ScepterSDK.git ~/ScepterSDK
```

另外要注意，AArch64 预编译 sample 的真实路径是：

```text
~/ScepterSDK/BaseSDK/AArch64/PrecompiledSamples/NYX650_OpenCVSample
```

不是旧文档里常见的这个目录：

```text
~/ScepterSDK/BaseSDK/AArch64/PrecompiledSamples/NYX650_Samples/
```

完成后，你至少要能做到：

1. 目录存在。
2. SDK 自带 sample 能运行。
3. Python 可以导入 `API.ScepterDS_api`。

建议按下面顺序验收：

```bash
ls ~/ScepterSDK/BaseSDK/AArch64/PrecompiledSamples
ls ~/ScepterSDK/MultilanguageSDK/Python/API
ls ~/ScepterSDK/MultilanguageSDK/Python/Samples/NYX650/DeviceConnectBySN

cd ~/ScepterSDK/BaseSDK/AArch64/PrecompiledSamples
chmod +x ./NYX650_OpenCVSample
./NYX650_OpenCVSample

cd ~/ScepterSDK/MultilanguageSDK/Python/Samples/NYX650/DeviceConnectBySN
python3 DeviceConnectBySN.py
```

还要明确一点：NYX650 是以太网设备，不是普通 USB 视频设备。

这意味着：

1. `get device count: 0` 并不优先说明 SDK 损坏。
2. 它更常见的含义是：主机网卡和相机不在同一子网，或者发现流量走错网口。
3. 如果你有多张网卡，SDK 官方 Python README 已明确提示：不同网卡必须使用不同网段。
4. 如果你只有一张网口并且直连 NYX650，就要把这张口临时设成与相机同子网的静态 IP，而且不要给它设置网关。

单网口直连时，最小排查命令是：

```bash
ip -br addr
ip route
ip route get <camera_ip>
ping -I <nic_name> <camera_ip>
```

如果 `ping` 能通但 sample 仍然显示 `get device count: 0`，下一步不要只盯着 `DeviceConnectBySN`，而应当直接去跑：

```bash
cd ~/ScepterSDK/MultilanguageSDK/Python/Samples/NYX650/DeviceConnectByIP
python3 DeviceConnectByIP.py
```

如果你之前改过 NYX650 的 IP，主机必须回到同一个子网，否则 `scGetDeviceCount()` 也会是 0。

### 9.2 TB4117 的前提

当前 TB4117 驱动按标准 UVC 视频设备使用，不依赖专有 Python SDK。

这意味着：

1. TB4117 必须处于 UVC 模式。
2. 系统里要能看到 `/dev/video*`。
3. `v4l2-ctl --list-devices` 应该能列到它。

### 9.3 mmWave 的前提

当前默认配置中 mmWave 使用两个串口：

```text
cli_port: /dev/ttyUSB0
data_port: /dev/ttyUSB1
```

迁到 Xavier 后，这两个端口号很可能变化。

所以你必须重新确认：

1. 哪个是 CLI 口。
2. 哪个是 data 口。
3. `config/profile_human.cfg` 是否存在并可用。

补充说明：当前 MACS 的 mmWave 驱动按 [MAC/MACS/config/default.yaml](MAC/MACS/config/default.yaml) 的默认配置，认为：

```text
ttyUSB0 -> CLI 口，115200，发送 ASCII 配置命令
ttyUSB1 -> Data 口，921600，接收二进制雷达数据包
```

`capture/mmwave_driver.py` 在 `prepare()` 里会先打开 `data_port`，再打开 `cli_port`。所以如果日志是：

```text
mmWave prepare failed: [Errno 13] could not open port /dev/ttyUSB1
```

在当前默认配置下，第一优先级不是协议不匹配，而是：

1. 当前用户没有串口权限。
2. `dialout` 组还没生效。
3. 或者别的进程正占着这个节点。

最小排查命令：

```bash
ls -l /dev/ttyUSB*
id
groups
sudo lsof /dev/ttyUSB0 /dev/ttyUSB1
```

判断规则：

1. 如果设备节点是 `root:dialout` 且权限为 `660`，而当前用户不在 `dialout` 组，`main.py` 一定会报 `Permission denied`。
2. 如果 `lsof` 没输出，说明不是被别的进程占用。
3. 只有在权限修好以后，才去怀疑 CLI / data 口接反。

修复后，建议先做一个最小打开测试：

```bash
python3 - <<'PY'
import serial
for dev, baud in [('/dev/ttyUSB0', 115200), ('/dev/ttyUSB1', 921600)]:
  try:
    s = serial.Serial(dev, baud, timeout=0.2)
    print('OK', dev, baud)
    s.close()
  except Exception as exc:
    print('FAIL', dev, baud, exc)
PY
```

还要注意协议特性：

1. CLI 口是文本配置口，`screen /dev/ttyUSB0 115200` 或 `minicom` 可以作为辅助检查。
2. Data 口承载的是 921600 的二进制数据流，`screen` 不是有效的验证工具。
3. 如果你拿 `screen` 去看 data 口，看到乱码、空白或者工具异常退出，都不能直接据此判断雷达损坏。

### 9.4 BLE IMU 的前提

当前 IMU 依赖 BlueZ 和 Python 的 `bleak`。

你需要确认：

1. Xavier 的蓝牙控制器存在并可用。
2. `bluetoothctl show` 有输出。
3. 目标 IMU 会广播。
4. 首次 bring-up 时不要 5 个 IMU 一起测，先只测 1 个。

补充说明：`bluetooth.service` 处于 `active (running)` 并不等价于“系统里有可用蓝牙控制器”。

如果你看到的是：

```text
bluetoothctl list        -> 空
bluetoothctl show        -> No default controller available
hciconfig -a             -> 空
```

那当前问题不是 IMU 没开机，而是主机侧根本没有被 BlueZ/Bleak 识别到任何控制器。此时 MACS 日志通常会是：

```text
IMU scan failed: No Bluetooth adapters found.
IMU imuXX_xxx: No Bluetooth adapters found.
```

这是系统层前置条件失败，不是 IMU MAC 地址、采样率或重连参数的问题。

建议固定使用下面这组命令判断蓝牙 bring-up 状态：

```bash
bluetoothctl list
bluetoothctl show
hciconfig -a
rfkill list bluetooth
systemctl status bluetooth --no-pager
lsusb | grep -i -E 'bluetooth|intel|realtek|broadcom|csr'
dmesg | grep -i -E 'bluetooth|hci|btusb|firmware' | tail -100
```

判断规则：

1. 只要 `bluetoothctl list` 和 `hciconfig -a` 都空，就先不要继续扫 IMU。
2. 如果 `rfkill` 没 block，但仍然没有 `hci0`，问题依旧是“没有可用控制器”，不是“被软硬阻塞”。
3. 如果 Xavier 板载蓝牙起不来，最快的恢复方案通常是接一个 Linux 支持良好的 USB 蓝牙 dongle。
4. 在控制器不存在之前，不要把时间花在 5 个 IMU 同时开机、改 MAC 地址或调整 `scan_warmup_s` 上。

---

## 10. 阶段五：检查和修改 MACS 配置

当前默认配置文件位于：

```text
config/default.yaml
```

迁移到 Xavier 后，你至少要检查下面这些配置项。

### 10.1 TB4117 视频节点

检查：

```yaml
camera:
  tb4117:
    device_index: 0
```

如果 Xavier 上热像仪不是 `/dev/video0`，你需要改成真实节点编号。

### 10.2 数据输出目录

检查：

```yaml
recording:
  output_dir: "data"
```

建议 bring-up 初期可以先保留相对路径，确保项目逻辑不变。

等你确认 SSD 稳定后，再把输出目录改到 SSD 路径，例如：

```yaml
recording:
  output_dir: "/mnt/macs_ssd/macs_data"
```

前提是项目里对应路径处理支持绝对路径。如果你不确定，先保守一点，保持项目目录内输出，然后再迁走数据目录。

### 10.3 mmWave 端口

检查：

```yaml
multimodal:
  mmwave:
    cli_port: "/dev/ttyUSB0"
    data_port: "/dev/ttyUSB1"
```

如果实际端口不同，必须改对后再运行。

### 10.4 IMU 启用集合

首次 bring-up 建议先只启用 1 个 IMU。

你可以两种方式控制：

1. 在 `config/default.yaml` 中设置 `active_devices`。
2. 运行时使用 `--imu-device` 参数覆盖。

示例：

```bash
python main.py --imu-device imu03_waist
```

---

## 11. 阶段六：按顺序验证每一类设备

这里是最关键的部分。顺序不要乱。

### 11.1 先验证系统层可见性

执行：

```bash
lsusb
ip -br addr
ls /dev/video* 2>/dev/null
ls /dev/ttyUSB* 2>/dev/null
bluetoothctl list
bluetoothctl show
hciconfig -a
df -h
```

你需要得到：

1. 能看到 USB 总线设备。
2. NYX650 所在网口已经有合理的 IP 配置。
3. TB4117 出现为视频设备。
4. mmWave 出现为串口设备。
5. 蓝牙控制器可用，而不是只有 `bluetooth.service` 在运行。
6. 磁盘空间足够。

### 11.2 跑项目自带总检查

```bash
cd ~/CUHK-Y/MAC/MACS
source .venv/bin/activate
python setup_check.py
```

通过标准：

1. `FAIL` 项必须清零。
2. `WARN` 项必须能解释。
3. 至少要确认 Python 包、NYX650 SDK、V4L2、串口、蓝牙、磁盘都过关。

### 11.3 单独诊断 TB4117

```bash
source .venv/bin/activate
python diagnose.py --tb
```

通过标准：

1. 能在 USB 层看到设备。
2. 能定位 `/dev/videoX`。
3. `v4l2-ctl` 能列出支持格式。
4. OpenCV 能读到帧。

### 11.4 单独诊断 NYX650

```bash
source .venv/bin/activate
python diagnose.py --nyx
```

通过标准：

1. SDK 路径存在。
2. Python API 可导入。
3. 能识别到设备。

补充说明：如果 SDK sample 显示 `get device count: 0`，排查顺序应该是：

1. 先查网口，不要先怀疑 SDK 包。
2. 先确认主机和 NYX650 在同一子网。
3. 再确认发现包没有走错网卡。

建议追加执行：

```bash
ip -br addr
ip route
ip route get <camera_ip>
ping -I <nic_name> <camera_ip>
```

如果 `DeviceConnectBySN` 不行，但网络确认没问题，再直接试：

```bash
cd ~/ScepterSDK/MultilanguageSDK/Python/Samples/NYX650/DeviceConnectByIP
python3 DeviceConnectByIP.py
```

### 11.5 单独验证 mmWave 串口

先看设备：

```bash
ls /dev/ttyUSB*
dmesg | tail -100
```

如果你需要看串口身份，也可以用：

```bash
udevadm info -a -n /dev/ttyUSB0 | head -50
udevadm info -a -n /dev/ttyUSB1 | head -50
```

通过标准：

1. 你能稳定分辨 CLI 口和 data 口。
2. `config/profile_human.cfg` 已存在。

补充说明：如果 `main.py` 日志里是：

```text
mmWave prepare failed: [Errno 13] could not open port /dev/ttyUSB1
```

先按“权限问题”处理，而不是先按“串口映射错误”处理。只有当：

1. 当前用户已经在 `dialout` 组里。
2. `python serial.Serial(...)` 可以手工打开两个节点。
3. `lsof` 显示没有进程占用。

之后仍然失败，才值得去对调 `cli_port` 和 `data_port`。

另外，CLI 口适合用 `screen` / `minicom` 做简单连通性检查，但 Data 口是二进制协议流，不要把 `screen` 看不到可读文本当成故障证据。

### 11.6 单独诊断 IMU

推荐先顺序诊断单个 IMU：

```bash
source .venv/bin/activate
python tools/ble_imu_diagnose.py \
  --mode sequential \
  --device imu03_waist \
  --scan-seconds 8 \
  --notify-seconds 5
```

如果单个通过，再考虑多个设备：

```bash
python tools/ble_imu_diagnose.py \
  --mode sequential \
  --device imu01_left_wrist \
  --device imu02_right_wrist
```

输出会写到 JSON 摘要文件。你要重点看：

1. `scan_seen`
2. `connect_ok`
3. `services_ok`
4. `write_ok`
5. `notify_ok`

第一次 bring-up 时，不建议先跑 `concurrent` 模式。

补充说明：如果 `tools/ble_imu_diagnose.py` 或 `main.py` 一上来就报 `No Bluetooth adapters found.`，那连 `scan_seen` 这一步都还没开始，应该先回到“主机蓝牙控制器是否存在”的系统检查，而不是继续折腾 IMU 本体。

---

## 12. 阶段七：先跑无 UI 冒烟测试，再跑 UI

### 12.1 外设冒烟测试

这个测试不会启动完整 UI，但会调用同一套外设协调器。

```bash
cd ~/CUHK-Y/MAC/MACS
source .venv/bin/activate
python tools/multimodal_smoke_test.py --duration 15
```

如果你还在早期调试阶段，建议只保留一个 IMU：

```bash
python tools/multimodal_smoke_test.py \
  --duration 15 \
  --imu-device imu03_waist \
  --imu-ready-timeout 20
```

通过标准：

1. 能生成新的 smoke test session 目录。
2. session 目录下有 mmWave 和 IMU 的输出文件。
3. 终端 summary 没有关键错误。

### 12.2 先跑 UI Demo

在没完全确认真机输入前，先测试 UI 本身：

```bash
cd ~/CUHK-Y/MAC/MACS
source .venv/bin/activate
python main.py --demo
```

通过标准：

1. UI 能正常打开。
2. 预览区和状态栏能正常工作。
3. 没有 Qt 插件或 OpenCV 导入冲突。

### 12.3 再跑真实 UI

```bash
cd ~/CUHK-Y/MAC/MACS
source .venv/bin/activate
python main.py
```

第一次真实运行建议：

1. 只接最少必要设备。
2. 先录一小段短 session。
3. 先确认 session 目录完整生成。
4. 再加大时长和增加 IMU 数量。

如果想限制 IMU：

```bash
python main.py --imu-device imu03_waist
```

补充说明：如果真实 UI 里你看到的是“手已经伸进镜头，但 2 到 3 秒后画面才更新”，不要先假设所有模态都在硬件层掉帧。

这类现象很常见的根因是预览线程积压：

1. 采集线程持续送帧。
2. 主线程却在做全分辨率 QImage/QPixmap 转换和缩放。
3. 最后 UI 显示的是几秒前堆在队列里的旧画面。

当前仓库里已经在 `ui/main_window.py` 和 `ui/preview_panel.py` 里做了两项修复：

1. 预览只保留每个模态的最新帧，不再逐帧排队显示。
2. 预览先缩到 `config/default.yaml` 中的 `preview_width` / `preview_height` 再显示。

所以如果你仍然看到明显预览滞后，下一步应当对照状态栏 FPS 判断：

1. 若状态栏 FPS 正常但画面滞后，优先查 UI 渲染。
2. 若状态栏 FPS 本身就很低，再去查相机链路、USB 带宽或系统性能。

---

## 13. 首轮真实采集的建议操作顺序

你第一次真正采集时，建议按这个顺序来：

1. 只接 AGX Xavier、显示器、键鼠、网线、SSD。
2. 接 TB4117，确认视频节点正常。
3. 接 NYX650，确认 SDK 与设备识别正常。
4. 接 mmWave，确认串口号正确。
5. 只接 1 个 IMU，确认 BLE 能连通。
6. 跑 `setup_check.py`。
7. 跑 `multimodal_smoke_test.py`。
8. 跑 `main.py --demo`。
9. 跑 `main.py` 做 10 到 20 秒短录制。
10. 检查 raw 和 processed 是否按预期输出。

只有这 10 步都稳定以后，再开始接 5 个 IMU、长时间录制和批量实验。

---

## 14. 迁移完成后的验收标准

当下面这些都满足时，才算真正迁移完成：

1. AGX Xavier 可以稳定启动并通过 SSH 管理。
2. `setup_check.py` 无 `FAIL`。
3. `diagnose.py --tb` 通过。
4. `diagnose.py --nyx` 通过。
5. `tools/ble_imu_diagnose.py` 单设备顺序诊断通过。
6. `tools/multimodal_smoke_test.py` 能产出有效数据。
7. `main.py --demo` 能正常打开 UI。
8. `main.py` 能完成一次真实录制。
9. 输出目录中 session 数据完整。
10. 录制结束后的后处理链路可正常执行。

---

## 15. 最常见的坑和修复思路

### 15.1 坑一：刷错 JetPack 代际

表现：

1. 你按 Orin 文档装了不适合 Xavier 的版本。
2. 系统起来了，但后续兼容性一堆问题。

修复：

1. 退回 JetPack 5.1.x。
2. 重新刷机，不要继续在错代系统上堆补丁。

### 15.2 坑二：用 macOS 强行做 AGX Xavier 刷机

表现：

1. USB 恢复模式识别不稳定。
2. 缺少官方工具链。

修复：

1. 换 Ubuntu 20.04 x86_64 主机。

### 15.3 坑三：TB4117 不在 UVC 模式

表现：

1. 看不到 `/dev/video*`。
2. `v4l2-ctl` 找不到设备。

修复：

1. 先确认热像仪固件工作在 UVC 模式。
2. 再重新接入并执行 `diagnose.py --tb`。

### 15.4 坑四：NYX650 SDK 路径不对

表现：

1. `setup_check.py` 找不到 SDK。
2. `main.py` 启动后 NYX650 不工作。

修复：

1. 把 SDK 放到驱动实际搜索的目录。
2. 先用 SDK 自带 sample 验证，再跑项目。

补充：

1. 当前可直接使用公开仓库 `https://github.com/ScepterSW/ScepterSDK`。
2. AArch64 下的预编译 sample 实际是单个文件 `BaseSDK/AArch64/PrecompiledSamples/NYX650_OpenCVSample`。
3. 如果你还按旧目录 `NYX650_Samples/` 去找，文档路径本身就是错的。

### 15.5 坑五：NYX650 sample 能启动，但 `get device count: 0`

表现：

1. `NYX650_OpenCVSample` 能跑起来。
2. Python API 也能导入。
3. 但 sample 显示 `get device count: 0`。

修复：

1. 先检查网口和相机是否在同一子网。
2. 先检查 `ip route get <camera_ip>` 是否把流量送到了正确网卡。
3. 多网卡场景必须使用不同网段。
4. 单网口直连场景必须临时配静态 IP，而且不要配网关。
5. 必要时用 `DeviceConnectByIP` 绕过按序列号发现。

### 15.6 坑六：mmWave 串口号或串口权限在 Xavier 上变了

表现：

1. 雷达初始化失败。
2. CLI 和 data 串口接反。
3. 日志出现 `Permission denied: '/dev/ttyUSB1'`。

修复：

1. 先检查当前用户是否已真正加入 `dialout`。
2. 先确认 `lsof` 没有别的进程占用串口。
3. 先用最小 `serial.Serial(...)` 脚本验证两个节点都可打开。
4. 只有权限问题排除后，再用 `dmesg` 和 `udevadm info` 重新识别 CLI / data 口。
5. 修改 `config/default.yaml`。
6. 后续最好写 udev 规则做固定别名。

### 15.7 坑七：蓝牙服务在跑，但系统里没有 controller

表现：

1. `systemctl status bluetooth` 显示 active running。
2. `bluetoothctl list` 没输出。
3. `bluetoothctl show` 显示 `No default controller available`。
4. `hciconfig -a` 没有任何 `hci0`。
5. `main.py` 或 `ble_imu_diagnose.py` 报 `No Bluetooth adapters found.`

修复：

1. 不要继续调 IMU 设备本身。
2. 先确认 Xavier 是否真的枚举出了蓝牙控制器。
3. 检查 `lsusb`、`dmesg`、`lsmod` 是否有蓝牙硬件和驱动。
4. 如果板载蓝牙起不来，优先换一个 Linux 支持好的 USB 蓝牙 dongle。

### 15.8 坑八：一开始就把 5 个 IMU 全开

表现：

1. 只有一个能连上。
2. 其余设备连接超时或 BlueZ 报进行中错误。

修复：

1. 先单设备。
2. 再两个设备。
3. 最后再扩到全部。
4. 先用 `tools/ble_imu_diagnose.py --mode sequential` 做隔离诊断。

### 15.9 坑九：真实采集时 UI 画面晚 2 到 3 秒才更新

表现：

1. 真实人物动作已经发生。
2. UI 预览延迟数秒后才显示。
3. 快速移动几乎无法在预览里被捕捉。

修复：

1. 先区分“预览滞后”和“采样掉帧”。
2. 看状态栏 FPS，如果 FPS 正常但画面滞后，优先查 UI 线程积压。
3. 当前仓库已经在 `ui/main_window.py`、`ui/preview_panel.py` 中做了“只渲染最新帧 + 预览先缩小”的修复。
4. 如果仍然滞后，再去检查 USB 带宽、CPU 频率和真实采样 FPS。

### 15.10 坑十：把数据直接写系统盘

表现：

1. 长录制时掉帧。
2. 系统盘空间和写入性能变成瓶颈。

修复：

1. 正式采集时把数据写到 SSD。
2. 长时间录制前先做写入压测和磁盘容量检查。

---

## 16. 一个最保守但最稳的实操顺序

如果你只想按顺序做，不想自己判断，就按下面的命令序列执行。

### 16.1 板卡刷机后首次设置

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y \
  git curl wget vim tmux htop \
  build-essential pkg-config \
  python3-pip python3-venv python3-dev \
  python3-opencv python3-pyqt5 python3-numpy \
  v4l-utils usbutils \
  bluez bluetooth rfkill \
  libgl1 libglib2.0-0 libusb-1.0-0-dev \
  minicom screen
sudo systemctl enable ssh
sudo systemctl start ssh
sudo nvpmodel -m 0
sudo jetson_clocks
sudo usermod -aG dialout,video,plugdev,bluetooth $USER
sudo reboot
```

### 16.2 拉代码和建环境

```bash
cd ~
git clone <你的仓库地址> CUHK-Y
cd ~/CUHK-Y/MAC/MACS
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install PyYAML pyserial bleak
```

### 16.3 安装 SDK 后先跑检查

```bash
cd ~
git clone https://github.com/ScepterSW/ScepterSDK.git ~/ScepterSDK

ls ~/ScepterSDK/BaseSDK/AArch64/PrecompiledSamples
ls ~/ScepterSDK/MultilanguageSDK/Python/API

cd ~/ScepterSDK/BaseSDK/AArch64/PrecompiledSamples
chmod +x ./NYX650_OpenCVSample
./NYX650_OpenCVSample

cd ~/CUHK-Y/MAC/MACS
source .venv/bin/activate
python setup_check.py
python diagnose.py --tb
python diagnose.py --nyx
python tools/ble_imu_diagnose.py --mode sequential --device imu03_waist
python tools/multimodal_smoke_test.py --duration 15 --imu-device imu03_waist --imu-ready-timeout 20
python main.py --demo
python main.py --imu-device imu03_waist
```

---

## 17. 建议你迁移完成后立刻做的两件事

### 17.1 固定 mmWave 串口别名

如果你后面会频繁插拔设备，强烈建议用 udev 规则给雷达两个串口建立固定别名。

目标效果类似：

```text
/dev/mmwave_cli
/dev/mmwave_data
```

这样以后 `config/default.yaml` 不用反复改。

### 17.2 固定 SSD 挂载点

建议把 SSD 稳定挂载到固定目录，例如：

```text
/mnt/macs_ssd
```

后续再把录制输出稳定指向这个路径。

---

## 18. 最后一句话的执行原则

迁移 Xavier 不要追求“一次点亮全部功能”，而要追求“每一步都能证明确实通了”。

你真正该做的是：

1. 先通系统。
2. 再通依赖。
3. 再通单设备。
4. 再通组合。
5. 最后才通完整采集任务。

只要你严格按本文档顺序执行，整个迁移是可控的。