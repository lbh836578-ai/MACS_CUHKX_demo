# CUHK-Y 预实验执行手册：硬件采购与测试

> 版本：v1.1 | 负责人：[待填] | 创建日期：2026-04-05 | 最近修订：2026-04-19
> 
> **本文档目的**：拿到这份文档的人可以直接执行——买设备、搭环境、跑测试、交报告。

---

## 第零部分：系统全貌与复现原则

### 0.1 先用一句话理解这个项目

这不是“在一台树莓派上装几个包”的项目，而是一个**多设备、双模态、离线分析为主**的采集系统。你要同时搭起 4 条链路：

1. **Wi-Fi CSI 链路**：人体动作改变无线传播路径，RPi 采到 CSI，保存为 pcap
2. **环境音频链路**：ReSpeaker 2-Mics Pi HAT v2 采到 2 通道环境声，保存为 wav
3. **个人音频链路**：领夹麦通过 USB 声卡采到个人近端语音；可以是一块双输入声卡录成 1 个 2 通道 wav，也可以是两块单输入声卡各录成 1 个单通道 wav
4. **同步与分析链路**：NTP + 拍手完成时间对齐，分析电脑把 pcap/wav 转成图、特征和指标

你最终不是只要“录到东西”，而是要回答 4 个研究问题：

- 单人动作能否从 CSI 中稳定区分
- 双人动作混在一起时，CSI 是否还能分离或至少区分条件
- 环境麦是否足以支持双人语音分析，还是必须上个人麦
- 同一台 RPi 上同时跑 CSI 和 Audio 是否会相互干扰

### 0.2 物理连接和模块之间的关系

```text
控制电脑 / WSL2 / 实验室主机
  |  SSH / rsync / Python分析 / VS Code Remote
  |
千兆交换机 ---------------------------------- 5GHz AP/路由器（固定信道）
 |              |              |               |
RPi-1         RPi-2         RPi-3          RPi-4
CSI流量源      CSI Rx+Env    穿墙 Rx+Env     个人麦录制
 |              |              |               |
 | built-in Wi-Fi sensing      | built-in Wi-Fi sensing
 +-------------- 空口 Wi-Fi CSI 链路 ----------+

ESP32-S3-A .............................. ESP32-S3-B
    可选穿墙 CSI 辅助链路（与 RPi 链路分开验证）
```

这里有一个非常关键的工程点：

- **以太网/交换机**负责远程管理、SSH、NTP、拷数据
- **RPi 自带 Wi-Fi（wlan0）**负责 CSI 感知

这两件事**不要共用同一张无线网卡**。因为做 CSI 时你通常要停掉 `wpa_supplicant`、固定信道、切 monitor mode；如果你靠 `wlan0` 远程登录，SSH 很容易直接断掉。

### 0.3 每个模块到底做什么

| 模块 | 跑在哪 | 输入 | 输出 | 它在系统里的作用 |
|------|--------|------|------|------------------|
| CSI 流量源 | RPi-1 | 固定 5GHz AP、`ping`/`iperf3` 等流量命令 | 稳定 Wi-Fi 帧 | 决定 CSI 的采样速率和稳定性 |
| Nexmon CSI 采集 | RPi-2 / RPi-3 | 空口 Wi-Fi 帧 | `*.pcap` | 从 Broadcom 芯片固件中提取每帧 CSI |
| 环境音频采集 | RPi-2 / RPi-3 + ReSpeaker 2-Mics Pi HAT v2 | 2 通道麦克风信号 | `*.wav` | 录下环境声、双人说话、拍手同步信号 |
| 个人音频采集 | RPi-4 + 1 块双输入 USB 声卡，或 2 块单输入 USB 声卡 | 2 个领夹麦 | 1 个 2 通道 wav，或 2 个 1 通道 wav | 作为双人语音的近端 ground truth |
| ESP32 穿墙辅助链路 | ESP32-S3 A/B | Wi-Fi CSI 示例固件 | 串口 CSI 输出 / 日志 | 验证低成本穿墙可检测性 |
| 时间同步 | 所有设备 | `chrony` + 拍手 | 对齐后的时间基准 | 让 CSI 和 Audio 落在同一条时间轴上 |
| 离线解析 | 控制电脑 / GPU 主机 | pcap、wav、metadata | 图表、特征、指标 | 生成 SNR、SDR、分类结果和结论 |

### 0.4 这些包和工具分别起什么作用

#### 采集侧工具

| 包/工具 | 跑在哪 | 作用 | 你什么时候会用到 |
|---------|--------|------|------------------|
| `nexmon` | RPi | Broadcom 固件 patch 框架 | 编译和安装 CSI 固件时 |
| `nexmon_csi` | RPi | 真正把 CSI 提取逻辑打进固件 | 安装 CSI 功能时 |
| `makecsiparams` | RPi | 生成 CSI 采集参数字符串 | 指定信道、带宽、core、stream 时 |
| `nexutil` | RPi | 把 CSI 参数下发到 Wi-Fi 固件 | 开始采集前 |
| `tcpdump` | RPi | 把 UDP 5500 上的 CSI 数据保存成 pcap | 录制原始 CSI 文件时 |
| `seeed-linux-dtoverlays` | RPi | 安装 ReSpeaker 2-Mics Pi HAT v2 的设备树 overlay | 让 2-Mic v2 被系统识别 |
| `alsa-utils` | RPi | 提供 `arecord`、`aplay`、`amixer` | 实际录音、回放、调音量 |
| `chrony` | 所有 RPi | 局域网时间同步 | 多设备对齐 |
| `tmux` | RPi | 后台运行长时间采集任务 | 避免 SSH 断开导致任务中止 |

#### 分析侧工具

| 包/工具 | 跑在哪 | 作用 | 备注 |
|---------|--------|------|------|
| `nexcsi` | 分析电脑 | 离线解析 Nexmon pcap | 只负责“读文件”，不负责采集 |
| `numpy` / `scipy` / `pandas` | 分析电脑 | 数值处理、统计、特征工程 | 基础分析必备 |
| `matplotlib` | 分析电脑 | 画 CSI 幅度图、频谱图、趋势图 | 报告配图 |
| `scikit-learn` | 分析电脑 | SVM、PCA、ICA 等基线算法 | 单人分类和分离尝试 |
| `librosa` / `soundfile` | 分析电脑 | 音频读取、频谱、能量、特征提取 | 环境声和语音分析 |
| `ffmpeg` | 分析电脑 / GPU 主机 | 音频视频转码和解码 | `pyannote.audio` 依赖它做音频解码 |
| `pyannote.audio` | 分析电脑 / GPU 主机 | 说话人分段、说话人计数、重叠说话检测 | 它更偏 diarization，不是开箱即用的高质量波形分离 |
| `VisualVoice` | GPU 主机 | 音视频联合语音分离 | 需要同步视频、嘴部跟踪和 GPU，属于高级可选项 |

### 0.5 新手最容易误解的 8 件事

1. **CSI 不是固定采样率传感器。** 它按“收到多少帧 Wi-Fi 帧”来决定采样密度，所以发包端的流量模式直接决定你的时间分辨率。
2. **`tcpdump` 抓到的不是普通 monitor mode 原始 802.11 帧。** 对 Nexmon 来说，它实际是在把固件导出的 CSI UDP 包保存下来。
3. **在 Raspberry Pi 3B+/4B 上，CSI UDP 包通常监听 `wlan0`，不是 `mon0`。** `mon0` 是 monitor 接口，但 Nexmon README 明确提醒 Pi 平台抓 CSI 时不要只盯着 `mon0`。
4. **`nexcsi` 只是离线解析器。** 它不会让你“开始采集”，只能把已经录好的 pcap 解码成数组。
5. **ReSpeaker 的驱动/overlay 不是录音软件。** 它只是把 ReSpeaker 变成 Linux 能识别的声卡；真正录音的是 `arecord`。
6. **`pyannote.audio` 更适合先做 diarization。** 也就是“谁在什么时候说话”；如果你要的是干净的双人语音分离波形，它不是最轻量的第一选择。
7. **`VisualVoice` 不能作为第一阶段 baseline。** 没有同步视频、GPU 和嘴部 ROI 预处理时，它基本不适合直接拿来做预实验首轮验证。
8. **NTP 只能给你粗对齐，拍手才是细对齐。** 多模态实验里这两个都要做，缺一个都会让后处理变得很痛苦。

