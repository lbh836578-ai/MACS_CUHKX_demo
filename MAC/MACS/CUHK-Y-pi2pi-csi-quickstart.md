# CUHK-Y 双 Pi CSI 简易联通手册（含最小 Audio 扩展）

> 版本：v1.2
> 最近修订：2026-05-04
> 适用对象：已经完成 Nexmon recent-kernel 安装的人，只想最快搭通一条 `pi2 = Tx`、`pi3 = Rx` 的 CSI 链路，并在此基础上挂最小 Audio 采集

---

## 前置部分：新环境、无显示器、4 台 Pi 时先怎么开始

如果你现在是**换了一个新环境、手上有 4 台 Pi、电脑已经能接交换机、但没有那么多显示屏**，那你先不要急着往后翻 CSI 命令。先按这一节把**物理连接和 headless 起步**做对。

### A. 先统一你现在这 4 台 Pi 的角色

按你现在这套真实设备，建议你先物理贴标签，不要先纠结旧的抽象命名：

| 物理标签 | 角色 | 现在先接什么 |
|---------|------|--------------|
| `pi2` | CSI Tx | 电源 + `eth0` 网线 |
| `pi3` | 主 Rx + 环境麦 | 电源 + `eth0` 网线 + ReSpeaker HAT |
| `pi4` | 第二 Rx + 环境麦 | 电源 + `eth0` 网线 + ReSpeaker HAT |
| `pi5` | 个人麦节点 | 电源 + `eth0` 网线 + 2 块 USB 声卡 |

这份 quickstart 的后半部分仍然以**最小闭环**为主，所以默认先跑：

1. `pi2 = Tx`
2. `pi3 = 第一条 Rx + 环境麦`
3. `pi5 = 个人麦`

等这一条最小链路跑通后，再把 `pi3` 的 **Rx + 环境麦** 步骤复制到 `pi4`。也就是说：**先用 `pi2 + pi3 + pi5` 跑最小闭环，`pi4` 作为第二观测点第二阶段再并入。**

### B. 你现在到底需要接几个 HAT

按最新 4-Pi 同房间部署：

1. **ReSpeaker 2-Mics Pi HAT v2：2 块。**
2. **分别接到 `pi3` 和 `pi4` 的 40-pin GPIO 上。**
3. **`pi2` 不接任何 HAT。**
4. **`pi5` 也不接 GPIO HAT；它接的是 2 块 USB 声卡，不是 GPIO HAT。**

如果你现在只是想最快从零开机并验证一条最小链路，那你可以先只接：

1. `pi3` 上的 **1 块 ReSpeaker HAT**。
2. `pi5` 上的 **2 块 USB 声卡**。
3. 暂时先不要急着把第二块 ReSpeaker HAT 插到 `pi4` 上参与实验。

### C. 物理连接顺序

所有 HAT 和 USB 音频设备都建议在**断电状态**下连接。

#### C1. 电脑和交换机

1. 电脑接交换机。
2. 电脑继续用自己原来的 Wi-Fi 上网也可以，不冲突。
3. 交换机现在只负责管理网络，不负责 CSI 无线链路。

#### C2. `pi2` = CSI Tx

1. 插好 MicroSD 卡。
2. 接电源。
3. 用网线把 `eth0` 接到交换机。
4. **不要接 HAT。**
5. **不要接 USB 声卡。**

#### C3. `pi3` = 主 Rx + 环境麦

1. 断电状态下，把 **ReSpeaker 2-Mics Pi HAT v2** 对准 `pi3` 的 **40-pin GPIO** 插好。
2. 确认针脚没有错位，再固定铜柱。
3. 插好 MicroSD 卡。
4. 接电源。
5. 用网线把 `eth0` 接到交换机。
6. **不要再给 ReSpeaker 另外接 USB 线**，因为它是 GPIO HAT。

#### C4. `pi4` = 第二 Rx + 环境麦

如果你打算按正式 4-Pi 拓扑一次接好，就和 `pi3` 完全一样：

1. 断电状态下插第二块 **ReSpeaker 2-Mics Pi HAT v2** 到 `pi4` 的 **40-pin GPIO**。
2. 插好 MicroSD 卡。
3. 接电源。
4. 用网线把 `eth0` 接到交换机。

如果你现在只是想先最小 bring-up，这一台可以先只接：

1. MicroSD 卡。
2. 电源。
3. `eth0` 网线。

也就是说，**第二块 HAT 可以等第一条链路跑通后再装。**

#### C5. `pi5` = 个人麦节点

1. 插好 MicroSD 卡。
2. 把 **两块 USB 声卡** 插到 `pi5` 的 USB 口。
3. 两只领夹麦分别接到两块 USB 声卡上。
4. 固定好 `A 麦 -> 声卡 A`、`B 麦 -> 声卡 B`，不要中途换口。
5. 接电源。
6. 用网线把 `eth0` 接到交换机。
7. **这一台不接 GPIO HAT。**

#### C6. AP / 路由器

1. 给专用 AP 上电。
2. 它主要给 `pi2` 的 `wlan0` 发流量链路使用。
3. `pi3` / `pi4` 的 `wlan0` 后面只需要跟到同一信道做 CSI Rx，不要求像管理网络那样靠 Wi-Fi 登录。

### D. 没有显示屏时，第一次怎么登录

最稳的前提是：**你烧录系统时已经在 Raspberry Pi Imager 里开了 SSH、设了用户名密码、设了 hostname。**

如果这个前提满足，你第一次开机后通常可以直接从电脑这样连：

```bash
ssh pi@<hostname>.local
```

如果你现在的 hostname 就是 `pi2`、`pi3`、`pi4`、`pi5`，那最省事的例子就是：

