# 6 台 Pi 5 Wi-Fi CSI 部署手册

> 版本：v0.1
> 范围：Wi-Fi only，3 个发射端分时，3 个接收端持续监听，Nexmon CSI，单房间部署

## 0. 先说结论

这套系统不是 3 对一一绑定的点对点链路，而是一个 **3 Tx + 3 Rx 的分布式多链路 CSI 系统**。

- 3 个 Tx 只是 3 个受控照明源
- 3 个 Rx 会持续监听同一固定 5 GHz 信道上的全部 3 个 Tx
- 正式实验必须走 **TDMA 分时发包**，不建议 3 个 Tx 同时并发乱发
- 全部 6 台 Pi 5 都可以安装 Nexmon，方便后面调换角色；但正式运行时只有 Rx 节点启用 CSI 抽取，Tx 节点保持普通 managed client 模式连接 AP

## 1. 房间摆位方案

### 1.1 推荐房间几何

假设房间约 6 m x 4 m，中间留一个 2 m x 2 m 活动区。推荐把 6 台 Pi 放成一个交错六边形，而不是 3 对相对独立的小链路。

```text
北墙

RX-A (0.8, 3.2)      TX-C (3.0, 3.5)      RX-B (5.2, 3.2)


             [    中央活动区 / HAR / HAU 区域    ]

TX-A (0.8, 0.8)      RX-C (3.0, 0.5)      TX-B (5.2, 0.8)

南墙
```

推荐高度：
- Tx：1.2 m 到 1.4 m
- Rx：1.0 m 到 1.2 m
- AP：2.0 m 到 2.4 m，尽量靠墙或靠门，不要占据中央活动区

### 1.2 每个节点的角色

| 节点 | 推荐主机名 | 管理 IP | 角色 | 建议位置 |
|---|---|---|---|---|
| 控制主机 | `cuhky-host` | `10.0.50.10` | SSH / rsync / 离线分析 | 管理桌面 |
| Tx-A | `rpi5-tx-a` | `10.0.50.11` | TDMA slot 0 发射端 | 房间南侧偏西 |
| Tx-B | `rpi5-tx-b` | `10.0.50.12` | TDMA slot 1 发射端 | 房间南侧偏东 |
| Tx-C | `rpi5-tx-c` | `10.0.50.13` | TDMA slot 2 发射端 | 房间北侧中央 |
| Rx-A | `rpi5-rx-a` | `10.0.50.21` | 持续监听 + CSI 抓包 | 房间北侧偏西 |
| Rx-B | `rpi5-rx-b` | `10.0.50.22` | 持续监听 + CSI 抓包 | 房间北侧偏东 |
| Rx-C | `rpi5-rx-c` | `10.0.50.23` | 持续监听 + CSI 抓包 | 房间南侧中央 |
| AP | `cuhky-csi-ap` | 由 AP 决定 | dedicated 5 GHz AP | 靠墙高处 |

### 1.3 为什么这样摆

这套摆法的核心目标是：
- 让 9 条 Tx-Rx 路径尽可能穿过中央活动区
- 避免 3 对链路彼此平行、信息重复过多
- 保留南北、左右、斜向三类空间穿越路径
- 让 3 个 Rx 看到的空间扰动是互补的，而不是纯冗余的

## 2. 网络拓扑方案

### 2.1 管理网和感知网分离

```text
Mac / Linux 控制主机 (10.0.50.10)
           |
         千兆交换机
  |        |        |        |        |        |
Tx-A     Tx-B     Tx-C     Rx-A     Rx-B     Rx-C
eth0     eth0     eth0     eth0     eth0     eth0

Dedicated 5 GHz AP  <---- 所有 Tx 的 wlan0 连接到这里
          ^
          |
     Rx-A / Rx-B / Rx-C 的 wlan0 不走 STA 关联，而是锁到同一固定信道做 CSI 监听
```

原则：
- `eth0` 只负责管理、SSH、chrony、rsync
- `wlan0` 只负责 Wi-Fi CSI 感知
- 不要在 CSI 运行期间依赖 `wlan0` 做 SSH 管理

## 3. Dedicated 5 GHz AP 设置

你需要一个独立的 5 GHz AP 或路由器。建议配置：

- Band：5 GHz only
- SSID：`CUHKY-CSI-5G`
- Security：`WPA2-PSK`
- Channel：固定 `36`
- Bandwidth：第一次 bring-up 用 `20 MHz`，正式 baseline 用 `40 MHz`
- 关闭自动选信道
- 关闭 band steering
- 关闭 mesh / roaming / airtime fairness