### 0.6 推荐的搭建顺序

请按下面顺序搭，不要一上来四台设备一起开：

1. 先把 4 台 RPi 的**网线管理链路**搭起来，能稳定 SSH
2. 只做 **RPi-1 -> RPi-2** 的单条 CSI 链路，先拿到一份可解析 pcap
3. 只做 ReSpeaker 和个人麦，先拿到环境麦 wav 和个人麦 ground truth wav
4. 再做 NTP + 拍手同步
5. 最后才做 CSI + Audio 共存、双人实验和穿墙实验

---

## 第一部分：硬件采购

### 采购总表

| # | 设备名称 | 型号 | 数量 | 单价（估） | 总价（估） | 采购渠道 | 用途 |
|---|---------|------|------|----------|----------|---------|------|
| 1 | Raspberry Pi 4 Model B | 4GB RAM | 4 | ¥400 | ¥1,600 | 淘宝/官方代理 | CSI 采集节点 + Audio 环境麦主机 |
| 2 | MicroSD 卡 | 128GB, Class 10 | 4 | ¥50 | ¥200 | 京东 | RPi 系统盘 + 数据存储 |
| 3 | RPi 电源适配器 | 5V/3A Type-C | 4 | ¥30 | ¥120 | 随 RPi 购买 | RPi 供电 |
| 4 | ReSpeaker 2-Mics Pi HAT v2 | for Raspberry Pi | 3 | ¥250 | ¥750 | Seeed Studio 官网 / 淘宝 | 环境麦克风（每房间 1 个） |
| 5 | BOYA BY-M1 Pro 领夹麦 | — | 2 | ¥150 | ¥300 | 京东 | 双人个人麦克风 |
| 6 | USB 声卡 | 双通道, 48kHz, 16/24-bit | 1 | ¥150 | ¥150 | 淘宝 | 领夹麦接入 RPi |
| 7 | 外接 SMA 天线（5GHz） | 全向, 5dBi | 4 | ¥30 | ¥120 | 淘宝 | CSI 信号增强 |
| 8 | ESP32-S3 开发板 | DevKitC-1 | 4 | ¥30 | ¥120 | 淘宝 | 穿墙 CSI 辅助节点 |
| 9 | 网线 + 交换机 | Cat6 + 5口千兆 | 1套 | ¥100 | ¥100 | 京东 | RPi 局域网互联（NTP 同步） |
| 10 | 麦克风支架/固定夹 | 桌面/天花板安装 | 3 | ¥30 | ¥90 | 淘宝 | 环境麦固定 |
| 11 | USB 移动硬盘 | 1TB | 1 | ¥350 | ¥350 | 京东 | 数据备份 |
| **合计** | | | | | **¥3,900** | | |

### 采购注意事项

- **RPi4**：确认购买的是 **BCM43455c0** Wi-Fi 芯片版本（绝大多数 RPi4 都是），Nexmon CSI 依赖此芯片
- **ReSpeaker 2-Mics Pi HAT v2**：确认是 **Raspberry Pi HAT v2 版本**（不是 USB 版）
- **ESP32-S3**：选带外置天线接口（IPEX）的版本，方便后续换天线
- **USB 声卡**：需支持 48kHz 采样率和双通道同时录入，购前确认 Linux/ALSA 兼容
- **个人麦替代采购方案**：如果买不到一块真正双输入的 USB 声卡，可以改买 2 块单输入、明确支持 ALSA 的 USB 声卡，固定对应参与者 A 和 B，后文按 `lavA` / `lavB` 两条单声道 ground truth 处理
- **5GHz AP/路由器**：Nexmon CSI 需要固定信道的参考网络。如果实验室没有现成、且可手动锁定 5GHz 信道的 AP，请额外准备 1 台双频路由器

### 采购时间要求

**在第 1 周内完成全部采购。** 等待到货期间开始软件环境准备（§第二部分-Step 1）。

---

## 第二部分：Wi-Fi CSI 系统搭建与测试

### Step 1：Nexmon CSI 环境搭建（第 1 周）

**目标**：4 台 RPi4 中的 3 台刷入 Nexmon CSI 固件，验证能稳定采集 CSI 数据。

#### 1.0 开始前的硬规则

先不要急着装包。先把 4 台 RPi 的**控制网络**固定下来，否则后面一旦 `wlan0` 切 CSI 模式，你会直接失联。

推荐的最小网络规划如下：**管理网络使用 eth0 私有子网（10.0.50.0/24），通过自带的千兆交换机互联，与场地路由器/Wi-Fi 完全独立。** 换场地时管理网络零修改，只需更新 CSI 感知用的 AP SSID/密码。

| 设备 | 主机名建议 | eth0 管理 IP | 用途 |
|------|------------|-------------|------|
| 控制电脑 / Mac / WSL2 | `cuhky-host` | `10.0.50.10` | SSH、rsync、离线分析 |
| RPi-1 | `rpi-csi-tx` | `10.0.50.11` | CSI 流量源 |
| RPi-2 | `rpi-csi-rx-a` | `10.0.50.12` | 室内 CSI Rx + 环境音频 |
| RPi-3 | `rpi-csi-rx-b` | `10.0.50.13` | 穿墙 CSI Rx + 环境音频 |
| RPi-4 | `rpi-lav-audio` | `10.0.50.14` | 个人麦录制 |
| 5GHz AP/路由器 | `cuhky-ap` | （场地现有 AP，IP 随场地变化） | 固定信道参考网络（仅用于 CSI 感知） |

> **为什么用 10.0.50.0/24？** 这个段几乎不会和任何场地网络冲突。静态 IP 配在 eth0（有线）上，随设备迁移，无需修改。
>
> **到新场地只需改什么？** RPi-1 的 `wpa_supplicant.conf` 里的 SSID/密码，以及 `makecsiparams` 里的信道号。

#### Bootstrap 首次开机流程（先有鸡还是先有蛋）

> **64-bit 系统提醒**：如果你使用的是 arm64 的 Raspberry Pi OS（例如 Bookworm/Trixie 64-bit），Nexmon 的部分 buildtools 仍会依赖 32-bit ARM 兼容环境。遇到 `Exec format error`、工具直接跑不起来时，不要先怀疑源码，先回头检查是否缺 armhf 兼容库，并对照官方 recent-kernel discussion 补依赖。

新 RPi 第一次开机时还没有配静态 IP，交换机上也没有 DHCP 服务器，eth0 只会拿到 `169.254.x.x` 链路本地地址。怎么 SSH 进去配 IP？

**答案：用 mDNS。** Raspberry Pi OS 默认自带 `avahi-daemon`，只要你在烧录时通过 Imager 设好了 hostname，第一次开机后就能用 `<hostname>.local` 直接连：

```bash
# 第一次开机，RPi 还没有静态 IP，但 mDNS 已经工作
ssh pi@rpi-csi-tx.local      # RPi-1
ssh pi@rpi-csi-rx-a.local    # RPi-2
ssh pi@rpi-csi-rx-b.local    # RPi-3
ssh pi@rpi-lav-audio.local   # RPi-4

# 登录后再配静态 IP（见下方），配完 reboot 即可
```

> **前提**：烧录时在 Raspberry Pi Imager 里**必须设好 hostname**，这是整个 bootstrap 能走通的关键。
> 控制电脑（Mac）和 RPi 必须插在同一台交换机上，mDNS 才能跨链路发现。

#### 控制电脑（Mac）侧的网络配置

Mac 的以太网口（USB 网卡或雷电转接）也要手动配到同一子网，否则和 RPi 无法通信,先开启互联网共享按键：

1. **系统设置 → 网络 → USB 以太网（或雷电网桥）**
2. 配置 IPv4：手动
   - IP 地址：`10.0.50.10`
   - 子网掩码：`255.255.255.0`
   - 路由器（网关）：**留空**
3. 应用

> Mac 的 Wi-Fi 继续正常上网，macOS 会自动按路由表分流：10.0.50.x 走有线，其他走 Wi-Fi。两者互不影响。

#### RPi 侧的 eth0 静态 IP 配置

