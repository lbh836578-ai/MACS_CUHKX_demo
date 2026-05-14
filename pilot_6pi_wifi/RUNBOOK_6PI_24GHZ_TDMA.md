# 6 台 Pi 5 2.4 GHz Wi-Fi CSI 部署手册

> 版本：v0.1
> 范围：Wi-Fi only，3 个发射端分时，3 个接收端持续监听，Nexmon CSI，单房间部署，2.4 GHz 专用版本

## 0. 先说结论

这份 runbook 适用于两种场景：
- 你暂时没有稳定可控的 5 GHz AP
- 你想先用更容易接入的 2.4 GHz 环境，把 6 台 Pi 5 的 3Tx/3Rx CSI 系统跑通

它的定位应该是：
- 很适合做 bring-up、烟雾测试、低门槛 baseline
- 也可以做正式 HAR 和 coarse HAU 采集
- 但如果你追求更高频谱分辨率、更低环境干扰、更高上限，5 GHz 版本通常仍然更优

这套系统不是 3 对独占链路，而是一个 **3 Tx + 3 Rx 的分布式多链路 CSI 系统**：
- 3 个 Tx 只是 3 个分时照明源
- 3 个 Rx 会持续监听同一固定 2.4 GHz 信道上的全部 3 个 Tx
- 正式实验必须走 **TDMA 分时发包**，不建议 3 个 Tx 同时并发乱发
- 全部 6 台 Pi 5 都建议安装同一版 Nexmon，方便后面调换角色

## 1. 什么时候优先用 2.4 GHz

优点：
- AP 和现有环境更容易接入
- 对墙体、家具和人体遮挡通常更不敏感
- 带机和 bring-up 成本更低
- 适合先验证 6 台 Pi 5 的分布式 CSI 拓扑是否稳定

缺点：
- 背景干扰通常更强，尤其是办公室、宿舍和公寓
- 可用的非重叠信道基本只有 `1 / 6 / 11`
- 正式实验里不建议用 `40 MHz`
- 频谱分辨率和上限一般低于 5 GHz 版本

一句话判断：
- 如果你想先把系统稳定跑起来，2.4 GHz 很合适
- 如果你要冲更高质量的正式数据，优先保留 5 GHz 版本作为上限基线

## 2. 房间摆位方案

### 2.1 推荐房间几何

假设房间约 6 m x 4 m，中间留一个 2 m x 2 m 活动区。推荐把 6 台 Pi 放成交错六边形，而不是 3 对相互独立的小链路。

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
- AP：2.0 m 到 2.4 m，尽量靠墙高处，不要压在中央活动区正上方

### 2.2 每个节点的角色

| 节点 | 推荐主机名 | 管理 IP | 角色 | 建议位置 |
|---|---|---|---|---|
| 控制主机 | `cuhky-host` | `10.0.50.10` | SSH / rsync / 离线分析 | 管理桌面 |
| Tx-A | `rpi5-tx-a` | `10.0.50.11` | TDMA slot 0 发射端 | 房间南侧偏西 |
| Tx-B | `rpi5-tx-b` | `10.0.50.12` | TDMA slot 1 发射端 | 房间南侧偏东 |
| Tx-C | `rpi5-tx-c` | `10.0.50.13` | TDMA slot 2 发射端 | 房间北侧中央 |
| Rx-A | `rpi5-rx-a` | `10.0.50.21` | 持续监听 + CSI 抓包 | 房间北侧偏西 |
| Rx-B | `rpi5-rx-b` | `10.0.50.22` | 持续监听 + CSI 抓包 | 房间北侧偏东 |
| Rx-C | `rpi5-rx-c` | `10.0.50.23` | 持续监听 + CSI 抓包 | 房间南侧中央 |
| AP | `cuhky-csi-ap-24g` | 由 AP 决定 | dedicated 2.4 GHz AP | 靠墙高处 |

### 2.3 为什么这样摆

这套摆法的目标和 5 GHz 版一致：
- 让 9 条 Tx-Rx 路径尽量穿过中央活动区
- 避免 3 对链路彼此平行，信息过于重复
- 保留横向、纵向和斜向路径
- 让 3 个 Rx 看到互补而非纯冗余的空间扰动

## 3. 网络拓扑方案