不建议：
- 直接用公共 Wi-Fi 做正式采集
- 开启双频合一、自动跳信道
- 一开始就用 `80 MHz`

## 4. Pi 5 初始化

### 4.1 烧录系统

推荐基线系统：
- Raspberry Pi OS Lite 64-bit
- Bookworm 或更新版本

在 Raspberry Pi Imager 里一次性完成：
- 启用 SSH
- 用户名统一设为 `pi`
- 给 6 台机器分别设 hostname
- 不预配 Wi-Fi
- 时区设为 `Asia/Hong_Kong`

### 4.2 首次开机后的基础包

**推荐方式（控制主机一键引导）：**

如果你在 Mac 控制主机上，直接跑自动化脚本可以对全部 6 台 Pi 批量完成基础包安装 + Nexmon 编译安装（§6），不用逐台手动操作：

```bash
# 先确认 Mac 上装了 sshpass
brew install hudochenkov/sshpass/sshpass   # 没装过的话先执行这一步

# 一键引导全部 6 台
cd /Users/labahua/Desktop/CUHK-Y
bash pilot_6pi_wifi/scripts/setup_6pi_bootstrap.sh
```

> **注意**：`setup_6pi_bootstrap.sh` 包含明文密码，已加入 `.gitignore`，不要提交到公共仓库。脚本会在每台 Pi 的 tmux `bootstrap` 会话里后台运行（约 15–30 分钟/台），完成后写入 `~/bootstrap_done.flag`。

**手动方式（逐台执行）：**

每台 Pi 执行：

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  git gawk qpdf bison flex make xxd automake autoconf libtool texinfo \
  tcpdump iw wireless-tools net-tools pkg-config \
  libnl-3-dev libnl-genl-3-dev libcap2-bin \
  chrony tmux rsync python3-pip python3-venv linux-headers-$(uname -r)
sudo timedatectl set-timezone Asia/Hong_Kong
```

### 4.3 管理网静态 IP

Pi 5 + Bookworm 默认优先按 `NetworkManager` 路线处理，建议直接用 `nmcli`：

```bash
# 以 Tx-A 为例
sudo nmcli con mod "Wired connection 1" ipv4.method manual \
  ipv4.addresses 10.0.50.11/24
sudo nmcli con up "Wired connection 1"
```

6 台 Pi 分别改成：
- `10.0.50.11`
- `10.0.50.12`
- `10.0.50.13`
- `10.0.50.21`
- `10.0.50.22`
- `10.0.50.23`

控制主机的有线口手工设成：
- IP：`10.0.50.10`
- Mask：`255.255.255.0`
- Gateway：留空

## 5. 时间同步

所有节点先启 `chrony`：

```bash
sudo systemctl enable chrony
sudo systemctl restart chrony
chronyc tracking
```

至少做到：
- 所有节点 `NTPSynchronized=yes`
- 6 台设备的时间偏差稳定在毫秒级到几十毫秒级

## 6. 在 6 台 Pi 5 上安装 Nexmon

虽然正式运行时只有 3 个 Rx 会开启 CSI 抽取，我仍建议 **6 台机器都安装同一版 Nexmon**，原因是后面换角色更方便。

### 6.1 安装步骤

每台 Pi 执行：

```bash
cd ~
git clone https://github.com/seemoo-lab/nexmon.git
cd ~/nexmon
source setup_env.sh
make

# 说明：make 过程中 buildtools/b43/assembler 可能出现 bison 相关警告或非致命错误，
# 这个子目标是给老款 Broadcom AP 芯片用的，bcm43455c0 (Pi 5) 不需要它。
# 只要 buildtools 整体没有阻断 nexutil 的编译，就可以继续。

cd ~/nexmon/utilities/nexutil
make USE_VENDOR_CMD=1
sudo make install USE_VENDOR_CMD=1
sudo setcap cap_net_admin+ep /usr/bin/nexutil