**Bullseye（推荐系统）**——默认网络管理器是 `dhcpcd`，编辑 `/etc/dhcpcd.conf`：
```bash
# 以 RPi-2 为例，追加到 /etc/dhcpcd.conf 末尾
interface eth0
static ip_address=10.0.50.12/24
# 不设 routers 和 domain_name_servers，此子网不需要出外网
```

**⚠️ Bookworm 兼容性警告**：如果你使用了 Bookworm（Debian 12）系统，默认网络管理器已换成 `NetworkManager`，上面的 `dhcpcd.conf` 写法**无效**。需要改用 `nmcli`：
```bash
# Bookworm 上的等价操作（仅在你用了 Bookworm 时才需要）
sudo nmcli con mod "Wired connection 1" ipv4.method manual \
  ipv4.addresses 10.0.50.12/24
sudo nmcli con up "Wired connection 1"
```
> 这也是为什么文档推荐 Bullseye 的原因之一：Nexmon、ReSpeaker 驱动、dhcpcd 静态 IP 三者在 Bullseye 上都是开箱即用的。

#### mDNS 兜底（长期保留）

Raspberry Pi OS 默认已带 `avahi-daemon`。配完静态 IP 后也建议保留 mDNS，作为 IP 忘记时的备用登录方式：
```bash
# 确认 avahi 在运行（一般不需要额外安装）
systemctl status avahi-daemon
# 如果没有：
sudo apt install -y avahi-daemon && sudo systemctl enable avahi-daemon

# 之后始终可用 ssh pi@rpi-csi-rx-a.local 连接
```

在开始 Step 1 前，先满足下面 3 条：

1. 4 台 RPi 全部通过**网线**连到交换机，并且控制电脑可以稳定 `ssh` 登录
2. 现场有一个**固定 5GHz 信道**的 AP/路由器，建议参数：`5GHz only`、`channel 36`、`80MHz`、`WPA2-PSK`、关闭自动选信道/双频合一
3. 先只验证 **RPi-1 -> RPi-2** 这一条最小 CSI 链路，别一开始就同时开 ReSpeaker、ESP32、双人实验

#### 1.1 烧录系统

```bash
# 在电脑上操作
# 推荐基线系统：Raspberry Pi OS Lite (64-bit, Bullseye)
# 原因：ReSpeaker 驱动和 Nexmon 在 Bullseye/5.10 上更容易复现
# 如果 64-bit Bullseye 上 ReSpeaker 仍异常，回退到 32-bit Bullseye

# 使用 Raspberry Pi Imager 烧录到 MicroSD 卡
# 烧录时【必须】设置以下内容（这是 bootstrap 能走通的前提）：
# 1. 启用 SSH
# 2. 统一用户名密码（如 pi / yourpassword）
# 3. 给每台机器设置不同 hostname（rpi-csi-tx / rpi-csi-rx-a / rpi-csi-rx-b / rpi-lav-audio）
# 4. 【不要】预配置 Wi-Fi（管理走网线，Wi-Fi 留给 CSI）
#
# ⚠️ hostname 必须在此步设好，否则首次开机无法通过 mDNS 登录
```

建议第一次启动后，在每台机器上先做一次基础初始化：

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y linux-headers-$(uname -r) git tmux rsync chrony tcpdump iw wireless-tools net-tools \
  alsa-utils sox python3-pip python3-venv htop
sudo timedatectl set-timezone Asia/Hong_Kong
mkdir -p ~/pilot/{data,logs,tmp}
#步骤1
# 查看当前NTP源状态
chronyc sources -v

# 强制重新同步
sudo systemctl restart chronyd

# 等待10秒后验证
sleep 10 && timedatectl status | grep synchronized
```
步骤二：修改 chrony 配置，防止复发
```
sudo nano /etc/chrony/chrony.conf
```
添加以下行：
```
# 允许启动时无限次跳步修正（-1 = 无限次）
makestep 1 -1

# 指定可靠的NTP服务器（香港推荐）
server time.apple.com iburst
server ntp.aliyun.com iburst
server pool.ntp.org iburst

# 记录时钟漂移
driftfile /var/lib/chrony/drift

# 退出nano模式 重启服务使配置生效
sudo systemctl restart chronyd

#验证流程
# 检查同步源
chronyc sources -v

# 期望输出示例：
# ^* twtpe2-ntp-001.aaplimg.com  ← * 表示当前使用的源

# 检查同步状态
timedatectl status
# System clock synchronized: yes  ← 应该变回 yes
```
#### 1.2 安装 Nexmon CSI

参考官方仓库：https://github.com/seemoo-lab/nexmon_csi

```bash
# 以下在 RPi-1 / RPi-2 / RPi-3 上分别执行
sudo apt update && sudo apt upgrade -y
sudo apt install -y git libgmp3-dev gawk qpdf \
  bison flex make xxd automake autoconf libtool texinfo tcpdump iw \
  wireless-tools net-tools python3-pip pkg-config libnl-3-dev libnl-genl-3-dev
sudo reboot

# 重连后继续
git clone https://github.com/seemoo-lab/nexmon.git ~/nexmon
cd ~/nexmon

# 设置编译环境
source setup_env.sh

# 先在 nexmon 根目录完成基础构建
make

# recent-kernel 路线的关键：nexutil 必须带 vendor command 支持
cd ~/nexmon/utilities/nexutil
make USE_VENDOR_CMD=1
sudo make install USE_VENDOR_CMD=1
sudo setcap cap_net_admin+ep /usr/bin/nexutil

# 进入 bcm43455c0 对应目录，再把 nexmon_csi clone 进去
cd ~/nexmon/patches/bcm43455c0/7_45_189
git clone https://github.com/seemoo-lab/nexmon_csi.git
cd nexmon_csi

# recent-kernel / Raspberry Pi OS 路线：安装补丁固件并重载
make -f Makefile.rpi install-firmware
make -f Makefile.rpi reload-full
```

> 说明 1：官方 README 里 bcm43455c0 的经典路径是 `patches/bcm43455c0/7_45_189`，不要直接照抄其他博客里过时的目录名。
>
> 说明 2：如果你使用的是 Bookworm、Trixie 或 `6.12.x+rpt-rpi-v8` 这类 recent-kernel，正确路径是“补丁固件 + `USE_VENDOR_CMD=1` 编译的 `nexutil` + `Makefile.rpi`”，而不是老博客里的 patched `brcmfmac.ko` 路线。
>
> 说明 3：如果 `nexutil` 编译时报 `libnl` 相关错误，先补齐 `libnl-3-dev`、`libnl-genl-3-dev` 和 `pkg-config`；如果运行时还是出现老 netlink 路线的报错，优先确认你是否真的用了 `USE_VENDOR_CMD=1` 重新编译并安装。

#### 1.2.1 recent-kernel 实战备注（本次排障得到的经验）

- `makecsiparams` 一定要先单独编译并验证输出；如果 `PARAMS` 是空字符串，就不要继续执行 `nexutil -s500`
- 如果补丁汇编时报 `Parser ERROR ... jext COND_RX_IFS2, skip+`，通常不是补丁本身坏了，而是 `buildtools/b43-v3/assembler` 需要在装好 `flex` / `bison` 后重建
- `make clean` 会把 `obj`、`gen`、`log` 一并删掉；后续如果再遇到 `log/disass.log` 不存在，先 `mkdir -p obj gen log` 再重跑
- recent-kernel 路线里，真正值得信任的 monitor 状态读数是 `nexutil -m`，不是 `iwconfig` 里那一行 `Mode`

#### 1.3 验证 CSI 采集

```bash
# 在 RPi-2 或 RPi-3 上执行，假设你当前在有线 SSH 下操作
cd ~/nexmon/patches/bcm43455c0/7_45_189/nexmon_csi

# recent-kernel 路线先重载固件；unmanage 如果提示 device not active，通常不是致命问题
make -f Makefile.rpi unmanage || true
make -f Makefile.rpi reload-full

# 停掉自动管 Wi-Fi 的进程，避免信道被改回去
sudo nmcli dev set wlan0 managed no || true
sudo pkill wpa_supplicant || true
sudo ifconfig wlan0 up