### 3.1 管理网和感知网分离

```text
Mac / Linux 控制主机 (10.0.50.10)
           |
         千兆交换机
  |        |        |        |        |        |
Tx-A     Tx-B     Tx-C     Rx-A     Rx-B     Rx-C
eth0     eth0     eth0     eth0     eth0     eth0

Dedicated 2.4 GHz AP  <---- 所有 Tx 的 wlan0 连接到这里
          ^
          |
     Rx-A / Rx-B / Rx-C 的 wlan0 不走 STA 关联，而是锁到同一固定信道做 CSI 监听
```

原则：
- `eth0` 只负责管理、SSH、chrony、rsync
- `wlan0` 只负责 Wi-Fi CSI
- 不要在 CSI 运行期间依赖 `wlan0` 做管理

## 4. Dedicated 2.4 GHz AP 设置

### 4.1 推荐 AP 参数

你需要一个独立的 2.4 GHz AP 或路由器。建议配置：

- Band：2.4 GHz only
- SSID：`CUHKY-CSI-24G`
- Security：`WPA2-PSK`
- Channel：固定为 `1`、`6` 或 `11` 之一
- 默认推荐：`11/20`
- Bandwidth：`20 MHz` only
- 关闭自动选信道
- 关闭 20/40 coexistence 自动扩频
- 关闭 band steering
- 关闭 mesh / roaming / airtime fairness
- 如果 AP 支持，优先关掉 802.11b legacy rate，只保留 g/n

### 4.2 2.4 GHz 为什么只建议 20 MHz

因为 2.4 GHz 的频谱太拥挤：
- 40 MHz 很容易和邻道重叠
- 一旦环境里还有其他 AP，链路稳定性和可重复性会明显变差
- 正式实验要的不是“带宽看起来更大”，而是“信道可控、链路稳定”

所以这份 runbook 里，默认只写：
- `1/20`
- `6/20`
- `11/20`

## 5. 先做一次 2.4 GHz 选信道

不要先拍脑袋决定用哪个信道。先扫描，再在 `1 / 6 / 11` 里选最干净的一个。

任选一台 Pi，在还没切 CSI 之前执行：

```bash
sudo iw dev wlan0 scan | egrep 'DS Parameter set|signal:|SSID:'
```

你真正关心的是：
- 哪个信道上周围 AP 最少
- 哪个信道上同信道强信号最少
- 哪个信道附近蓝牙、IoT、宿舍路由器最少

默认建议：
- 如果环境不明，先试 `11/20`
- 如果 `11` 很挤，再试 `1/20` 或 `6/20`

## 6. Pi 5 初始化

### 6.1 烧录系统

推荐基线系统：
- Raspberry Pi OS Lite 64-bit
- Bookworm 或更新版本

在 Raspberry Pi Imager 里一次性完成：
- 启用 SSH
- 用户名统一设为 `pi`
- 给 6 台机器分别设 hostname
- 不预配 Wi-Fi
- 时区设为 `Asia/Hong_Kong`

### 6.2 首次开机后的基础包

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

### 6.3 管理网静态 IP

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

## 7. 时间同步

所有节点执行：

```bash
sudo systemctl enable chrony
sudo systemctl restart chrony
chronyc tracking
```

至少做到：
- 所有节点 `NTPSynchronized=yes`
- 6 台设备时间偏差稳定在毫秒级到几十毫秒级

## 8. 在 6 台 Pi 5 上安装 Nexmon

虽然正式运行时只有 3 个 Rx 会开启 CSI 抽取，我仍建议 6 台机器都安装同一版 Nexmon，方便后面切换角色。

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

角色区别：
- Tx 节点：安装 Nexmon，但实验时 `wlan0` 保持连接 AP，不启 monitor 抽取
- Rx 节点：安装 Nexmon，并在采集时锁定 2.4 GHz 固定信道、启 monitor、抓 UDP 5500

## 9. 把 Tx 节点切到 dedicated 2.4 GHz AP

3 个 Tx 节点执行：

```bash
SSID="CUHKY-CSI-24G"
PASSWORD="改成你的密码"

sudo nmcli dev wifi connect "$SSID" password "$PASSWORD" ifname wlan0
iw dev wlan0 link
```