cd ~/nexmon/patches/bcm43455c0/7_45_189
git clone https://github.com/seemoo-lab/nexmon_csi.git
cd nexmon_csi
make -f Makefile.rpi install-firmware
make -f Makefile.rpi reload-full
```

### 6.2 角色区别

- Tx 节点：安装 Nexmon，但正常实验时 `wlan0` 保持连接 AP，不启 monitor 抽取
- Rx 节点：安装 Nexmon，并在采集时用 `nexutil` 锁信道、启 monitor、抓 UDP 5500

### 6.3 ⚠️ Pi 5 的 monitor 模式只能通过 nexutil 设置

**常见误区**：在 Pi 5（bcm43455c0 / brcmfmac 驱动）上，以下命令**无效**，会直接报错 `-95 (Operation not supported)`：

```bash
# ❌ 在 Pi 5 上无效
sudo iw dev wlan0 set type monitor
```

正确做法是：**等 Nexmon 安装完毕**，用 vendor 命令通过 `nexutil` 切换：

```bash
# ✅ Nexmon 安装后才能用
sudo ip link set wlan0 down
sudo nexutil -Iwlan0 -m2      # -m2 = monitor mode via vendor command
sudo ip link set wlan0 up

# 验证（期望输出 803）
cat /sys/class/net/wlan0/type
```

`/sys/class/net/wlan0/type` 的含义：
- `1` = managed（Ethernet-style，默认）
- `803` = monitor（IEEE 802.11 radiotap，Nexmon CSI 所需）

> 如果 bootstrap 还没跑完（`~/bootstrap_done.flag` 不存在），nexutil 尚未安装，monitor 模式无法设置，需要先等 bootstrap 完成。

## 7. 把 Tx 节点切到 5 GHz AP

### 7.1 批量从控制主机执行（推荐）

在 Mac 控制主机上，用 `sshpass` 批量操作。注意两个已知坑（见下方故障说明）：

```bash
# Mac 上：先确认 sshpass 可用
brew install hudochenkov/sshpass/sshpass
sshpass -V   # 确认输出版本号

# Step 1：确保 wlan0 在 managed 模式，并刷新扫描缓存
for info in \
  "pi5-1@192.168.2.7:raspberrypi5-1" \
  "pi5-2@192.168.2.10:raspberrypi5-2" \
  "pi5-3@192.168.2.13:raspberrypi5-3"; do
  ssh_target="${info%%:*}"
  pi_pw="${info##*:}"
  echo "── Tx ${ssh_target} ──"
  sshpass -p "$pi_pw" ssh -o StrictHostKeyChecking=accept-new "$ssh_target" "
    echo '$pi_pw' | sudo -S ip link set wlan0 down 2>/dev/null
    echo '$pi_pw' | sudo -S iw dev wlan0 set type managed 2>/dev/null || true
    echo '$pi_pw' | sudo -S ip link set wlan0 up
    echo '$pi_pw' | sudo -S nmcli device set wlan0 managed yes 2>/dev/null || true
    echo '$pi_pw' | sudo -S nmcli dev wifi rescan ifname wlan0 2>/dev/null || true
    sleep 4
    echo '$pi_pw' | sudo -S nmcli connection delete 'CUHKY-CSI-5G' 2>/dev/null || true
    echo '$pi_pw' | sudo -S nmcli dev wifi connect 'CUHKY-CSI-5G' password '你的AP密码' ifname wlan0 \
      && echo 'CONNECTED OK' || echo 'CONNECT FAILED'
  "
done
```

**注意**：把 `你的AP密码` 替换成实际密码。SSID 里如有空格或特殊字符（如 `#`），单引号内原样写即可，不需要额外转义。

### 7.2 逐台手动执行

每台 Tx 节点上执行：

```bash
SSID='CUHKY-CSI-5G'
PASSWORD='你的AP密码'

sudo nmcli dev wifi rescan ifname wlan0
sleep 4
sudo nmcli dev wifi connect "$SSID" password "$PASSWORD" ifname wlan0
nmcli dev status | grep wlan0
```

### 7.3 验收

```bash
# 在每台 Tx 上确认
nmcli dev status | grep wlan0   # 期望：connected   CUHKY-CSI-5G
nmcli dev wifi list | grep '*'  # 期望：* 号指向 CUHKY-CSI-5G，freq 5xxx MHz
```

- 三个 Tx 都连到同一 AP 和同一信道
- `freq` 应为 5 GHz 范围（5180 / 5200 / 5745 等）

### 7.4 ⚠️ 已知错误及修复