# 生成 CSI 参数：固定在 channel 36 / 80MHz，采 1 个 core 和 1 个 spatial stream
PARAMS=$(./utils/makecsiparams/makecsiparams -c 36/80 -C 1 -N 1)
echo "$PARAMS"

# recent-kernel 下优先用 nexutil 的 chanspec，而不是 iw set channel
sudo nexutil -Iwlan0 -k36/80
nexutil -Iwlan0 -k

# 下发 CSI 提取配置并打开 monitor
sudo nexutil -Iwlan0 -s500 -b -l34 -v"$PARAMS"
sudo nexutil -Iwlan0 -m1
nexutil -m

# 最快验证：先不写文件，直接看 5500 端口是否有 CSI UDP
sudo tcpdump -ni wlan0 udp dst port 5500 -c 20

# 再正式写文件；不要复用旧文件名，避免 tcpdump 降权后覆盖失败
sudo rm -f /tmp/test_csi.pcap
sudo tcpdump -ni wlan0 udp dst port 5500 -w /tmp/test_csi.pcap -c 1000

# 用 Python 做最小离线验证
python3 -m venv ~/venvs/csi-check
source ~/venvs/csi-check/bin/activate
pip install --upgrade pip
pip install nexcsi numpy matplotlib
python3 -c "
from nexcsi import decoder
import numpy as np
samples = decoder('raspberrypi').read_pcap('/tmp/test_csi.pcap')
csi = decoder('raspberrypi').unpack(samples['csi'], zero_nulls=True, zero_pilots=True)
print(f'Packets: {len(samples)}')
print(f'Subcarriers: {csi.shape[-1]}')
print(f'Mean amplitude: {np.abs(csi).mean():.3f}')
"
```

> 如果 `python3 -m venv` 报缺模块，先执行 `sudo apt install -y python3-venv python3-full`。Bookworm / Trixie 上不要默认直接用系统级 `python3 -m pip install ...`，否则会触发 `externally-managed-environment`。

这些命令分别在做什么：

| 命令/工具 | 作用 |
|-----------|------|
| `make -f Makefile.rpi ...` | recent-kernel 下安装/重载补丁固件，并让 `wlan0` 进入可控状态 |
| `pkill wpa_supplicant` | 停掉自动联网程序，避免它把信道抢回去 |
| `makecsiparams` | 生成 CSI 过滤配置字符串 |
| `nexutil -k...` | 读取或设置当前 chanspec；recent-kernel 下优先用它锁信道 |
| `nexutil` | 把 CSI 配置写入 Broadcom 固件 |
| `nexutil -m` | 读取 monitor 模式状态；比 `iwconfig` 更可信 |
| `tcpdump -ni wlan0 udp dst port 5500` | 把 Nexmon 导出的 CSI UDP 包写进 pcap，也是最快的在线验收方式 |
| `decoder('raspberrypi')` | 用正确的 Raspberry Pi 解码器离线解析 pcap |

**验收标准**：
- [  ] 能采集到 CSI 数据包
- [  ] 子载波数 ≥ 64（20MHz）或 ≥ 242（80MHz）
- [  ] 采样率 ≥ 100 packets/s（连续采集 10 秒，包数 ≥ 1000）
- [  ] 能在分析电脑上画出一条随时间变化的 CSI 幅度曲线

如果你已经看到 `monitor: 1`，并且 `sudo tcpdump -ni wlan0 udp dst port 5500` 可以持续抓到包，那么从工程判断上说，Rx 通路已经打通了。

#### 1.3.1 两台 Pi 最小 bring-up（当前实测最快）

如果你当前只想最快搭通一条 `pi2 = Tx`、`pi3 = Rx` 的 CSI 链路，先不要把系统复杂化，按下面做。

先在 pi3 上做状态回读，确认它当前真的在你以为的信道上，并且之前抓到的文件里确实是 CSI UDP：

```bash
nexutil -Iwlan0 -k
sudo tcpdump -nn -r /tmp/test_csi.pcap -c 10
```

然后把 pi2 固定到同一信道并持续发帧。两种最省事的方式如下：

```bash
# 方式 A：已经有固定信道 AP wlan0的，就让 pi2 连 AP 并持续发流量
ping -I wlan0 -i 0.02 <AP_IP>
# 或
iperf3 -u -c <SERVER_IP> -b 20M -l 1470 -t 600

# 方式 B：如果你想先脱离场地 AP 自测，pi2 直接开固定信道热点
sudo nmcli dev wifi hotspot ifname wlan0 ssid csi-lab password 12345678 band bg channel 1
```

> 如果你走方式 B，pi3 也要切到相同的 chanspec，例如 `sudo nexutil -Iwlan0 -k1/20`。如果你走方式 A 且 AP 固定在 `36/80`，那就保持 `sudo nexutil -Iwlan0 -k36/80`。
>
> 对 recent-kernel 路线，优先用 `nexutil -k<chanspec>` 锁信道，不要把 `iw dev wlan0 set channel ...` 当默认做法；如果你看到 `Operation not supported (-95)`，通常就是这里不匹配。

#### 1.4 配置 3 台 RPi4 的角色

| RPi | 角色 | 位置 | 说明 |
|-----|------|------|------|
| RPi-1 | CSI Tx（流量源） | 房间 A 角落 | 连接固定 5GHz AP，稳定产生可控 Wi-Fi 流量 |
| RPi-2 | CSI Rx + Audio（环境麦） | 房间 A 对角 | 同时采集 CSI + 环境音频 |
| RPi-3 | CSI Rx + Audio（环境麦） | 房间 B | 穿墙接收 + 环境音频 |
| RPi-4 | Audio（个人麦录制） | 桌面 | 接 1 块双输入 USB 声卡，或 2 块单输入 USB 声卡 + 2 个领夹麦 |

RPi-1 的“发包机”不是一个抽象概念，而是要**持续产生可控流量**。最简单的做法是把 RPi-1 连到固定 5GHz AP 上，然后持续 `ping` AP；如果要更高、更平滑的速率，可以用 `iperf3`。

```bash
# 最小可复现流量源：持续 ping AP
ping -i 0.02 <AP_IP>

# 需要更高流量时（先在控制电脑或另一台机器上启动 iperf3 -s）
iperf3 -u -c <SERVER_IP> -b 20M -l 1470 -t 600
```

记住：**CSI 采样率由发包端的帧速率决定，不是由接收端设置一个固定 Hz。**

### Step 2：ESP32-S3 穿墙节点搭建（第 1 周，与 Step 1 并行）

**目标**：至少准备 1 块发送端和 1 块接收端，先在无遮挡环境跑通，再移到墙两侧。ESP32 链路主要是穿墙可检测性的辅助验证，不能直接把数值幅度和 Nexmon 链路硬比较。

```bash
# 建议在 Ubuntu 或 WSL2 中执行；下面是 Linux shell 命令
# 如果你在纯 Windows 上操作，请使用官方 ESP-IDF installer，并把串口名替换为 COMx

# 安装 ESP-IDF
git clone --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh esp32s3
. ./export.sh

# 获取 ESP-CSI 示例工程
git clone https://github.com/espressif/esp-csi.git

# 第一块板子：发送端
cd esp-csi/examples/get-started/csi_send
idf.py set-target esp32s3
idf.py menuconfig   # 配置 Wi-Fi SSID / password / channel 等参数
idf.py build
idf.py flash -p /dev/ttyUSB0
idf.py monitor