```bash
ssh pi@pi2.local
ssh pi@pi3.local
ssh pi@pi4.local
ssh pi@pi5.local
```

如果你当前 hostname 还不是这些，也没关系。你至少应该先做到：

1. 电脑能通过交换机访问到 4 台 Pi。
2. 每台 Pi 都能 SSH 进去。
3. 不依赖 HDMI 显示器和 USB 键盘鼠标。

### E. 接好设备后，先做什么，不要一上来全跑

推荐按下面这个顺序：

1. **先只确认 4 台 Pi 都能 headless SSH 登录。**
2. **再只确认 `pi3` 上那块 ReSpeaker HAT 被系统识别。**
3. **再只确认 `pi5` 上两块 USB 声卡都被系统识别。**
4. **再只跑 `pi2 -> pi3` 这一条最小 CSI 链路。**
5. **最后才把 `pi4` 和第二块 ReSpeaker HAT 加进来。**

每台机器接好线、SSH 登录以后，第一批最小检查命令应该是：

在每台 Pi 上都先看：

```bash
hostname
ip -4 addr show dev eth0
timedatectl status
```

在 `pi3` 上额外看 ReSpeaker：

```bash
arecord -l
```

在 `pi5` 上额外看 USB 声卡：

```bash
arecord -l
```

如果你此时的目标只是“先从头把系统带起来”，那么到这一步的判断标准只有 3 条：

1. 4 台 Pi 都能 SSH。
2. `pi3` 的 ReSpeaker 至少能在 `arecord -l` 里出现。
3. `pi5` 的两块 USB 声卡至少能在 `arecord -l` 里出现。

只有这 3 条都满足，再往后做 CSI、录音和同步。

## 0. 先看你当前这套环境的结论

你现在给出的 `pi2` 联网状态是：

- SSID：`KFC-Free-Wifi`
- 频点：`2462 MHz`
- 实际信道：`11`
- 频段：`2.4 GHz`

这意味着：

1. 你现在**不能继续沿用**之前的 `36/80` 作为当前公共 Wi-Fi 的工作信道
2. 这条链路**可以先做 demo**，但**不适合正式采集**，因为公共 Wi-Fi 的信道、带宽、AP 负载和客户端隔离策略都不可控
3. 你现在最快的临时方案，是让 `pi3` 的 Rx 端跟着改到 `11/20`

一句话判断：

- **临时验证**：可以继续，用 `11/20`
- **正式实验**：不要依赖公共 Wi-Fi，改用自带固定信道 AP 或热点

---

## 1. 最推荐的两种用法

### 方案 A：公共 Wi-Fi 临时 demo

适合你现在这个场景：现场只有公共 Wi-Fi，`pi2` 已经连上 `2.4 GHz / channel 11`。

优点：

- 不用再额外拿路由器
- 现在就能验证 Rx/Tx 是否联通

缺点：

- 信道和带宽不可控
- AP 可能自动切换
- 不适合做正式数据采集和可复现实验

### 方案 B：自带固定信道网络

适合正式实验。

优先级：

1. 最优：固定 `5 GHz / 36/80` 的专用 AP
2. 备选：固定 `2.4 GHz / 1/20` 或 `11/20` 的专用 AP/热点

如果现场卡不到 5G，不要硬顶。**固定的 2.4G 比不可控的 5G 更有价值**。

---

## 2. 开始前的最小前提

默认你已经完成以下一次性工作：

- `nexutil` 已经用 `USE_VENDOR_CMD=1` 编译并安装
- `makecsiparams` 能正常输出 base64 参数
- `make -f Makefile.rpi install-firmware` 已跑过
- `pi2`、`pi3` 通过 `eth0` 或其他方式可管理，**不要依赖 `wlan0` 做管理 SSH**

如果上面有一条没满足，先回主文档处理，不要直接往下跑。

---

## 3. 方案 A：公共 Wi-Fi 下的最小联通步骤

这一节只做最短闭环：

- `pi2` 连公共 Wi-Fi，当 Tx 端制造流量
- `pi3` 不连网，只做 Rx 端抓 CSI UDP

### 3.1 在 pi2 上确认当前实际信道

```bash
iw dev wlan0 link
ip -4 addr show dev wlan0
ip route
```

你的当前输出已经说明：

- `freq: 2462.0` 对应 `channel 11`
- 这条公共 Wi-Fi 当前在 `2.4 GHz`

所以 `pi3` 应该跟到 `11/20`，不要继续用 `36/80`。

### 3.2 在 pi3 上配置 Rx

先进入 Nexmon 目录：

```bash
cd ~/nexmon/patches/bcm43455c0/7_45_189/nexmon_csi
```

然后执行下面这组：

```bash
CHANSPEC=11/20

sudo nmcli dev set wlan0 managed no || true
sudo pkill wpa_supplicant || true
sudo ifconfig wlan0 up

PARAMS=$(./utils/makecsiparams/makecsiparams -c "$CHANSPEC" -C 1 -N 1)
echo "$PARAMS"

sudo nexutil -Iwlan0 "-k$CHANSPEC"
nexutil -Iwlan0 -k

sudo nexutil -Iwlan0 -s500 -b -l34 -v"$PARAMS"
sudo nexutil -Iwlan0 -m1
nexutil -m

sudo rm -f /tmp/csi-public-demo.pcap
sudo tcpdump -ni wlan0 udp dst port 5500 -w /tmp/csi-public-demo.pcap
```

如果 `makecsiparams -c 11/20` 或 `nexutil -k11/20` 被拒绝，再退一步试：