| 错误信息 | 原因 | 修复 |
|---|---|---|
| `sudo: a terminal is required to read the password` | 通过 SSH 批量执行时没有伪终端，sudo 拒绝交互提示 | 改用 `echo 'pass' \| sudo -S command` 将密码通过 stdin 传入 |
| `802-11-wireless-security.key-mgmt: property is missing` | wlan0 当前处于 monitor 模式（brcmfmac 驱动在 monitor 模式下无法主动扫描），nmcli 找不到 AP 的安全策略 | 先将 wlan0 切回 managed，强制 rescan（`sleep 4`），再连接 |
| `Error: No network with SSID 'xxx' found` | AP 不在扫描范围，或 AP 还没广播该 SSID | 确认 AP 已启动并固定在 5 GHz；重新执行 rescan 再试 |

### 7.5 Rx 节点的 wlan0 不要连 AP

- Rx 节点在正式采集时 `wlan0` **不应该**关联任何 AP
- Rx 的 `wlan0` 由 `nexutil` 锁定到固定信道，进行 CSI 监听
- 如果 Rx 上存在残留的 WiFi connection profile，先删除：
  ```bash
  echo 'pi_password' | sudo -S nmcli connection delete 'CUHKY-CSI-5G' 2>/dev/null || true
  ```

## 8. 记录 Tx MAC 地址

在 Tx-A / Tx-B / Tx-C 上分别执行：

```bash
ip link show wlan0 | awk '/link\/ether/ {print $2}'
```

把 3 个 MAC 填到：
- `configs/devices.yaml`
- 启动命令里的 `--tx-macs`

这一步很重要。Rx 端用 `makecsiparams -m` 只跟踪这 3 个源 MAC，能显著减少杂散流量。

## 9. 为脚本准备 passwordless sudo

### 9.1 Rx 节点 sudoers

在 Rx-A / Rx-B / Rx-C 上创建：`/etc/sudoers.d/90-sixpi-rx`

```sudoers
Cmnd_Alias SIXPI_RX_WIFI    = /usr/bin/nmcli, /usr/bin/pkill
Cmnd_Alias SIXPI_RX_IFACE   = /sbin/ip, /usr/sbin/ip, /bin/ip, /sbin/ifconfig, /usr/sbin/ifconfig
Cmnd_Alias SIXPI_RX_CAPTURE = /usr/sbin/tcpdump, /usr/bin/tcpdump
Cmnd_Alias SIXPI_RX_FILES   = /bin/rm, /usr/bin/rm
Cmnd_Alias SIXPI_RX_SIGNAL  = /bin/kill, /usr/bin/kill
Cmnd_Alias SIXPI_RX_NEXUTIL = /home/pi/nexmon/utilities/nexutil/nexutil, \
                              /home/pi/nexmon/patches/bcm43455c0/7_45_189/nexmon_csi/utils/makecsiparams/makecsiparams

pi ALL=(root) NOPASSWD: SIXPI_RX_WIFI, SIXPI_RX_IFACE, SIXPI_RX_CAPTURE, SIXPI_RX_FILES, SIXPI_RX_SIGNAL, SIXPI_RX_NEXUTIL
```

### 9.2 Tx 节点 sudoers

在 Tx-A / Tx-B / Tx-C 上创建：`/etc/sudoers.d/90-sixpi-tx`

```sudoers
Cmnd_Alias SIXPI_TX_PING   = /bin/ping, /usr/bin/ping
Cmnd_Alias SIXPI_TX_SIGNAL = /usr/bin/pkill, /bin/kill, /usr/bin/kill

pi ALL=(root) NOPASSWD: SIXPI_TX_PING, SIXPI_TX_SIGNAL
```

验证：

```bash
sudo -n tcpdump --version    # Rx 上应通过
sudo -n ping -V              # Tx 上应通过
```

## 10. 同步新目录到 6 台 Pi

在控制主机执行：

```bash
cd /Users/labahua/Desktop/CUHK-Y
bash pilot_6pi_wifi/scripts/host_prepare_6pi.sh
```

默认会同步到每台 Pi 的：

```text
/home/pi/pilot_6pi_wifi
```

## 11. 3Tx/3Rx 分时实验 protocol

### 11.1 推荐的正式 baseline

| 配置 | 建议值 |
|---|---|
| AP 频段 | 5 GHz |
| 信道 | `36` |
| 带宽 | `40 MHz` |
| 时隙长度 | `300 ms` |
| 周期 | `3 slots = 900 ms` |
| Tx-A 时隙 | slot 0 |
| Tx-B 时隙 | slot 1 |
| Tx-C 时隙 | slot 2 |
| burst count | `120` |
| burst interval | `0.002 s` |
| 目标总包率 | 每个 Rx `>= 300 pps` |
| 最低可接受总包率 | 每个 Rx `>= 180 pps` |