验收：
- `iw dev wlan0 link` 能看到 `freq: 2412`、`2437` 或 `2462`
- 三个 Tx 都连到同一 AP 和同一信道
- 三个 Tx 不要发生频繁漫游或自动断开重连

注意：
- Rx 节点在正式采集时不要把 `wlan0` 连到 AP
- Rx 的 `wlan0` 只负责锁定同一固定信道并监听

## 10. 记录 Tx MAC 地址

在 Tx-A / Tx-B / Tx-C 上分别执行：

```bash
ip link show wlan0 | awk '/link\/ether/ {print $2}'
```

把 3 个 MAC 填到：
- [pilot_6pi_wifi/configs/devices.yaml](pilot_6pi_wifi/configs/devices.yaml)
- 启动命令里的 `--tx-macs`

这一步很关键。Rx 端可以用 `makecsiparams -m` 只跟踪这 3 个源 MAC，显著减少杂散流量。

## 11. 为脚本准备 passwordless sudo

### 11.1 Rx 节点 sudoers

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

### 11.2 Tx 节点 sudoers

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

## 12. 同步 6Pi 目录到全部节点

在控制主机执行：

```bash
cd /Users/labahua/Desktop/CUHK-Y
bash pilot_6pi_wifi/scripts/host_prepare_6pi.sh
```

默认会同步到每台 Pi 的：

```text
/home/pi/pilot_6pi_wifi
```

## 13. 3Tx/3Rx 2.4 GHz 实验 protocol

### 13.1 推荐的 2.4 GHz 正式 baseline

| 配置 | 建议值 |
|---|---|
| AP 频段 | 2.4 GHz |
| 信道 | `11/20` |
| 备选信道 | `1/20` 或 `6/20` |
| 带宽 | `20 MHz` |
| 时隙长度 | `300 ms` |
| 周期 | `3 slots = 900 ms` |
| Tx-A 时隙 | slot 0 |
| Tx-B 时隙 | slot 1 |
| Tx-C 时隙 | slot 2 |
| burst count | `90` |
| burst interval | `0.003 s` |
| 每个 Rx 最低可接受总包率 | `>= 120 pps` |
| 每个 Rx 目标总包率 | `>= 220 pps` |

### 13.2 为什么这版参数比 5 GHz 更保守

因为 2.4 GHz 更容易受外部干扰：
- 邻居 AP 和公共路由器更多
- 蓝牙、IoT、无线鼠标等共享频段
- 你想要的是稳定、重复的 CSI，不是把 AP 压到极限

所以这版 baseline 默认更保守：
- 只用 20 MHz
- 不追求太高 burst 密度
- 先保证 3 个 Rx 都稳，再往上加压

### 13.3 时隙图

```text
cycle = 900 ms

0-300 ms     : Tx-A active
300-600 ms   : Tx-B active
600-900 ms   : Tx-C active
900-1800 ms  : repeat
```

### 13.4 命名规范

会话名统一格式：

```text
YYYYMMDD_roomXX_task_trialNN
```

示例：
- `20260513_room01_empty24g_trial01`
- `20260513_room01_walk1p24g_trial03`
- `20260513_room01_dualwalk24g_trial02`

所有节点统一使用同一个 `SESSION` 值。

### 13.5 动作时间轴

因为现在只做 Wi-Fi，不用音频拍手。建议每轮试次固定成：
- 0 到 5 秒：完全静止
- 第 5 秒：做一次大幅度同步动作，例如双臂上举再放下
- 第 6 秒开始：进入正式任务动作
- 最后 5 秒：再次静止，方便后处理切边

## 14. 启动一轮 2.4 GHz 6Pi 会话

在控制主机执行：

```bash
cd /Users/labahua/Desktop/CUHK-Y

SESSION="20260513_room01_walk1p24g_trial01"
TX_MACS="aa:bb:cc:dd:ee:01,aa:bb:cc:dd:ee:02,aa:bb:cc:dd:ee:03"

bash pilot_6pi_wifi/scripts/host_start_6pi_session.sh \
  --session "$SESSION" \
  --duration 60 \
  --channel 11/20 \
  --start-delay 10 \
  --slot-ms 300 \
  --burst-count 90 \
  --burst-interval 0.003 \
  --tx-target auto-gateway \
  --tx-macs "$TX_MACS"
```