```bash
./utils/makecsiparams/makecsiparams -c 11 -C 1 -N 1
sudo nexutil -Iwlan0 -k11
```

### 3.3 在 pi2 上制造流量

先取 `wlan0` 自己的默认网关，不要误拿 `eth0` 的网关：

```bash
ip route show default dev wlan0
GW=$(ip route show default dev wlan0 | awk 'NR==1 {print $3}')
echo "$GW"
```

如果它输出了一个网关 IP，例如 `10.25.x.x`，就用它发持续 ping：

```bash
ping -I wlan0 -i 0.02 "$GW"
```

> 你的当前机器上，`eth0` 的默认网关是 `192.168.2.1`，`wlan0` 的默认网关才是 `10.25.5.99`。前者不能拿来配合 `-I wlan0` 使用，所以你前面打 `ping -I wlan0 -i 0.02 192.168.2.1` 必然 100% 丢包。
>
> 对 CSI 来说，`pi2` 的任务是**发帧**，不是“自己收到正常 ping 回复”。如果公共 Wi-Fi 屏蔽了 ICMP 回复，但 `pi3` 仍然持续看到 `udp dst port 5500`，这条 demo 链路依然算是工作的。

如果公共 Wi-Fi 禁止 ping 网关，再试公网地址：

```bash
ping -I wlan0 -i 0.02 1.1.1.1
```

如果你已经有 `iperf3` 服务器，也可以替换成：

```bash
iperf3 -u -c <SERVER_IP> -b 20M -l 1470 -t 600
```

> **注意**：发流量命令只在 `pi2` 上执行，不要再打到 `pi3` 上。

### 3.4 在 pi3 上做在线验证

先看 monitor 状态：

```bash
nexutil -m
```

再做 20 个包的快速验证：

```bash
sudo tcpdump -ni wlan0 udp dst port 5500 -c 20
```

如果你已经在写 pcap，另开一个终端读头 10 个包：

```bash
sudo tcpdump -nn -r /tmp/csi-public-demo.pcap -c 10
```

你理想中应该看到这种头：

```text
IP 10.10.10.10.5500 > 255.255.255.255.5500: UDP, length 1042
```

只要这个头稳定出现，就说明 Rx 通路已经在工作。

---

## 4. 方案 B：正式实验推荐步骤

如果你要可复现，不要继续依赖公共 Wi-Fi。改成下面任一条：

### 路线 B1：专用 5GHz AP

- AP 固定到 `36/80`
- `pi2` 连这个 AP
- `pi3` 设成 `36/80`
- `pi2` 持续 `ping` AP 网关或跑 `iperf3`

`pi3` 的 Rx 命令只需把 `11/20` 全部改回 `36/80`：

```bash
CHANSPEC=36/80
PARAMS=$(./utils/makecsiparams/makecsiparams -c "$CHANSPEC" -C 1 -N 1)
sudo nexutil -Iwlan0 "-k$CHANSPEC"
sudo nexutil -Iwlan0 -s500 -b -l34 -v"$PARAMS"
sudo nexutil -Iwlan0 -m1
sudo tcpdump -ni wlan0 udp dst port 5500 -w /tmp/csi-5g-demo.pcap
```

### 路线 B2：专用 2.4GHz AP 或热点

如果就是卡不到 5GHz，也不要纠结。直接选一个固定 `2.4 GHz / 1/20` 或 `11/20` 的网络即可。

核心原则只有一条：

- **Tx 所在网络的实际信道是多少，Rx 就跟到同一 chanspec**

### 路线 B3：在 quickstart 拓扑上挂最小 Audio

这一节回答的是下面这个实际场景：

- `pi2`：CSI Tx
- `pi3`：CSI Rx + 环境麦
- `pi5`：个人麦节点

这里先说清一个命名问题：**`pi5` 只是你的主机名，不代表它是 Raspberry Pi 5。** 你现在这台 `pi5` 的实际型号仍然是 **Raspberry Pi 4B**，在这份 quickstart 里它继续作为个人麦节点来用。

按你现在手上的设备，这一节后面统一按下面这套硬件写，不再展开 6-Mic 分支：

- `pi2`：CSI Tx 节点
- `pi3`：CSI Rx + ReSpeaker 2-Mics Pi HAT v2 环境麦节点
- `pi5`：主机名为 `pi5` 的 Raspberry Pi 4B + USB 声卡 + 2 个领夹麦

这时最稳、最省事的角色分配应该是：

| 节点 | 实际角色 | 挂什么设备 | 为什么这样分 |
|------|----------|------------|--------------|
| `pi2` | CSI Tx | `eth0` 管理网线 + 自带 `wlan0` | `eth0` 负责 SSH / rsync / NTP，`wlan0` 专门负责连 AP 发流量，保持链路干净，不叠加音频任务 |
| `pi3` | CSI Rx + 环境音频 | `eth0` 管理网线 + 自带 `wlan0` + ReSpeaker 2-Mics Pi HAT v2（GPIO HAT，物理上双麦；当前 quickstart 先按单声道 smoke test） | `eth0` 负责管理，`wlan0` 负责 CSI Rx，ReSpeaker 负责环境音频；这是你最需要验证的“CSI + 环境音频同机共存”节点 |
| `pi5` | 个人麦节点 | 主机名 `pi5` 的 Raspberry Pi 4B + `eth0` 管理网线 + USB 声卡 + 2 个领夹麦 | 管理链路走 `eth0`，音频链路走 USB 声卡，作为双人语音的近端 ground truth，后面做对照最方便 |