### 11.2 时隙图

```text
cycle = 900 ms

0-300 ms     : Tx-A active
300-600 ms   : Tx-B active
600-900 ms   : Tx-C active
900-1800 ms  : repeat
```

### 11.3 为什么不把 3 对链路独立绑定

不要把系统理解成：
- Tx-A 只给 Rx-A
- Tx-B 只给 Rx-B
- Tx-C 只给 Rx-C

正确理解是：
- 所有 3 个 Rx 都持续监听所有 3 个 Tx
- pair 只是时隙编号，不是物理隔离关系
- 后续真正有价值的是 9 条逻辑链路的融合，而不是 3 条独占链路

### 11.4 命名规范

会话名统一格式：

```text
YYYYMMDD_roomXX_task_trialNN
```

示例：
- `20260513_room01_empty_trial01`
- `20260513_room01_walk1p_trial03`
- `20260513_room01_dualwalk_trial02`

所有节点使用同一个 `SESSION` 值。
不同设备的身份由各自主机目录体现，而不是由文件名重复编码。

### 11.5 每轮实验的动作时间轴

因为现在只做 Wi-Fi，不用音频拍手。建议改成一个纯动作标记：

- 0 到 5 秒：完全静止
- 第 5 秒：做一次大幅度同步动作，例如双臂上举再放下
- 第 6 秒开始：进入正式任务动作
- 最后 5 秒：再次静止，方便后处理切边

## 12. 启动一轮 6Pi 会话

在控制主机执行：

```bash
cd /Users/labahua/Desktop/CUHK-Y

SESSION="20260513_room01_walk1p_trial01"
TX_MACS="aa:bb:cc:dd:ee:01,aa:bb:cc:dd:ee:02,aa:bb:cc:dd:ee:03"

bash pilot_6pi_wifi/scripts/host_start_6pi_session.sh \
  --session "$SESSION" \
  --duration 60 \
  --channel 36/40 \
  --start-delay 10 \
  --slot-ms 300 \
  --burst-count 120 \
  --burst-interval 0.002 \
  --tx-target auto-gateway \
  --tx-macs "$TX_MACS"
```

说明：
- 3 个 Rx 会先启动并进入监听状态
- 3 个 Tx 会拿到同一个 `start_epoch`，到点后按 slot 0/1/2 循环发包

## 13. 停止与回收

### 13.1 停止

```bash
bash pilot_6pi_wifi/scripts/host_stop_6pi_session.sh --session "$SESSION"
```

### 13.2 拉回 raw data 和日志

```bash
bash pilot_6pi_wifi/scripts/pull_session.sh --session "$SESSION" --include-logs \
  pi@10.0.50.11 \
  pi@10.0.50.12 \
  pi@10.0.50.13 \
  pi@10.0.50.21 \
  pi@10.0.50.22 \
  pi@10.0.50.23
```

## 14. 快速验收

### 14.1 文件层面

每个 Rx 最少应有：
- 一个 `pcap`
- 一份对应会话日志

### 14.2 pcap 总包率

对每个 Rx 的 pcap 执行：

```bash
bash pilot_6pi_wifi/scripts/check_csi_rate.sh \
  pilot_6pi_wifi/data/pulls/$SESSION/pi@10.0.50.21/raw/csi/$SESSION.pcap 60
```

正式 baseline 的验收标准：
- 每个 Rx 的总 CSI 包率 `>= 180 pps`
- 目标值 `>= 300 pps`
- 三个 Rx 之间的总包率差异不应超过约 `25%`

### 14.3 快速预览图

```bash
python3 pilot_6pi_wifi/analysis/parse_csi_preview.py \
  pilot_6pi_wifi/data/pulls/$SESSION --pattern "*.pcap"
```

你应该能看到：
- 3 个 Rx 都有非空 trace
- 空房间时波动较平稳
- 同步动作和 walking 段明显高于静止段

## 15. 推荐实验顺序

1. `36/20` 空房间 60 秒 bring-up
2. `36/20` 单人静止 vs 单人走动
3. `36/40` 单人 5 类 HAR baseline
4. `36/40` 双人 coarse HAU baseline
5. 最后才考虑 `36/80`

## 16. 常见故障

### 16.1 Mac 上 sshpass 找不到