# 第二块板子：接收端
cd ../csi_recv
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py flash -p /dev/ttyUSB1
idf.py monitor  # 查看 CSI 输出
```

这里每个组件的职责是：

| 组件 | 作用 |
|------|------|
| `ESP-IDF` | ESP32 的官方开发框架，负责编译、烧录、monitor |
| `esp-csi` | Espressif 提供的 CSI 示例仓库 |
| `csi_send` | 主动发包的固件，用来制造稳定无线活动 |
| `csi_recv` | 接收并输出 CSI 的固件 |
| `csi_recv_router` | 如果你想让路由器承担一部分发包作用时可选用 |

**验收标准**：
- [  ] 2 台 ESP32 能建立 Tx-Rx 链路
- [  ] 能持续输出 CSI 幅度数据

### Step 3：CSI 预实验（第 2-3 周）

#### 实验 3.1：单人基线

| 参数 | 设置 |
|------|------|
| 参与者 | 1 人（团队成员即可） |
| 动作 | 5 类：站立不动、在房间内行走、坐下/站起、挥手、空房间（无人） |
| 重复 | 每类 20 次，每次 5 秒 |
| 采集 | RPi-1 发包 --> RPi-2 接收（室内链路） |

**执行步骤**：
1. 启动 RPi-1 发包、RPi-2 录制
2. 用拍手标记每个动作起止（同时录音，方便后对齐）
3. 参与者按指令执行动作
4. 保存 pcap 文件，命名：`csi_single_{action}_{trial}.pcap`

**交付物**：
- [  ] 5×20 = 100 个 CSI 片段
- [  ] 每类动作的 CSI 幅度时序图（可视化）
- [  ] 简单分类结果（SVM 或 1D-CNN，5 分类准确率）

#### 实验 3.2：双人分离（最关键）

| 参数 | 设置 |
|------|------|
| 参与者 | 2 人 |
| 条件 | 见下表 |
| 重复 | 每条件 15 次，每次 10 秒 |

| 条件 | Person A | Person B | 验证目标 |
|------|----------|----------|---------|
| D1 | 行走 | 静止站立 | 混合信号中能否提取 A 的运动 |
| D2 | 静止站立 | 行走 | 对称验证 |
| D3 | 行走（顺时针） | 行走（顺时针） | 同向运动的信号叠加 |
| D4 | 行走（顺时针） | 行走（逆时针） | 反向运动的信号差异 |
| D5 | 两人共同搬运一个箱子 | （同左） | 同步协作信号 |
| D6 | 模拟切菜动作 | 旁边站立观看 | 模拟真实协作场景 |

**执行步骤**：
1. 双人进入房间 A，RPi-1 发包，RPi-2 接收
2. 每个条件前口头报条件编号（录音记录）
3. 拍手标记起止
4. 文件命名：`csi_dual_{condition}_{trial}.pcap`

**交付物**：
- [  ] 6×15 = 90 个 CSI 片段
- [  ] 双人 vs 单人 CSI 的对比可视化（相同动作，1 人 vs 2 人时的信号差异）
- [  ] PCA/ICA 信号分离尝试结果
- [  ] 结论：是否可分离？分离程度如何？

#### 实验 3.3：穿墙测试

| 条件 | 房间 A | 房间 B | 采集节点 |
|------|--------|--------|---------|
| W1 | 空 | 空 | RPi-1(Tx,A) --> RPi-3(Rx,B) + ESP(A) --> ESP(B) |
| W2 | 1 人行走 | 空 | 同上 |
| W3 | 空 | 1 人行走 | 同上 |
| W4 | 1 人行走 | 1 人行走 | 同上 |

每条件 10 次，每次 15 秒。

**交付物**：
- [  ] 穿墙 vs 室内 CSI 信号质量对比（SNR 对比）
- [  ] 穿墙条件下能否检测到人体运动（W2 vs W1 的信号差异是否显著）
- [  ] 记录墙体材质和厚度

---

## 第三部分：Audio 系统搭建与测试

### Step 4：ReSpeaker 环境麦搭建（第 1 周，与 CSI 并行）

这一部分最容易被误解。请先记住一句话：**对你现在这块 ReSpeaker 2-Mics Pi HAT v2，优先使用 Seeed 官方的设备树 overlay 让系统识别声卡，真正录音的仍然是 ALSA 的 `arecord`。**

换句话说，驱动装好不等于你已经会录音；你还需要确认声卡编号、通道数、采样率和文件格式都对。

#### 4.1 安装 ReSpeaker 驱动

```bash
# 在 RPi-2 和 RPi-3 上执行（这两台同时负责 CSI 和 Audio）
sudo apt install -y git make device-tree-compiler alsa-utils sox i2c-tools
cd ~
rm -rf seeed-linux-dtoverlays
git clone https://github.com/Seeed-Studio/seeed-linux-dtoverlays.git
cd seeed-linux-dtoverlays

CONFIG=/boot/config.txt
[ -f /boot/firmware/config.txt ] && CONFIG=/boot/firmware/config.txt
OVERLAYS=/boot/overlays
[ -d /boot/firmware/overlays ] && OVERLAYS=/boot/firmware/overlays

make overlays/rpi/respeaker-2mic-v2_0-overlay.dtbo
sudo cp overlays/rpi/respeaker-2mic-v2_0-overlay.dtbo "$OVERLAYS/respeaker-2mic-v2_0.dtbo"

grep -q '^dtoverlay=respeaker-2mic-v2_0$' "$CONFIG" || echo 'dtoverlay=respeaker-2mic-v2_0' | sudo tee -a "$CONFIG"
grep -q '^dtparam=i2c_arm=on$' "$CONFIG" || echo 'dtparam=i2c_arm=on' | sudo tee -a "$CONFIG"
grep -q '^dtparam=i2s=on$' "$CONFIG" || echo 'dtparam=i2s=on' | sudo tee -a "$CONFIG"

sudo reboot

# 验证
arecord -l  # 先确认系统识别到 ReSpeaker 声卡编号或名称

# 注意：不要死写 CARD 名称，下面把 <ReSpeaker_CARD> 替换成实际 card 名称或 card 编号
arecord -D plughw:<ReSpeaker_CARD>,0 -c 2 -r 48000 -f S16_LE -d 5 test_2ch.wav
soxi test_2ch.wav   # 应看到 Channels: 2, Sample Rate: 48000
```

如果 `arecord -l` 里根本没有看到 ReSpeaker，对你来说这通常意味着以下 3 种情况之一：

1. HAT 没有插紧，GPIO 接触不良
2. `dtoverlay=respeaker-2mic-v2_0` 没有写进启动配置
3. overlay 文件没有正常复制到系统的 overlays 目录

#### 4.2 安装个人麦录制环境

正式方案优先仍然是 **1 块双输入 USB 声卡 + 2 只领夹麦**。但如果你买不到这种设备，用 **2 块单输入 USB 声卡 + 2 只领夹麦** 也可以继续做正式实验。

这里真正的要求不是“必须只有一块声卡”，而是：

1. 参与者 A 和参与者 B 各自都有一条稳定的近端语音轨。
2. 两条近端语音轨都能和环境麦、CSI 在同一轮试次内对齐。
3. 每轮实验里，A/B 和对应麦克风、对应声卡的映射保持不变。

如果你用两块单通道声卡，推荐的硬件连接是：

```text
RPi-4
├── eth0 --------------> 交换机 / NTP / SSH
├── USB port 1 --------> USB 声卡 A --------> 领夹麦 A --------> 参与者 A
└── USB port 2 --------> USB 声卡 B --------> 领夹麦 B --------> 参与者 B
```

实际连接时注意 4 点：

1. `RPi-4` 继续用 `eth0` 接交换机，USB 只负责音频，不要让个人麦节点依赖 `wlan0` 做管理。
2. 两块 USB 声卡分别插到固定 USB 口；如果供电或接触不稳，改用**带供电的 USB Hub**，不要用廉价无供电分线器。
3. 领夹麦 A 只接声卡 A，领夹麦 B 只接声卡 B；实验全程固定 `A -> 参与者 A`、`B -> 参与者 B`。
4. 给两块声卡和两只领夹麦贴标签，避免换口后 ALSA card 编号变化却没人发现。

```bash
# 在 RPi-4 上执行
# 先看系统识别到了哪些 USB 音频设备
arecord -l  # 确认 USB 声卡被识别

# 方案 A：你有 1 块双输入 USB 声卡
# 用实际识别到的 USB 声卡 card 名称或编号替换 <USB_CARD>
arecord -D plughw:<USB_CARD>,0 -c 2 -r 48000 -f S16_LE -d 5 test_lav.wav
soxi test_lav.wav   # 应看到 Channels: 2, Sample Rate: 48000

# 方案 B：你有 2 块单输入 USB 声卡
# 用实际识别到的两个 card 名称或编号替换 <USB_CARD_A> 和 <USB_CARD_B>
arecord -D plughw:<USB_CARD_A>,0 -c 1 -r 48000 -f S16_LE -d 5 test_lavA.wav
soxi test_lavA.wav   # 应看到 Channels: 1, Sample Rate: 48000