这一套里，**CSI 仍然只有一条主链路：`pi2 -> pi3`**。这里要特别注意：`pi2`、`pi3`、`pi5` 都建议同时接交换机，用 `eth0` 做管理网络；表格里提到的 `wlan0` 说的是 **CSI 用的无线链路**，不是说这些机器不接网线。Audio 是挂在这条主链路旁边的，不要把音频再硬理解成 Tx / Rx。

#### 4.3.1 先建立正确理解

在这套最小系统里：

1. `pi2` 不录音，只负责制造稳定 Wi-Fi 帧。
2. `pi3` 一边抓 CSI，一边录环境声。
3. `pi5` 单独录两个人的领夹麦，给后面做对齐和 ground truth。

你可以把它理解成：

- `pi2 -> pi3` 提供 **无线运动感知主数据**
- `pi3` 的 ReSpeaker 提供 **房间里的环境声音主数据**
- `pi5` 的领夹麦提供 **人的近端说话参考数据**

如果你当前还没有把 `pi5` 这条个人麦链路准备好，也没关系。**最小闭环可以先只做 `pi3` 的环境麦。** 但如果你后面想认真比较“环境麦能不能替代个人麦”，那 `pi5` 这条链路最好尽早加上。

#### 4.3.2 你应该怎么组装硬件

先组 `pi3` 这一台环境麦节点。

**`pi3 + ReSpeaker 2-Mics Pi HAT v2` 的组装方式：**

1. 关闭 `pi3` 电源。
2. 把 ReSpeaker 2-Mics Pi HAT v2 对准 `pi3` 的 40-pin GPIO。
3. 确认 40-pin 完整对齐后压紧，不要错位插针。
4. 用铜柱把 HAT 固定住，不要让板子悬空。
5. `pi3` 继续接电源和 `eth0` 网线。
6. `wlan0` 继续留给 CSI，不需要为 ReSpeaker 另外接 USB 线。

> 你现在这块 ReSpeaker 走 GPIO HAT 安装方式，不占 USB；但按你当前这台 `pi3` 的排障状态，这份 quickstart 后面先统一按 **`单声道 / 48 kHz` smoke test** 写，等底层 codec / device tree 问题修完后再恢复 2 通道验收。

这台机器的物理状态应该是：

- `eth0`：管理 SSH / rsync / NTP
- `wlan0`：CSI Rx
- GPIO HAT：环境音频输入

然后组 `pi5` 这一台个人麦节点。

**`pi5 + USB 声卡 + 2 个领夹麦` 的组装方式：**

1. 关闭 `pi5` 电源。
2. 把 USB 声卡插到 `pi5` 的 USB 口。
3. 把两只领夹麦分别接到 USB 声卡的两个输入通道。
4. 给两个参与者各自佩戴一只领夹麦。
5. `pi5` 同样接电源和 `eth0` 网线。

你要特别确认 2 件事：

1. 这块 USB 声卡真的是**双输入双通道**，不是“一个立体声口分线出来看起来像双麦”。
2. 领夹麦接进去后，录到的左右声道确实是分开的，不是两个人混到同一条声道里。

领夹麦推荐的佩戴方式：

1. 麦头夹在胸口偏上，离嘴大约 `15 - 20 cm`。
2. 左右两个人固定对应同一通道，中途不要换。
3. 线尽量沿衣服内侧或背后走，减少摩擦噪声。
4. 如果现场有风扇或空调，尽量给领夹麦加海绵套。

### 4.3.3 ReSpeaker 2-Mics Pi HAT v2 的驱动和最小录音验证

你当前这块 ReSpeaker 是 **2-Mics Pi HAT v2**。在较新的 Raspberry Pi OS 上，优先走 Seeed 官方新的 `dtoverlay` 路线，不要再默认跑旧的 `seeed-voicecard/install_arm64.sh`。

```bash
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
```

重启回来以后：

```bash
arecord -l
```

你要先确认系统已经识别到 ReSpeaker 声卡。`arecord -l` 里通常会看到 `seeed2micvoicec` 一类名字。**如果 `arecord -l` 仍然是空的，就说明 overlay 还没挂成功，这时不要继续往下跑录音命令。**

另外要注意两件事：

1. `<ReSpeaker_CARD>` 只是占位符，不能原样照抄；你必须换成 `arecord -l` 里看到的实际 card 编号或名称。
2. 按你当前这台 `pi3` 的实际排障状态，这里的最小验证先固定用 `-c 1`，把它当成 **单声道 smoke test**；不要在底层问题没修完前继续把 2 通道当成门槛。

最小验证应该写成：

```bash
arecord -D plughw:<ReSpeaker_CARD>,0 -c 1 -r 48000 -f S16_LE -d 5 test_1ch.wav
soxi test_1ch.wav
```

正确结果至少要满足：

- `Channels: 1`
- `Sample Rate: 48000`
- `Encoding: Signed Integer PCM`

这一条现在只是在验证：**ReSpeaker 这条链路能不能先稳定录出一条单声道 wav**。它不代表最终正式采集就只能单声道。

如果卡已经出来了，但录音很小或者像静音，先运行 `alsamixer`，按 `F6` 选中 ReSpeaker，再看 `Capture` 有没有被静音或音量太低。

再在 `pi5` 上验证 USB 声卡和领夹麦：

```bash
sudo apt install -y alsa-utils sox
arecord -l
```

确认 USB 声卡被识别后，做 5 秒测试：

```bash
arecord -D plughw:<USB_CARD>,0 -c 2 -r 48000 -f S16_LE -d 5 test_lav.wav
soxi test_lav.wav
```

然后让两个人分别说一句话，检查左右声道是不是独立的。

如果你已经把 `pilot/` 目录分发到树莓派上，也可以直接使用你现在仓库里的脚本：