如果 `11/20` 太拥挤，就改成：
- `--channel 1/20`
- 或 `--channel 6/20`

## 15. 停止与回收

### 15.1 停止

```bash
bash pilot_6pi_wifi/scripts/host_stop_6pi_session.sh --session "$SESSION"
```

### 15.2 拉回 raw data 和日志

```bash
bash pilot_6pi_wifi/scripts/pull_session.sh --session "$SESSION" --include-logs \
  pi@10.0.50.11 \
  pi@10.0.50.12 \
  pi@10.0.50.13 \
  pi@10.0.50.21 \
  pi@10.0.50.22 \
  pi@10.0.50.23
```

## 16. 快速验收

### 16.1 文件层面

每个 Rx 最少应有：
- 一个 `pcap`
- 一份对应会话日志

### 16.2 pcap 总包率

对每个 Rx 的 pcap 执行：

```bash
bash pilot_6pi_wifi/scripts/check_csi_rate.sh \
  pilot_6pi_wifi/data/pulls/$SESSION/pi@10.0.50.21/raw/csi/$SESSION.pcap 60
```

2.4 GHz baseline 的验收标准：
- 每个 Rx 的总 CSI 包率 `>= 120 pps`
- 目标值 `>= 220 pps`
- 三个 Rx 之间的总包率差异最好不超过约 `30%`

### 16.3 快速预览图

```bash
python3 pilot_6pi_wifi/analysis/parse_csi_preview.py \
  pilot_6pi_wifi/data/pulls/$SESSION --pattern "*.pcap"
```

你应该能看到：
- 3 个 Rx 都有非空 trace
- 静止段比 walking 段更平稳
- 同步动作附近出现明显波动

## 17. 先做什么实验最合理

推荐顺序：
1. `11/20` 空房间 60 秒 bring-up
2. `11/20` 单人静止 vs 单人走动
3. `11/20` 单人 5 类 HAR baseline
4. `11/20` 双人 coarse HAU baseline
5. 如果 `11/20` 不稳，再换到 `1/20` 或 `6/20`

不建议的顺序：
- 一上来就做长时双人复杂动作
- 一开始就追高包率
- 一开始就尝试 40 MHz

## 18. 常见故障

### 18.1 2.4 GHz AP 很拥挤

先做两件事：
1. 重新扫 `1 / 6 / 11`
2. 换一个更少人用的时间段采集

### 18.2 Tx 看起来连上了 AP，但包率很低

检查：

```bash
iw dev wlan0 link
ping -I wlan0 -c 20 <gateway_ip>
```

常见原因：
- AP 虽然是 2.4 GHz，但启了自动 20/40 coexistence
- 信道虽然是 11，但旁边有强干扰源
- 某个 Tx 离 AP 太远或被金属遮挡

### 18.3 Rx 抓不到 UDP 5500

检查：

```bash
sudo nexutil -Iwlan0 -k
sudo nexutil -m
sudo tcpdump -ni wlan0 udp dst port 5500 -c 20
```

常见原因：
- Rx 锁的信道和 AP 不一致
- `wpa_supplicant` 抢回了接口
- `--tx-macs` 写错，导致过滤把目标帧全滤掉了

### 18.4 包率很不稳定

2.4 GHz 下更常见。按这个顺序排：
1. 先从 `11/20` 换到 `1/20` 或 `6/20`
2. 降低 `burst_count`
3. 把活动区外的蓝牙设备先关掉
4. 先只保留 1 个 Tx 做最小链路确认
5. 再逐个加回 Tx-B、Tx-C

## 19. 最终建议

2.4 GHz 版本最适合做：
- 6 台 Pi 5 的完整 bring-up
- 低门槛多链路 baseline
- 对抗遮挡和室内复杂反射的稳健性验证
- HAR 和 coarse HAU 的可用性验证

2.4 GHz 版本不适合被误解成：
- 高频谱分辨率上限最高的正式平台
- 干扰最少的科研黄金配置

所以更准确的定位是：
- **它是很好的 6Pi 实战版本**
- **也是很好的正式 baseline**
- **但如果 5 GHz 条件成熟，仍建议保留 5 GHz 版作为上限对照**