arecord -D plughw:<USB_CARD_B>,0 -c 1 -r 48000 -f S16_LE -d 5 test_lavB.wav
soxi test_lavB.wav   # 应看到 Channels: 1, Sample Rate: 48000

# 再做一次并行录制，确认两张卡能同时工作
arecord -D plughw:<USB_CARD_A>,0 -c 1 -r 48000 -f S16_LE -d 5 test_lavA_sync.wav &
PID_A=$!
arecord -D plughw:<USB_CARD_B>,0 -c 1 -r 48000 -f S16_LE -d 5 test_lavB_sync.wav &
PID_B=$!
wait $PID_A
wait $PID_B
```

双单通道方案有 3 个执行细节必须记住：

1. **不要再写 `-c 2`。** 这时每张卡都应该按自己的单声道输入单独录。
2. **每轮实验都必须拍手。** 两块独立 USB 声卡通常不是同一个采样时钟，长录音可能有轻微漂移；NTP 管粗对齐，拍手管细对齐。
3. **后处理时不要先把两条单声道强行混成一个伪立体声文件。** `lavA.wav` 和 `lavB.wav` 应该被当成两个独立 ground truth 参考轨。

如果你已经把 `pilot/` 目录分发到树莓派上，也可以直接用脚本：

```bash
# 1 块双输入 USB 声卡
~/pilot/scripts/start_audio_lav.sh --session speech_V1_01 --card <USB_CARD> --duration 30

# 2 块单输入 USB 声卡
~/pilot/scripts/start_audio_lav.sh --session speech_V1_01 \
  --card-a <USB_CARD_A> --card-b <USB_CARD_B> --duration 30
```

第二种模式会输出两条文件：

- `speech_V1_01_lavA.wav`
- `speech_V1_01_lavB.wav`

**验收标准**：
- [  ] ReSpeaker 2 通道全部正常录制
- [  ] 个人麦链路达到 48kHz 采样率稳定
- [  ] 如果是双输入声卡：2 个人声通道正确分离
- [  ] 如果是两块单输入声卡：`lavA` / `lavB` 两条文件都能独立录到清晰人声，且拍手尖峰在两条文件中都可见

### Step 5：Audio 预实验（第 2-3 周）

#### 5.0 音频分析软件栈怎么分工

不要把所有包都想成“录音软件”。它们所在的阶段完全不同：

| 工具 | 跑在哪 | 作用 | 你该怎么理解它 |
|------|--------|------|----------------|
| `arecord` | RPi | 录制 wav | 原始采集工具 |
| `sox` / `soxi` | RPi / 分析电脑 | 检查采样率、通道数、简单裁剪 | 快速质检工具 |
| `librosa` / `soundfile` | 分析电脑 | 频谱、能量、MFCC、读写音频 | 环境声分析主力 |
| `pyannote.audio` | 分析电脑 / GPU 主机 | 说话人分段、重叠检测、说话人计数 | 首选 baseline 是 diarization，不是高保真语音分离 |
| `VisualVoice` | GPU 主机 | 音视频联合分离 | 必须有同步视频、face tracking、GPU，属于高级可选项 |

建议你把音频侧分成两层任务：

1. **先完成 baseline**：频谱、能量、SNR、说话人分段
2. **再做高级分离**：只有在你已经有同步视频和 GPU 的前提下，再尝试 VisualVoice

#### 实验 5.1：环境声检测能力

在厨房/客厅环境中，制造以下 5 类声音，每类 20 次：

| 声音类别 | 具体动作 | 预期特征 |
|---------|---------|---------|
| 切菜声 | 刀切砧板 | 有节奏的脉冲 |
| 水流声 | 开关水龙头 | 持续宽带噪声 |
| 碗碟碰撞 | 放置碗碟 | 短促金属/陶瓷撞击 |
| 脚步声 | 正常行走 | 规律低频脉冲 |
| 门声 | 开关门 | 单次低频冲击 |

**执行步骤**：
1. 环境麦（RPi+ReSpeaker）录制，同时用手机录视频做对照
2. 每个事件前后静默 3 秒
3. 文件命名：`audio_env_{sound}_{trial}.wav`

**交付物**：
- [  ] 5 类声音的频谱图
- [  ] SNR 测量（信号段 vs 静默段）
- [  ] 不同距离（1m/2m/3m）的检测质量

#### 实验 5.2：双人语音分离质量

| 条件 | 说明 | 采集方式 |
|------|------|---------|
| V1 | A 说话，B 沉默 | 环境麦 + 个人麦 |
| V2 | B 说话，A 沉默 | 同上 |
| V3 | A、B 轮流说话 | 同上 |
| V4 | A、B 同时说话 | 同上 |
| V5 | A、B 边做动作边交谈（模拟做饭聊天） | 同上 |

每条件 5 次，每次 30 秒。说话内容：朗读预设文本 + 自由对话。

**执行步骤**：
1. 同时启动：环境麦（2ch）+ 个人麦（1 个 2ch 文件，或 `lavA` + `lavB` 两个 1ch 文件）
2. 拍手同步
3. 先用 `pyannote.audio` 做 diarization / VAD，确认“谁在什么时候说话”；只有当你有同步视频和 GPU 时，再用 VisualVoice 做音视频 separation
4. 用个人麦录音作为 ground truth 评估分离质量；如果你用的是两块单通道声卡，就分别把 `lavA.wav` 和 `lavB.wav` 当成两个人的参考轨

**交付物**：
- [  ] 个人麦 vs 环境麦+算法分离 的 SDR（信号失真比）对比
- [  ] V4（同时说话）条件下的分离效果
- [  ] 结论：是否必须用个人麦，还是环境麦+算法就够

#### 实验 5.3：CSI + Audio 共存测试

在 RPi-2 上**同时**运行 Nexmon CSI 采集和 ReSpeaker 录音：

| 检查项 | 方法 | 通过标准 |
|--------|------|---------|
| Audio 是否有 Wi-Fi 噪声 | 对比：仅录音 vs CSI+录音同时运行，比较频谱 | 噪声增加 < 3dB |
| CSI 是否有丢包 | 对比：仅 CSI vs CSI+录音同时运行，比较包数 | 丢包率 < 5% |
| CPU/内存压力 | 监控 top/htop | CPU < 80%, 内存 < 70% |

**交付物**：
- [  ] 共存 vs 独立运行的对比数据
- [  ] 结论：能否共用 RPi，还是必须分开

---

## 第四部分：时间同步方案

所有设备必须时间对齐，否则多模态数据无法配合。

### 同步架构

```
NTP 服务器（交换机连接的任一 RPi 或实验室电脑）
    ├── RPi-1 (CSI Tx)          <- NTP 同步
    ├── RPi-2 (CSI Rx + Audio)  <- NTP 同步
    ├── RPi-3 (CSI Rx + Audio)  <- NTP 同步
    └── RPi-4 (个人麦 Audio)    <- NTP 同步

精度目标：< 10ms（NTP 局域网内通常 < 1ms）
```

### 设置步骤

```bash
# 在每台 RPi 上
sudo apt install -y chrony
sudo systemctl enable chrony

# 选一台设备（推荐 RPi-1）作为 NTP 服务器
# 编辑 /etc/chrony/chrony.conf，加入：
# local stratum 10
# allow 10.0.50.0/24

# 其他 RPi 指向 RPi-1：
# server 10.0.50.11 iburst

# 重启 chrony
sudo systemctl restart chrony