在 `pi3` 上：

```bash
~/pilot/scripts/start_audio_env.sh --session audio_env_test --card <ReSpeaker_CARD> --channels 1 --duration 5
```

在 `pi5` 上：

```bash
~/pilot/scripts/start_audio_lav.sh --session audio_lav_test --card <USB_CARD> --duration 5
```

#### 4.3.4 环境麦到底放哪里

这是 Audio 部分最容易摆错的地方。

**结论先说：ReSpeaker 不要贴墙角，不要贴桌角，不要贴着路由器、电源排插和风扇。**

对于大多数室内实验，`pi3 + ReSpeaker` 的推荐摆位是：

1. 放在主要活动区旁边，而不是最边缘。
2. 离主要说话人或动作区 `1 - 2 m`。
3. 高度大约 `1.2 - 1.6 m`。
4. 尽量让麦阵列和主要活动区之间没有大件遮挡。

一个很实用的原则是：

- **环境麦不是越近越好，而是要既能稳定录到人声和事件声，又不被单个声源压爆。**

如果你做的是双人对话或双人动作，最推荐两种摆法：

1. 放在两人中间稍微偏前的位置。
2. 放在两人前方 `1 - 1.5 m` 的位置，对着活动区。

如果你做的是厨房 / 客厅环境声：

1. 麦阵列放在操作区外缘。
2. 先从距离主要声源 `1 m` 的位置测试。
3. 后续再补 `2 m`、`3 m` 的对照采样。
4. 不要把麦直接摆在砧板旁边，不然切菜声会把其他声源全部淹掉。

#### 4.3.5 同房间版本怎么放

如果你当前只是做**同一房间内**的 quickstart 扩展，可以直接按下面摆：

```text
房间 A（同房间版本）

    [墙边 / 角落]                         [对角 / 侧前方]
    pi2 (CSI Tx)  --------------------->  pi3 (CSI Rx + ReSpeaker)

                                 [参与者 A]    [参与者 B]
                                         |              |
                                         +------活动区---+

    [桌边 / 墙边]
    pi5 (USB声卡 + 2个领夹麦)
```

对应的摆位逻辑是：

1. `pi2` 靠墙边或角落，专心发包。
2. 两位参与者在房间中部活动或说话。
3. `pi3` 放在活动区前方或对角，既看 CSI，又录环境音。
4. `pi5` 放桌边即可，因为它只负责领夹麦，不依赖空间位置。

#### 4.3.7 采集时的标准启动顺序

在这套 `pi2 + pi3 + pi5` 的最小系统里，推荐按这个顺序启动：

1. 确认 `pi3` 上 ReSpeaker 能先稳定录到单声道。
2. 确认 `pi5` 上 USB 声卡能正常录到 2 通道。
3. 在 `pi2` 上启动 CSI 发流量。
4. 在 `pi3` 上启动 CSI Rx。
5. 在 `pi3` 上启动环境麦录音。
6. 在 `pi5` 上启动个人麦录音。
7. 所有人就位后拍手一次。
8. 开始动作或说话任务。

最小命令顺序可以写成：

在 `pi2`：

```bash
ping -I wlan0 -i 0.02 <GW_OR_AP_IP>
```

在 `pi3`：

```bash
cd ~/nexmon/patches/bcm43455c0/7_45_189/nexmon_csi
CHANSPEC=11/20   # 或 36/80，取决于 Tx 当前网络
PARAMS=$(./utils/makecsiparams/makecsiparams -c "$CHANSPEC" -C 1 -N 1)

sudo nmcli dev set wlan0 managed no || true
sudo pkill wpa_supplicant || true
sudo ifconfig wlan0 up
sudo nexutil -Iwlan0 "-k$CHANSPEC"
sudo nexutil -Iwlan0 -s500 -b -l34 -v"$PARAMS"
sudo nexutil -Iwlan0 -m1

sudo tcpdump -ni wlan0 udp dst port 5500 -w /tmp/csi-audio-demo.pcap
```

另开一个 `pi3` 终端录环境音：

```bash
arecord -D plughw:<ReSpeaker_CARD>,0 -c 1 -r 48000 -f S16_LE -d 30 /tmp/audio_env_demo_1ch.wav
```

在 `pi5`：

```bash
arecord -D plughw:<USB_CARD>,0 -c 2 -r 48000 -f S16_LE -d 30 /tmp/audio_lav_demo.wav
```

如果你已经把 `pilot/` 脚本分发到各机器上，更推荐用：

在 `pi3`：

```bash
~/pilot/scripts/start_csi_rx.sh --session demo01 --channel 11/20
~/pilot/scripts/start_audio_env.sh --session demo01 --card <ReSpeaker_CARD> --channels 1 --duration 30
```

在 `pi5`：

```bash
~/pilot/scripts/start_audio_lav.sh --session demo01 --card <USB_CARD> --duration 30
```

#### 4.3.8 这一节的最短验收标准

你至少要同时满足下面 5 条，才算这套最小 Audio 扩展是真的跑起来了：

1. `pi3` 的 ReSpeaker 至少能稳定录出 `单声道 / 48 kHz` 的 wav。
2. `pi5` 的 USB 声卡能录出 `2 通道 / 48 kHz` 的 wav。
3. `pi2 -> pi3` 的 CSI 链路仍然保持 `monitor: 1` 且能抓到 UDP 5500。
4. 拍手后，`pi3` 的环境音和 `pi5` 的个人麦里都能看到明显尖峰。
5. 三个节点同时运行 `30 s` 时，没有谁因为资源占用直接挂掉。

#### 4.3.9 什么时候不要这么配

下面几种情况，不建议继续沿用这套最小布置：