```
zsh: command not found: sshpass
```

修复：

```bash
brew install hudochenkov/sshpass/sshpass
sshpass -V   # 确认安装成功
```

### 16.2 SSH 批量执行时 sudo 要求终端

```
sudo: a terminal is required to read the password; either use the -S option...
```

原因：通过 `ssh user@host 'sudo command'` 执行时，ssh 默认没有分配伪终端（pseudo-tty），sudo 拒绝弹交互密码框。

修复：在 SSH 命令里用 `echo 'pass' | sudo -S` 把密码通过 stdin 传给 sudo：

```bash
sshpass -p "$pi_pw" ssh "$ssh_target" "echo '$pi_pw' | sudo -S nmcli ..."
```

### 16.3 nmcli 报 key-mgmt 缺失

```
Error: 802-11-wireless-security.key-mgmt: property is missing.
```

原因：wlan0 当前处于 monitor 模式（或刚从 monitor 切回但扫描缓存还是空的），nmcli 在扫描结果里找不到目标 AP，因此无法推断安全模式（WPA2/WPA3）。

修复步骤：
1. 将 wlan0 切回 managed 模式（brcmfmac 只支持 iw 在 **down 状态**下切换）
2. 让 NetworkManager 重新管理接口
3. 等 4–6 秒扫描完成
4. 再执行 nmcli connect

```bash
echo '$pi_pw' | sudo -S ip link set wlan0 down
echo '$pi_pw' | sudo -S iw dev wlan0 set type managed 2>/dev/null || true
echo '$pi_pw' | sudo -S ip link set wlan0 up
echo '$pi_pw' | sudo -S nmcli device set wlan0 managed yes
echo '$pi_pw' | sudo -S nmcli dev wifi rescan ifname wlan0
sleep 5
echo '$pi_pw' | sudo -S nmcli dev wifi connect 'CUHKY-CSI-5G' password 'AP密码' ifname wlan0
```

### 16.4 iw set type monitor 返回 -95

```
command failed: Operation not supported (-95)
```

原因：Pi 5 的 brcmfmac 驱动**不支持**通过标准 `iw dev wlan0 set type monitor` 切换 monitor 模式。这是已知的驱动限制，与内核版本无关。

修复：安装 Nexmon 后改用 `nexutil -m2`（见 §6.3）。

### 16.5 Tx 连不上 5 GHz

先看：

```bash
nmcli dev status
nmcli dev wifi list | head -20
```

常见原因：
- AP 没固定在 5 GHz
- SSID 做了双频合一
- AP 自动跳信道
- wlan0 仍在 monitor 模式导致扫描失败（见 §16.3）

### 16.2 Rx 抓不到 UDP 5500

检查：

```bash
sudo nexutil -Iwlan0 -k
sudo nexutil -m
sudo tcpdump -ni wlan0 udp dst port 5500 -c 20
```

常见原因：
- 信道不一致
- `wpa_supplicant` 抢回了接口
- `--tx-macs` 写错，导致过滤把目标帧全滤掉了

### 16.3 包率太低

先按下面顺序排：

1. 把 profile 退回 `36/20`
2. 只保留 1 个 Tx 测最小链路
3. 逐个加回 Tx-B、Tx-C
4. 增大 `burst_count`
5. 确认 AP 关闭了自动信道和 airtime fairness

### 16.4 3 个 Tx 包率极不均衡

优先检查：
- AP 距离是否对某个 Tx 明显不公平
- 某个 Tx 的 `wlan0` 是否掉回 2.4 GHz 或重新漫游
- 某个 Tx 的时隙脚本是否没有按共享 `start_epoch` 启动

## 17. 最终建议

正式研究时，把这套系统当成：
- 一个 3Tx/3Rx 的分布式多链路感知平台
- 更适合 HAR 和 coarse HAU
- 更适合做链路融合、空间多样性利用和多视角鲁棒性分析

不要把它当成：
- 真正同步相干的 3x3 阵列
- 可以直接做高精度 AoA / 波束形成 / 精细几何重建的平台

如果你的目标是先把 6 台 Pi 5 的 Wi-Fi-only 数据稳定跑起来，这份 runbook 的优先级顺序是对的：
- 先固定管理网
- 再固定 5 GHz AP
- 再安装 Nexmon
- 再跑 1Tx/3Rx bring-up
- 最后上 3Tx/3Rx TDMA 正式 protocol