# 验证同步状态
chronyc tracking
chronyc sources -v
```

你真正关心的不是“命令有没有跑完”，而是下面 2 个结果：

1. `chronyc tracking` 能看到参考源和较小的时钟偏移
2. 所有设备在拍手时刻附近都能在各自数据里看到明显峰值

### 物理同步标记

每次录制开始时：**拍手一次**。
- Audio：拍手产生尖锐脉冲，所有麦克风可检测
- CSI：拍手引起空间扰动，CSI 幅度出现突变
- 后处理时对齐拍手时刻即可

---

## 第五部分：代码端控制与离线分析

### 5.1 为什么建议你一定写控制脚本

如果每次实验都手打一长串命令，你很快会遇到 4 个问题：

1. 文件名不统一，后面没法批量处理
2. 忘记先停 `wpa_supplicant` 或忘记切固定信道
3. 音频和 CSI 录制起止时刻不一致
4. 试次很多以后，根本记不住哪台机器跑了哪条命令

所以推荐你建立一个最小控制仓库，把“启动采集”和“离线预览”固化成脚本。

### 5.2 建议的代码和数据目录

```text
pilot/
├── configs/
│   ├── devices.yaml
│   ├── router.yaml
│   └── experiment_plan.csv
├── scripts/
│   ├── start_tx.sh
│   ├── start_csi_rx.sh
│   ├── start_audio_env.sh
│   ├── start_audio_lav.sh
│   ├── stop_capture.sh
│   └── pull_session.sh
├── data/
│   ├── raw/
│   │   ├── csi/
│   │   └── audio/
│   └── processed/
├── metadata/
│   ├── sessions.csv
│   ├── clap_timestamps.csv
│   └── device_notes.md
├── analysis/
│   ├── parse_csi_preview.py
│   ├── plot_audio_preview.py
│   ├── diarize_audio.py
│   └── sync_modalities.py
└── report/
    └── pilot_report.md
```

### 5.3 每个脚本负责什么

| 脚本 | 跑在哪 | 负责什么 | 依赖 |
|------|--------|----------|------|
| `start_tx.sh` | RPi-1 | 连接固定 AP 并持续产生可控流量 | `ping` / `iperf3` |
| `start_csi_rx.sh` | RPi-2 / RPi-3 | 停 `wpa_supplicant`、配置 Nexmon、保存 pcap | `nexutil`、`tcpdump` |
| `start_audio_env.sh` | RPi-2 / RPi-3 | 录制 2 通道环境音频 | `arecord` |
| `start_audio_lav.sh` | RPi-4 | 录制 2 通道个人麦音频，或两块单通道声卡各录一条 1 通道个人麦音频 | `arecord` |
| `pull_session.sh` | 控制电脑 | 用 `rsync` 拉回整轮实验数据 | `rsync` |
| `parse_csi_preview.py` | 分析电脑 | 把 pcap 解码并画出快速预览图 | `nexcsi`、`numpy`、`matplotlib` |
| `plot_audio_preview.py` | 分析电脑 | 画频谱和能量曲线，做快速质检 | `librosa`、`matplotlib` |
| `diarize_audio.py` | 分析电脑 / GPU 主机 | 跑 `pyannote.audio`，输出说话人时间段 | `pyannote.audio`、`ffmpeg` |
| `sync_modalities.py` | 分析电脑 | 根据拍手峰值对齐 CSI 和音频 | `numpy`、`scipy` |

### 5.4 最小脚本模板

下面 3 个模板足够你搭起第一版控制层。

#### `start_csi_rx.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME=${1:?usage: start_csi_rx.sh <session_name> [chanspec] [outdir]}
CHANNEL=${2:-36/80}
OUTDIR=${3:-$HOME/pilot/data/raw/csi}

mkdir -p "$OUTDIR"
cd "$HOME/nexmon/patches/bcm43455c0/7_45_189/nexmon_csi"

sudo nmcli dev set wlan0 managed no || true
sudo pkill wpa_supplicant || true
sudo ifconfig wlan0 up

PARAMS=$(./utils/makecsiparams/makecsiparams -c "$CHANNEL" -C 1 -N 1)
sudo nexutil -Iwlan0 "-k$CHANNEL"
sudo nexutil -Iwlan0 -s500 -b -l34 -v"$PARAMS"
sudo nexutil -Iwlan0 -m1
nexutil -m

OUTFILE="$OUTDIR/${SESSION_NAME}.pcap"
sudo rm -f "$OUTFILE"
sudo tcpdump -ni wlan0 udp dst port 5500 -w "$OUTFILE"
```

#### `start_audio_env.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME=${1:?usage: start_audio_env.sh <session_name> <card> [duration]}
CARD=${2:?usage: start_audio_env.sh <session_name> <card> [duration]}
DURATION=${3:-30}
OUTDIR=${4:-$HOME/pilot/data/raw/audio/env}

mkdir -p "$OUTDIR"
arecord -D "plughw:${CARD},0" -c 6 -r 48000 -f S16_LE \
  -d "$DURATION" "$OUTDIR/${SESSION_NAME}.wav"
```

#### `parse_csi_preview.py`

```python
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from nexcsi import decoder

pcap_path = Path("test_csi.pcap")
samples = decoder("raspberrypi").read_pcap(pcap_path)
csi = decoder("raspberrypi").unpack(
    samples["csi"],
    zero_nulls=True,
    zero_pilots=True,
)

trace = np.abs(csi).mean(axis=1)

plt.figure(figsize=(10, 3))
plt.plot(trace)
plt.title(pcap_path.stem)
plt.xlabel("packet index")
plt.ylabel("mean amplitude")
plt.tight_layout()
plt.savefig("csi_preview.png", dpi=200)
```

### 5.5 一次完整实验的标准启动顺序

1. 确认 4 台 RPi 都能通过网线 SSH 登录
2. 检查 `chronyc tracking`，确保时间同步正常
3. 在 RPi-1 启动固定流量源
4. 在 RPi-2 / RPi-3 启动 CSI 采集脚本
5. 在 RPi-2 / RPi-3 / RPi-4 启动音频录制脚本
6. 口头报试次编号，然后拍手一次
7. 执行动作或语音任务
8. 停止采集，立即用 `rsync` 拉回文件
9. 先跑一遍 `parse_csi_preview.py` 和音频频谱预览，确认不是空文件，再开始下一轮

**原则**：每做完一轮试次，都要立刻做“快速预览”。不要攒到一天结束后才发现整批数据有问题。

---

## 第六部分：预实验时间线

| 周 | 日期 | 任务 | 交付物 |
|----|------|------|--------|
| **W1** | 4/7 - 4/13 | 采购到货 + 系统烧录 + Nexmon/ReSpeaker 驱动安装 | 4 台 RPi 就绪，CSI 和 Audio 各跑通 demo |
| **W2** | 4/14 - 4/20 | CSI 单人基线（实验 3.1）+ Audio 环境声测试（实验 5.1） | 单人 CSI 数据 + 环境声频谱 |
| **W3** | 4/21 - 4/27 | CSI 双人分离（实验 3.2）+ Audio 语音分离（实验 5.2）+ 穿墙（实验 3.3） | 双人数据 + 分离结果 |
| **W4** | 4/28 - 5/4 | CSI+Audio 共存测试（实验 5.3）+ 数据整理 + **撰写预实验报告** | **最终报告** |

---

## 第七部分：预实验报告模板

第 4 周结束时提交以下报告：

```
# CUHK-Y 预实验报告

## 1. 硬件验证结果
- Nexmon CSI：采样率 ___Hz，子载波 ___个，稳定性 ___
- ReSpeaker Audio：2通道正常？采样率稳定？
- ESP32 穿墙链路：可用？信号质量？
- CSI+Audio 共存：可行？需要分离？

## 2. CSI 实验结果
- 单人 5 类识别准确率：___%
- 双人分离可行性：[可分离 / 部分可分 / 不可分]
  - 具体证据：[附 PCA/ICA 结果图]
- 穿墙感知：[可检测 / 信号微弱 / 不可用]
  - 墙体材质：___，厚度：___cm

## 3. Audio 实验结果
- 环境声 5 类 SNR：___dB（1m/2m/3m）
- 双人语音分离 SDR：
  - 个人麦（ground truth）：___dB
  - 环境麦+pyannote：___dB
  - 环境麦+VisualVoice：___dB
- 同时说话分离质量：[良好 / 可接受 / 差]

## 4. 决策建议
- CSI 平台最终选择：[Nexmon / 需要切换到 PicoScenes]
- Audio 双人方案：[个人麦必须 / 环境麦+算法即可]
- RPi 共用方案：[可共用 / 需分离]
- 穿墙方案：[Nexmon 穿墙可用 / 仅用 ESP32 / 放弃穿墙]

## 5. 正式采集的硬件采购调整
- 基于预实验结果，正式采集需要增购/替换的设备