1. `pi3` 在跑 CSI 时 CPU 已经很高，环境音录制一开就开始丢包。
2. 你需要高质量双人语音分离评估，但 `pi5` 上的 USB 声卡其实不是双独立输入。
3. 你当前只有公共 Wi-Fi，CSI 本身还没稳定，这时先别把 Audio 一起上来增加变量。

最务实的策略始终是：

- **先把 `pi2 -> pi3` 的 CSI 跑稳，再挂 `pi3` 的环境麦，最后才加 `pi5` 的个人麦。**

---

## 5. 最小验证 demo 程序

**运行位置优先级**：

1. 最方便：直接在 `pi3` 上运行，因为 pcap 默认保存在 `pi3:/tmp/csi-public-demo.pcap`
2. 更适合分析：把 pcap 拷到电脑后，在控制电脑上运行，但要把代码里的 `pcap_path` 改成复制后的本地路径
3. 不建议在 `pi2` 上运行，因为默认 pcap 不在 `pi2` 上

**Bookworm / Trixie 提醒**：不要在 `pi3` 上直接执行系统级的 `python3 -m pip install ...`。Debian 现在默认启用了 PEP 668，会报 `externally-managed-environment`。正确做法是新建一个虚拟环境。

**Python 3.13 额外提醒**：如果你的 `pi3` 当前是 Python 3.13，`pip install nexcsi numpy` 还会遇到第二层问题。`nexcsi 0.5.2` 把 `numpy` 限制在 `<2.0`，而 Python 3.13 上通常没有适合 `aarch64` 的 `numpy 1.26.x` 预编译 wheel，于是 `pip` 会回退到源码包 `numpy-1.26.4.tar.gz`，然后在树莓派上慢速编译。停在 `Preparing metadata`、`Getting requirements to build wheel` 很久，通常就是这个原因，不是网络卡死。

下面这个 Python 程序只做一件事：

- 读取 pcap
- 解码成 CSI
- 打印包数、形状、平均幅度
- 输出前 10 个包的平均幅度

保存为 `quick_check_csi.py` 后运行。



```python
from pathlib import Path

import numpy as np
from nexcsi import decoder

pcap_path = Path('/tmp/csi-public-demo.pcap')

samples = decoder('raspberrypi').read_pcap(pcap_path)
csi = decoder('raspberrypi').unpack(
    samples['csi'],
    zero_nulls=True,
    zero_pilots=True,
)

trace = np.abs(csi).mean(axis=1)

print('packets =', len(samples))
print('csi shape =', csi.shape)
print('mean amplitude =', float(np.abs(csi).mean()))
print('first 10 packet amplitudes =', trace[:10].tolist())
```

运行方式：

```bash
sudo apt install -y python3-venv
python3 -m venv ~/venvs/csi-demo
source ~/venvs/csi-demo/bin/activate
pip install --upgrade pip
pip install nexcsi numpy
python quick_check_csi.py
```

如果 `python3 -m venv` 提示缺模块，再补：

```bash
sudo apt install -y python3-full python3-venv
```

如果你当前看到 `numpy-1.26.4.tar.gz` 并且卡在 `Preparing metadata` 很久，直接切下面三种更快的做法，不要在 Pi 上硬等源码编译：

### 更快做法 A：直接在控制电脑上跑 demo

这是最稳的办法。

```bash
scp pi@<PI3_IP>:/tmp/csi-public-demo.pcap .
```

然后在控制电脑上用 Python 3.11 / 3.12 的虚拟环境安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install nexcsi numpy
python quick_check_csi.py
```

### 更快做法 B：如果 pi3 上有 Python 3.11 / 3.12，就用旧解释器建 venv

```bash
python3.11 -m venv ~/venvs/csi311
source ~/venvs/csi311/bin/activate
pip install --upgrade pip
pip install nexcsi numpy
python quick_check_csi.py
```

如果你的系统没有 `python3.11`，这条就跳过。

### 更快做法 C：只在你接受风险时用

`nexcsi` 本身是纯 Python 包，源码里看不出明显依赖旧版 NumPy 已删除 API。一个务实但非官方保证的做法是：

```bash
source ~/venvs/csi-demo/bin/activate
pip install numpy==2.4.4
pip install nexcsi==0.5.2 --no-deps
python quick_check_csi.py
```

这条的含义是：跳过 `nexcsi` 对 `numpy<2` 的旧版本约束，直接配合新 wheel 跑。通常会比在 Pi 上编译 `numpy 1.26` 快得多，但它不是上游正式声明支持的组合。

如果你是在控制电脑上运行，就先把文件拉回来，例如：

```bash
scp pi@<PI3_IP>:/tmp/csi-public-demo.pcap .
```

然后把脚本里的：

```python
pcap_path = Path('/tmp/csi-public-demo.pcap')
```

改成：

```python
pcap_path = Path('csi-public-demo.pcap')
```

如果你要快速画图，用下面这个版本：
```
touch quick_check_csi.py
```
```
nano quick_check_csi.py
```

```python
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from nexcsi import decoder

pcap_path = Path('/tmp/csi-public-demo.pcap')

samples = decoder('raspberrypi').read_pcap(pcap_path)
csi = decoder('raspberrypi').unpack(
    samples['csi'],
    zero_nulls=True,
    zero_pilots=True,
)

trace = np.abs(csi).mean(axis=1)

plt.figure(figsize=(10, 3))
plt.plot(trace)
plt.title('CSI quick preview')
plt.xlabel('packet index')
plt.ylabel('mean amplitude')
plt.tight_layout()
plt.savefig('csi_quick_preview.png', dpi=200)
print('saved csi_quick_preview.png')
```

如果你要跑这个画图版本，把虚拟环境里的依赖补成：

```bash
source ~/venvs/csi-demo/bin/activate
pip install nexcsi numpy matplotlib
python quick_check_csi.py
```

---

## 6. 最短验收标准

只看下面 4 条就够了：

1. `nexutil -m` 输出 `monitor: 1`
2. `nexutil -Iwlan0 -k` 输出的 chanspec 和 Tx 实际信道一致
3. `sudo tcpdump -ni wlan0 udp dst port 5500 -c 20` 能持续抓到包
4. `sudo tcpdump -nn -r <pcap> -c 10` 能看到 `10.10.10.10:5500 -> 255.255.255.255:5500`

只要这 4 条满足，就说明你的两台 Pi CSI 链路已经跑通。

---

## 7. 高频错误和最短处理

### 7.1 还在看到 `36/80`

说明 Rx 还没切到公共 Wi-Fi 的实际信道。现在这个场景应该先改成：

```bash
sudo nexutil -Iwlan0 -k11/20
```

### 7.2 `tcpdump: /tmp/csi.pcap: No such file or directory`

不是 CSI 故障，只是你读错了文件名。先 `ls /tmp/*.pcap` 找实际文件。

### 7.3 第二次抓同名 pcap 报 `Permission denied`

先删旧文件：

```bash
sudo rm -f /tmp/csi-public-demo.pcap
```

或者直接换新文件名。

### 7.4 把 `ping` 误打到了 pi3

直接 `Ctrl+C` 停掉即可。它不会永久改坏固件状态。停掉后重新检查：

```bash
nexutil -m
sudo tcpdump -ni wlan0 udp dst port 5500 -c 20
```

### 7.5 公共 Wi-Fi 根本不稳定

不要继续在它上面做正式实验。直接换成自带 AP/热点。

### 7.6 `pi2` 一直 0 received，是不是 Tx 失败了

不一定。

先分开看：

1. 如果你打的是 `ping -I wlan0 ...`，但目标其实是 `eth0` 那张网卡的网关，例如 `192.168.2.1`，那一定会失败
2. 如果目标是 `wlan0` 的网关或公网地址，但公共 Wi-Fi 不回 ICMP，也可能还是 `0 received`
3. 只要 `pi3` 继续能抓到 `udp dst port 5500`，对当前临时 demo 来说，`pi2` 这边没有 ping 回复并不等于 CSI 没工作

### 7.7 `python3 -m pip install ...` 报 `externally-managed-environment`

这是 Debian Bookworm / Trixie 的正常行为，不是你的 Pi 坏了。

最短处理：

```bash
sudo apt install -y python3-venv
python3 -m venv ~/venvs/csi-demo
source ~/venvs/csi-demo/bin/activate
pip install nexcsi numpy
```

不要默认用 `--break-system-packages` 去污染系统 Python；只有在你明确接受风险时才这么做。

### 7.8 虚拟环境里 `pip install` 卡在 `Preparing metadata`

这通常不是单纯的网络问题，而是下面这条链式反应：

1. 你的解释器是 Python 3.13
2. `nexcsi` 依赖 `numpy<2.0`
3. `numpy<2.0` 在 `cp313 + aarch64` 上往往没有现成 wheel
4. `pip` 退回源码包 `numpy-1.26.4.tar.gz`
5. 树莓派开始本地编译，所以会非常慢，甚至失败

最短处理顺序：

1. 优先改到控制电脑上跑
2. 或改用 Python 3.11 / 3.12 venv
3. 最后才考虑 `numpy==2.4.4` + `nexcsi --no-deps` 这种务实绕过法

### 7.9 `arecord -l` 看不到 ReSpeaker

对你现在这块 **ReSpeaker 2-Mics Pi HAT v2**，先不要再回去跑旧的 `install_arm64.sh`。优先检查这几件事：

1. HAT 是否插紧、是否错位。
2. 启动配置里有没有 `dtoverlay=respeaker-2mic-v2_0`。
3. overlay 文件是否真的拷到了 `/boot/firmware/overlays` 或 `/boot/overlays`。
4. 重启后内核日志里有没有 `seeed`、`tlv320`、`aic3`、`i2s` 相关信息。

最短动作：

```bash
CONFIG=/boot/config.txt
[ -f /boot/firmware/config.txt ] && CONFIG=/boot/firmware/config.txt

grep -n 'respeaker-2mic-v2_0' "$CONFIG"
arecord -l
dmesg | grep -Ei 'seeed|tlv320|aic3|i2s|snd'
```

如果你已经能在 `arecord -l` 里看到 ReSpeaker，但一执行：

```bash
arecord -D plughw:<ReSpeaker_CARD>,0 -c 1 -r 48000 -f S16_LE -d 5 test_1ch.wav
```

就只生成一个 `44 bytes` 的空 wav 头，并报：

```text
arecord: pcm_read:2272: read error: Input/output error
```

这通常不是录音参数写错，而是 **ALSA 已经打开了设备，但采集流一启动就被内核/驱动打断了**。对你现在这块 2-Mics Pi HAT v2，最常见的原因有 3 个：

1. 之前跑过旧的 `seeed-voicecard/install_arm64.sh`，启动配置里残留了旧 overlay，和新的 `respeaker-2mic-v2_0` 冲突。
2. `card` 号用错了，或者重启后声卡编号变了。
3. HAT 虽然被识别成卡了，但 `i2s` / `i2c` / codec 没真正稳定挂起来。

优先按这个最小影响顺序处理：

```bash
CONFIG=/boot/config.txt
[ -f /boot/firmware/config.txt ] && CONFIG=/boot/firmware/config.txt

grep -nE 'seeed|respeaker|voicecard|i2s-mmap|googlevoicehat' "$CONFIG"
```

如果你看到了旧的 `seeed-2mic-voicecard`、`i2s-mmap`、`googlevoicehat-soundcard` 一类条目，先把它们注释掉，只保留：

- `dtoverlay=respeaker-2mic-v2_0`
- `dtparam=i2c_arm=on`
- `dtparam=i2s=on`

然后重启，再重新确认实际 card 编号：

```bash
arecord -l
cat /proc/asound/cards
```

再用当前这次 `arecord -l` 里看到的实际 card 去测，不要死用旧的 `3`：

```bash
arecord -v -D hw:<ReSpeaker_CARD>,0 -c 1 -r 48000 -f S16_LE -d 3 /tmp/test_1ch.wav
```

如果还是报同样的 `Input/output error`，马上补看这两项：

```bash
sudo i2cdetect -y 1
dmesg | grep -Ei 'seeed|tlv320|aic3|i2s|snd'
```

这时候最有价值的不是 `soxi`，而是内核日志里有没有 codec / I2S 初始化失败信息。

如果你看到的是这一组组合错误：

- `tlv320aic3x ... supply IOVDD/DVDD/AVDD/DRVDD not found`
- `Invalid supply voltage(s) AVDD: -22, DVDD: -22`
- `bcm2835-i2s ... I2S SYNC error`
- 后面再跟一串 `ASoC ... -5 / -121`

那就不要再把重点放在 `arecord` 参数、card 编号或者 `plughw` / `hw` 的区别上了。这个组合基本说明：

1. overlay 已经把 codec 节点挂出来了，所以 ALSA 卡能看见。
2. 但当前这份 `respeaker-2mic-v2_0` 的设备树描述，对你这套内核/固件组合来说还不完整。
3. 问题已经下沉到 **device tree / codec supply / I2S 时钟主从** 这一层，而不是用户态录音命令本身。

这时最稳妥的下一步是：

1. 先导出运行中的 live device tree，确认 codec 节点里是否真的缺少 supply 属性。
2. 只有在确认板上电源轨定义之后，再考虑自定义 overlay 修补。
3. 不要直接把 `DVDD` 之类的 supply 随手改成 `3.3V`，否则可能从“缺属性”变成“供电值写错”。

按你这次已经贴出来的实际输出，现阶段还可以进一步确认 3 件事：

1. 你当前内核是 `6.12.75+rpt-rpi-v8`，不是旧版 Bullseye 内核。
2. 运行中的 live device tree 里，`tlv320aic3104@18` 和 `simple-audio-card` 都已经存在，`bitclock-master` / `frame-master` 以及固定 `mclk` 也都挂上了。
3. 但无论是 live device tree 还是 `/boot/overlays/respeaker-2mic-v2_0.dtbo` 的反编译结果，都没有看到 `iovdd-supply`、`dvdd-supply`、`avdd-supply`、`drvdd-supply` 这几项属性。

这意味着当前问题已经不该再沿着“card 号不对”或者“录音命令参数不对”这条路排了。更像是 **Seeed 这份 v2 overlay 在你当前内核上，对 tlv320aic3104 的供电描述不完整**，于是卡能枚举出来，但流一启动就掉进 codec / I2S 初始化失败。

### 7.10 当前先按单声道测试

按你现在这台 `pi3` 的实际情况，quickstart 先把 ReSpeaker 的最小验证降成 **单声道 / 48 kHz smoke test**。也就是说，在底层 supply / I2S 问题没修完前，你先不要再把 `Channels: 2` 当成必须条件。

先回头做这条最小验证：

```bash
arecord -D plughw:<ReSpeaker_CARD>,0 -c 1 -r 48000 -f S16_LE -d 5 test_1ch.wav
soxi test_1ch.wav
```

这一阶段你至少先要看到：

- `Channels: 1`
- `Sample Rate: 48000`
- 文件大小明显大于 `44 bytes`

如果连这条单声道 smoke test 也还是直接报 `Input/output error`，那就不要再纠结通道数了，直接回到 [7.9](#79-arecord-l-看不到-respeaker) 继续按 codec / device tree 问题处理。

### 7.11 `pi5` 的两只领夹麦录出来像混在一起

这通常意味着：

1. 你的 USB 声卡不是真双输入。
2. 接口接法不对。
3. 两个麦实际上被混成了同一个立体声输入。

最短检查方法：

1. 让 A 先说话，B 保持安静。
2. 再让 B 说话，A 保持安静。
3. 分别看左右声道能量是否明显分离。

### 7.12 环境麦录出来全是房间反射和底噪

先不要急着换算法，优先改摆位：

1. 不要放墙角。
2. 不要放桌角。
3. 不要离风扇、空调、电源排插、路由器太近。
4. 先退回到距离活动区 `1 - 2 m`、高度 `1.2 - 1.6 m` 的中间位置重新录一轮。

---

## 8. 当前这套环境下一句话建议

你现在最应该做的不是继续纠结 5GHz，而是：

1. 让 `pi3` 从 `36/80` 切到 `11/20`
2. 在 `pi2` 上对当前公共 Wi-Fi 网关持续发包
3. 在 `pi3` 上确认 `monitor: 1` 和 `udp dst port 5500`
4. 先在 `pi3` 上把 ReSpeaker 的 `单声道 / 48 kHz` smoke test 单独跑通
5. 再在 `pi5` 上把 USB 声卡的 `2 通道 / 48 kHz` 录音单独跑通
6. 一旦要做正式采集，就换成自带固定信道网络