附录：原始数据、可视化图表、分类代码
```

---

## 附录 A：推荐目录与命名规范

建议你把“脚本、配置、原始数据、处理结果、元数据”分开管理。这样后面写批处理脚本和报告时不会乱。

```text
pilot/
├── configs/
│   ├── devices.yaml
│   ├── router.yaml
│   └── experiment_plan.csv
├── scripts/
│   ├── start_tx.sh
│   ├── start_csi_rx.sh
│   ├── start_audio_env.sh
│   ├── start_audio_lav.sh
│   ├── stop_capture.sh
│   └── pull_session.sh
├── data/
│   ├── raw/
│   │   ├── csi/
│   │   │   ├── single/
│   │   │   │   ├── csi_single_stand_01.pcap
│   │   │   │   ├── csi_single_walk_01.pcap
│   │   │   │   └── ...
│   │   │   ├── dual/
│   │   │   │   ├── csi_dual_D1_01.pcap
│   │   │   │   └── ...
│   │   │   └── wall/
│   │   │       ├── csi_wall_W1_01.pcap
│   │   │       └── ...
│   │   └── audio/
│   │       ├── env/
│   │       │   ├── audio_env_chopping_01.wav
│   │       │   └── ...
│   │       ├── speech/
│   │       │   ├── audio_speech_V1_env2ch_01.wav
│   │       │   ├── audio_speech_V1_lav2ch_01.wav
│   │       │   ├── audio_speech_V1_lavA_01.wav
│   │       │   ├── audio_speech_V1_lavB_01.wav
│   │       │   └── ...
│   │       └── coexist/
│   │           └── ...
│   └── processed/
│       ├── figures/
│       ├── features/
│       └── metrics/
├── metadata/
│   ├── sessions.csv
│   ├── clap_timestamps.csv
│   └── device_notes.md
├── analysis/
│   ├── parse_csi_preview.py
│   ├── plot_audio_preview.py
│   ├── diarize_audio.py
│   └── sync_modalities.py
└── report/
    └── pilot_report.md
```

命名规则建议固定为：

- CSI 单人：`csi_single_<action>_<trial>.pcap`
- CSI 双人：`csi_dual_<condition>_<trial>.pcap`
- CSI 穿墙：`csi_wall_<condition>_<trial>.pcap`
- 环境音频：`audio_env_<sound>_<trial>.wav`
- 双人语音环境麦：`audio_speech_<condition>_env2ch_<trial>.wav`
- 双人语音个人麦（双输入声卡）：`audio_speech_<condition>_lav2ch_<trial>.wav`
- 双人语音个人麦（两块单输入声卡）：`audio_speech_<condition>_lavA_<trial>.wav` 和 `audio_speech_<condition>_lavB_<trial>.wav`
- 共存测试：`coexist_<mode>_<trial>.{pcap,wav,log}`

## 附录 B：应急方案与高频故障排查

| 问题 | 典型原因 | 应急方案 |
|------|----------|---------|
| Nexmon 刷机失败 | 目录版本不对、系统过新、依赖不全 | 优先回到 Bullseye；确认走 `7_45_189`；必要时尝试官方 discussion 里的 `Makefile.rpi` 路线 |
| `nexutil` 编译失败或运行时报老 netlink 路线错误 | 没装 `libnl` 开发包，或者 `nexutil` 不是用 `USE_VENDOR_CMD=1` 编出来的 | 安装 `pkg-config`、`libnl-3-dev`、`libnl-genl-3-dev`；然后重编 `nexutil` 并执行 `sudo make install USE_VENDOR_CMD=1` |
| `makecsiparams` 不存在或 `PARAMS` 为空 | 工具没编出来，或者脚本继续往下执行了 | 先单独编 `utils/makecsiparams`；用 `echo "$PARAMS"` 确认非空后再执行 `nexutil -s500` |
| 汇编时报 `Parser ERROR ... jext COND_RX_IFS2, skip+` | `buildtools/b43-v3/assembler` 过旧，或 parser/scanner 没在本机重建 | 先安装 `flex` / `bison`，再重建 `buildtools/b43-v3/assembler` 后重试 |
| `make clean` 之后又报 `log/disass.log`、`obj`、`gen`、`log` 不存在 | 清理目标把中间目录一起删掉了 | 先 `mkdir -p obj gen log`，再重跑生成流程 |
| 启动 CSI 后 SSH 断开 | 你正在用 `wlan0` 管理机器 | 所有 RPi 改走网线管理；CSI 期间不要依赖无线 SSH |
| `tcpdump` 抓不到 5500 端口包 | 没有流量、信道不一致、`wpa_supplicant` 抢回控制 | 检查 RPi-1 是否持续发流量；检查 AP 是否固定在 `36/80`；先停 `wpa_supplicant` |
| 现场只有公共 Wi-Fi，连不上 5GHz 或信道不固定 | 场地 AP 只开放 2.4GHz，或者会自动切信道/带宽 | 临时 demo 可以按当前实际频点工作，例如 `2462 MHz = channel 11` 时让 Rx 改到 `11/20`；正式采集不要依赖公共 Wi-Fi，改用自带固定信道 AP/热点 |
| `make -f Makefile.rpi unmanage` 提示 `This device is not active` | NetworkManager 当时并没有接管 `wlan0` | 这通常不是致命故障，继续执行 `reload-full` 和后续配置即可 |
| `Operation not supported (-95)` 出现在设信道阶段 | 还在沿用 `iw dev wlan0 set channel ...` 的旧做法 | recent-kernel 下改用 `nexutil -k<chanspec>` 读写信道，例如 `-k1/20` 或 `-k36/80` |
| `monitor: 1` 但你仍不确定是否成功 | 只看单条报错，没有看抓包结果 | 对 recent-kernel 路线，`nexutil -m` 和 `tcpdump -ni wlan0 udp dst port 5500` 比 `iwconfig` / `mon0` 更可信 |
| 在 Rx 端误跑了 `ping` / `iperf` | 把发流量命令打到了只负责接收 CSI 的机器上 | 直接 `Ctrl+C` 停掉即可；这不会持久修改固件状态。停掉后重新执行 `nexutil -m` 和短时间 `tcpdump` 确认 Rx 仍在工作 |
| 第二次写同名 pcap 时 `Permission denied` | 旧文件是 root 创建的，`tcpdump` 降权后无法覆盖 | 每次使用新文件名，或者先 `sudo rm -f <old.pcap>` 再抓 |
| pcap 有文件但 `nexcsi` 解析异常 | 解码器选错、抓到的是空包、子载波全是无效值 | 使用 `decoder('raspberrypi')`；先看包数；绘图前 zero null/pilot subcarriers |
| ReSpeaker 驱动不兼容 | overlay 未安装、启动配置未生效，或系统版本过旧/过新 | 优先检查 `dtoverlay=respeaker-2mic-v2_0`、overlay 文件位置和 `dmesg`；必要时再评估系统版本 |
| `arecord` 通道数不对 | 录错声卡，或把单输入声卡当成双输入来录了 | 先用 `arecord -l` 找实际 card；双输入声卡用 `-c 2`，单输入声卡用 `-c 1`；再用 `soxi` 验证输出 |
| 没有双输入 USB 声卡 | 市面设备难买，或采购时没确认真双输入 | 改用 2 块单输入 ALSA 兼容 USB 声卡，分别录成 `lavA.wav` / `lavB.wav`，每轮实验保留拍手同步 |
| `pyannote.audio` 跑不起来 | 缺 `ffmpeg`、缺 Hugging Face token、Pi 性能不够 | 在分析电脑/GPU 主机上运行；安装 `ffmpeg`；提前获取 Hugging Face token |
| VisualVoice 很难直接复现 | 缺同步视频、嘴部 ROI、GPU 环境老旧 | 不要把它当第一阶段 baseline；先完成音频-only baseline，再决定是否上音视频分离 |
| 穿墙信号太弱 | 墙体损耗大、天线方向不佳、发包链路不稳定 | 调整天线和站位；补做 ESP32 辅助链路；如果仍不稳定，只保留室内场景 |
| CSI+Audio 共存干扰严重 | 同一台 Pi 资源不足或电磁干扰明显 | 先记录 CPU/内存和丢包率；若指标超阈值，拆分到不同 RPi |
| RPi4 缺货 | 采购延误 | 用 RPi5（先确认 Nexmon 兼容）或 Asus RT-AC86U 替代 CSI 节点 |
