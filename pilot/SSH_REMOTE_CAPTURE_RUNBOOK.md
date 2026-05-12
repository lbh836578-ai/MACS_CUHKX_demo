# CUHK-Y Pilot SSH Remote Capture Runbook

这份文档只覆盖当前可执行的 raw capture 流程：

- 控制主机：Mac，管理网 IP 为 `192.168.2.1`
- `pi2`：CSI Tx，管理网 `192.168.2.2`
- `pi3`：CSI Rx + 环境麦，管理网 `192.168.2.3`
- `pi4`：CSI Rx + 环境麦，管理网 `192.168.2.4`
- `pi5`：个人麦，管理网 `192.168.2.6`
- 当前 smoke test 网络：`木木家`，CSI channel 使用 `11/20`
- 当前控制方式：Mac 通过 SSH 下发命令，真正的采集进程在各台 Pi 本地运行并本地写盘

这份文档不处理 Nexmon 安装、ReSpeaker 驱动安装、USB 声卡驱动安装本身；它假设这些基础能力已经至少完成过一次可用验证。

## 1. 当前目录和职责

统一约定：

- Mac 上保留一份完整目录：`/Users/labahua/Desktop/CUHK-Y/pilot`
- 每台 Pi 上保留一份完整目录：`/home/pi/pilot`
- 采集数据写在各台 Pi 的 `~/pilot/data/raw/`
- 采集日志写在各台 Pi 的 `~/pilot/logs/`
- 录制结束后由 Mac 用 `pull_session.sh` 拉回到本地 `pilot/data/pulls/<session>/`

## 2. SSH 约定

下面默认你在各台 Pi 上的 SSH 登录名都是 `pi`。如果你现在实际使用的是 `pi2@192.168.2.2`、`pi3@192.168.2.3` 这种单独用户名，只改下面这 4 行变量即可，后文其他命令不用改。

在 Mac 上先进入项目目录：

```bash
cd /Users/labahua/Desktop/CUHK-Y
```

定义远端：

```bash
PI2_SSH="pi@192.168.2.2"
PI3_SSH="pi@192.168.2.3"
PI4_SSH="pi4@192.168.2.4"
PI5_SSH="pi5@192.168.2.6"
```

测试 SSH：

```bash
ssh "$PI2_SSH" 'hostname; whoami; pwd'
ssh "$PI3_SSH" 'hostname; whoami; pwd'
ssh "$PI4_SSH" 'hostname; whoami; pwd'
ssh "$PI5_SSH" 'hostname; whoami; pwd'
```

可选：如果你想以后直接用 `ssh pi3` 这种短命令，在 Mac 的 `~/.ssh/config` 里写：

```sshconfig
Host pi2
  HostName 192.168.2.2
  User pi

Host pi3
  HostName 192.168.2.3
  User pi

Host pi4
  HostName 192.168.2.4
  User pi4

Host pi5
  HostName 192.168.2.6
  User pi5
```

然后执行：

```bash
chmod 600 ~/.ssh/config
```

## 3. 一次性准备

### 3.0 一键 SSH 免密 + sudo 免密配置（首次必做）

运行以下脚本，一次性完成 SSH 公钥分发和 CSI 节点的 `NOPASSWD` sudoers 配置。
**脚本运行过程中会提示输入各 Pi 密码各一次；运行完毕后所有后续命令均无需密码。**

```bash
cd /Users/labahua/Desktop/CUHK-Y
bash pilot/scripts/setup_pilot.sh
```

脚本做了以下事情：
1. 在 Mac 生成 `~/.ssh/id_pilot` 密钥对（如已有则跳过）
2. 在 `~/.ssh/config` 里为 `192.168.2.*` 网段添加 `IdentityFile ~/.ssh/id_pilot`
3. `ssh-copy-id` 把公钥推送到全部 Pi（每台 Pi 需要密码一次）
4. 在 pi3 / pi4 安装 `/etc/sudoers.d/90-pilot-csi`：仅放行 `nmcli / ip / tcpdump / nexutil / kill / rm`，无 `ALL` 权限
5. 验证各节点 `sudo -n true` 通过
6. 把 Mac 上的 `pilot/scripts/` 同步到所有 Pi

> 之后再次分发脚本也只需重新运行 `setup_pilot.sh` 即可（step 1–2 会自动跳过）。

### 3.1 在 Pi 端创建目录

```bash
for host in "$PI2_SSH" "$PI3_SSH" "$PI4_SSH" "$PI5_SSH"; do
  ssh "$host" 'mkdir -p ~/pilot'
done
```

### 3.2 分发当前 pilot 目录

推荐同步整套目录，但排除本地已有数据和日志：

```bash
for host in "$PI2_SSH" "$PI3_SSH" "$PI4_SSH" "$PI5_SSH"; do
  rsync -av \
    --exclude '.DS_Store' \
    --exclude '__pycache__/' \
    --exclude 'data/raw/' \
    --exclude 'data/processed/' \
    --exclude 'data/pulls/' \
    --exclude 'logs/' \
    pilot/ \
    "$host":~/pilot/
done
```

如果你只更新了脚本目录：

```bash
for host in "$PI2_SSH" "$PI3_SSH" "$PI4_SSH" "$PI5_SSH"; do
  rsync -av pilot/scripts/ "$host":~/pilot/scripts/
done
```

### 3.3 检查远端脚本是否就位

```bash
for host in "$PI2_SSH" "$PI3_SSH" "$PI4_SSH" "$PI5_SSH"; do
  ssh "$host" 'cd ~/pilot && pwd && ls scripts && bash -n ~/pilot/scripts/start_tx.sh && bash -n ~/pilot/scripts/start_csi_rx.sh'
done
```

## 4. 录制前检查

### 4.1 pi2 / pi3 / pi4 的网络和 CSI 基础检查

在 Mac 上执行：

```bash
ssh "$PI2_SSH" 'ip addr show eth0 | sed -n "1,5p"; if command -v iw >/dev/null 2>&1; then iw dev wlan0 link; elif command -v nmcli >/dev/null 2>&1; then nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status | grep "^wlan0:" || true; else ip link show wlan0 || true; echo "Install iw for detailed Wi-Fi link info: sudo apt install -y iw"; fi'
ssh "$PI3_SSH" 'ip addr show eth0 | sed -n "1,5p"; if command -v iw >/dev/null 2>&1; then iw dev wlan0 link; elif command -v nmcli >/dev/null 2>&1; then nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status | grep "^wlan0:" || true; else ip link show wlan0 || true; echo "Install iw for detailed Wi-Fi link info: sudo apt install -y iw"; fi'
ssh "$PI4_SSH" 'ip addr show eth0 | sed -n "1,5p"; if command -v iw >/dev/null 2>&1; then iw dev wlan0 link; elif command -v nmcli >/dev/null 2>&1; then nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status | grep "^wlan0:" || true; else ip link show wlan0 || true; echo "Install iw for detailed Wi-Fi link info: sudo apt install -y iw"; fi'
```

当前 smoke test 期望：

- `eth0` 在 `192.168.2.0/24` 管理网可 SSH
- `pi2` 作为 Tx 节点，`wlan0` 保持连接到 `木木家` 这类现有 Wi-Fi 是正常的
- `pi3` / `pi4` 作为 CSI Rx 节点，如果管理面已经走 `eth0`，而 `wlan0` 预留给 Nexmon / monitor 模式，那么 `wlan0:wifi:disconnected:` 是正常现象，不代表管理网断了
- `pi5` 是个人麦节点，只要 `eth0` 正常、SSH 正常，`wlan0` 是否连接通常不影响录制
- 当前 demo channel 是 `11/20`
- 只有在你明确要求 `pi3` / `pi4` 通过普通 Wi-Fi 上网、拉包或做 STA 连接时，`disconnected` 才算异常
- 如果系统提示 `iw: command not found`，这不是链路故障，只是缺少 Wi-Fi 状态工具；最快的修复是 `sudo apt install -y iw`

### 4.2 pi3 / pi4 的环境麦检查

```bash
ssh "$PI3_SSH" 'arecord -l'
ssh "$PI4_SSH" 'arecord -l'
```

如果 `start_audio_env.sh` 自动找卡失败，再记录对应 `card N`，启动时用 `--card N` 显式指定。

### 4.3 pi5 的双 USB 声卡检查

```bash
ssh "$PI5_SSH" 'arecord -l'
```

记下两个 USB 输入设备对应的 `card` 编号，例如：

```bash
CARD_A=3
CARD_B=4
```

如果你的实际编号不是 `1` 和 `2`，只改这两个变量。

### 4.4 tmux 检查

```bash
for host in "$PI2_SSH" "$PI3_SSH" "$PI4_SSH" "$PI5_SSH"; do
  ssh "$host" 'tmux -V'
done
```

如果缺少 tmux：

```bash
for host in "$PI2_SSH" "$PI3_SSH" "$PI4_SSH" "$PI5_SSH"; do
  ssh -tt "$host" 'sudo apt update && sudo apt install -y tmux rsync'
done
```

说明：

- 原来的 `ssh "$host" 'sudo ...'` 会失败，是因为 SSH 直接执行远端命令时默认不给 `sudo` 分配伪终端，`sudo` 没法读密码
- `ssh -tt` 会强制分配 TTY，这样远端 `sudo` 才能正常提示输入密码
- 这个写法仍然是交互式的：每台机器可能都要输入 SSH 密码和 sudo 密码
- 如果你后面想做真正的批量无人值守，正确方向是配 SSH key，并为受控用户配置受限的 `NOPASSWD` sudo；不要把密码硬编码到 `sudo -S` 脚本里

## 5. 开始一轮完整 raw capture

### 5.1 在 Mac 上定义本轮参数

```bash
cd /Users/labahua/Desktop/CUHK-Y

PI2_SSH="pi@192.168.2.2"
PI3_SSH="pi@192.168.2.3"
PI4_SSH="pi4@192.168.2.4"
PI5_SSH="pi5@192.168.2.6"

SESSION="room01_$(date +%Y%m%d_%H%M%S)"
DURATION=30
CSI_CHANNEL="11/20"

CARD_A=3
CARD_B=4
```

说明：

- `SESSION` 是这一轮采集的统一名字，所有输出文件都带它
- `DURATION` 用于 Tx、环境麦和个人麦
- `start_csi_rx.sh` 目前没有 `--duration` 参数，所以 CSI 要在录制结束时显式 stop
- `CARD_A`、`CARD_B` 必须按 `pi5` 上 `arecord -l` 的实际结果填写

### 5.2 启动 pi3：CSI + 环境麦

CSI 必须以 root 身份启动（需要 `sudo nexutil` / `tcpdump`）。
运行 `setup_pilot.sh`（§3.0）之后，CSI 节点已配置 NOPASSWD sudo，
可以直接用 `tmux`（普通用户）启动，脚本内部的 `sudo -n` 命令会自动生效：

```bash
ssh "$PI3_SSH" "tmux new-session -d -s csi_${SESSION} /home/pi/pilot/scripts/csi_launcher.sh ${SESSION} ${CSI_CHANNEL}"
ssh "$PI3_SSH" "tmux new-session -d -s env_${SESSION} 'cd ~/pilot/scripts && ./start_audio_env.sh --session ${SESSION} --duration ${DURATION}'"
```

### 5.3 启动 pi4：CSI + 环境麦

```bash
ssh "$PI4_SSH" "tmux new-session -d -s csi_${SESSION} /home/pi4/pilot/scripts/csi_launcher.sh ${SESSION} ${CSI_CHANNEL}"
ssh "$PI4_SSH" "tmux new-session -d -s env_${SESSION} 'cd ~/pilot/scripts && ./start_audio_env.sh --session ${SESSION} --duration ${DURATION}'"
```

> **注意**：pi4 用户家目录若为 `/home/pi4`，则 launcher 路径改为 `/home/pi4/pilot/scripts/csi_launcher.sh`，
> 若仍是 `/home/pi`，则与 pi3 相同。

### 5.4 启动 pi5：双 USB 个人麦

```bash
ssh "$PI5_SSH" "tmux new-session -d -s lav_$SESSION 'cd ~/pilot/scripts && ./start_audio_lav.sh --session $SESSION --card-a $CARD_A --card-b $CARD_B --duration $DURATION'"
```

### 5.5 启动 pi2：Tx 发流量

当前 smoke test 先用 `ping` 模式：

```bash
ssh "$PI2_SSH" "tmux new-session -d -s tx_$SESSION 'cd ~/pilot/scripts && ./start_tx.sh --session $SESSION --mode ping --target auto-gateway --interface wlan0 --duration $DURATION'"
```

如果你明确知道想打到哪个目标，也可以直接写 IP：

```bash
ssh "$PI2_SSH" "tmux new-session -d -s tx_$SESSION 'cd ~/pilot/scripts && ./start_tx.sh --session $SESSION --mode ping --target 10.10.10.10 --interface wlan0 --duration $DURATION'"
```

### 5.6 检查远端 tmux 是否真的启动

```bash
ssh "$PI2_SSH" 'tmux ls'
ssh "$PI3_SSH" 'tmux ls'
ssh "$PI4_SSH" 'tmux ls'
ssh "$PI5_SSH" 'tmux ls'
```

查看最近输出：

```bash
ssh "$PI2_SSH" "tmux capture-pane -pt tx_$SESSION | tail -n 20"
ssh "$PI3_SSH" "tmux capture-pane -pt csi_$SESSION | tail -n 20"
ssh "$PI3_SSH" "tmux capture-pane -pt env_$SESSION | tail -n 20"
ssh "$PI4_SSH" "tmux capture-pane -pt csi_$SESSION | tail -n 20"
ssh "$PI4_SSH" "tmux capture-pane -pt env_$SESSION | tail -n 20"
ssh "$PI5_SSH" "tmux capture-pane -pt lav_$SESSION | tail -n 20"
```

## 6. 停止录制

因为 `start_audio_env.sh`、`start_audio_lav.sh`、`start_tx.sh` 都带 `--duration`，它们通常会自己结束；`start_csi_rx.sh` 会持续抓包直到你显式 stop。

最简单的做法是在 Mac 上等待略长于 `DURATION` 的时间，然后只停止 CSI；为了稳妥，也可以把所有类型都 stop 一次。

例如等待 35 秒：

```bash
sleep $((DURATION + 5))
```

然后统一停止：

```bash
ssh "$PI3_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session $SESSION --kind csi"
ssh "$PI4_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session $SESSION --kind csi"

ssh "$PI2_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session $SESSION --kind tx"
ssh "$PI3_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session $SESSION --kind audio-env"
ssh "$PI4_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session $SESSION --kind audio-env"
ssh "$PI5_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session $SESSION --kind audio-lav"
```

如果 pid 文件丢了或任务异常挂住，用 fallback：

```bash
ssh "$PI3_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session $SESSION --kind csi --fallback"
ssh "$PI4_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session $SESSION --kind csi --fallback"
ssh "$PI5_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session $SESSION --kind audio-lav --fallback"
```

## 7. 从 Pi 拉回 raw data 和日志

在 Mac 上执行：

```bash
cd /Users/labahua/Desktop/CUHK-Y/pilot/scripts

./pull_session.sh --session "$SESSION" --include-logs \
  "$PI3_SSH" \
  "$PI4_SSH" \
  "$PI5_SSH"
```

如果你也想拉回 `pi2` 的流量日志，一起加上：

```bash
./pull_session.sh --session "$SESSION" --include-logs \
  "$PI2_SSH" \
  "$PI3_SSH" \
  "$PI4_SSH" \
  "$PI5_SSH"
```

拉回后的目录结构大致是：

```text
pilot/data/pulls/<SESSION>/
├── pi@192.168.2.2/
│   ├── logs/
│   └── raw/
├── pi@192.168.2.3/
│   ├── logs/
│   └── raw/
├── pi4@192.168.2.4/
│   ├── logs/
│   └── raw/
├── pi5@192.168.2.6/
│   ├── logs/
│   └── raw/
└── manifest.sha256
```

## 8. 快速确认录制结果

### 8.1 先看 Pi 本机有没有生成文件

```bash
ssh "$PI3_SSH" "find ~/pilot/data/raw -type f | sort | grep '$SESSION'"
ssh "$PI4_SSH" "find ~/pilot/data/raw -type f | sort | grep '$SESSION'"
ssh "$PI5_SSH" "find ~/pilot/data/raw -type f | sort | grep '$SESSION'"
```

### 8.2 再看 Mac 拉回后是否齐全

```bash
cd /Users/labahua/Desktop/CUHK-Y/pilot
find data/pulls/"$SESSION" -type f | sort
```

当前这轮完整 raw capture 最少应看到：

- `pi3`：一个 `pcap`，一个环境麦 `wav`
- `pi4`：一个 `pcap`，一个环境麦 `wav`
- `pi5`：两个个人麦 `wav`，通常为 `_lavA.wav` 和 `_lavB.wav`

### 8.3 拉回后做音频电平质检

文件存在不等于真的录到了有效声音。尤其对 `pi5` 的 lav 录音，最常见的问题不是脚本报错，而是生成了时长正确的 wav，但实际只有极低电平噪声。

在 Mac 上可以直接运行：

```bash
cd /Users/labahua/Desktop/CUHK-Y

/Users/labahua/Desktop/CUHK-Y/.venv/bin/python pilot/analysis/check_wav_levels.py \
  pilot/data/pulls/"$SESSION"/pi5@192.168.2.6/raw/audio/lav/
```

如果输出里 `likely_silent` 是 `true`，就说明文件格式和时长正常，但输入信号几乎没进声卡，应该优先排查麦克风、转接头、USB 声卡输入类型和录音增益，而不是先怀疑 pull 或 wav 写盘逻辑。

## 9. 常见问题

### 9.1 `start_csi_rx.sh` 只打印 Usage 就退出

最常见原因是 `--session` 值为空，例如：

```bash
./start_csi_rx.sh --session "$SESSION" --channel 11/20
```

但 `SESSION` 没有先赋值。

先检查：

```bash
echo "SESSION=<$SESSION>"
```

更稳妥的写法是直接写死一个名字做 smoke test：

```bash
./start_csi_rx.sh --session demo01 --channel 11/20
```

### 9.2 SSH 断了，录制会不会丢

如果你是按这份文档用 `tmux` 在 Pi 本地启动，SSH 断开通常不会导致采集进程退出。

### 9.4 `sudo tmux ls` 报 `no server running`，CSI 会话秒退

这个问题在调试过程中出现过多次，根因有三层，按概率排序：

**Bug 1（最常见）：SSH 双引号嵌套，命令在 Mac 侧就被截断**

错误写法：
```bash
ssh -tt pi@pi3 "USER_PILOT_ROOT=$HOME/pilot; sudo tmux ... \"$USER_PILOT_ROOT/scripts/...\""
```
`$USER_PILOT_ROOT` 在 Mac 侧展开时为空（或指向 Mac 路径），tmux 启动后立刻找不到脚本退出。

**修复**：改用 `csi_launcher.sh` 绝对路径，不再在 SSH 命令里嵌套引号：
```bash
ssh -tt pi@pi3 "sudo tmux new-session -d -s csi_SESSION /home/pi/pilot/scripts/csi_launcher.sh SESSION CHANNEL"
```

**Bug 2：root tmux 里 `$HOME` 变成 `/root`**

`sudo tmux` 启动的 pane 以 root 身份运行，`$HOME` 是 `/root`。
旧版 `start_csi_rx.sh` 从 `$HOME/nexmon/...` 查找 `makecsiparams` 和 `nexutil`，
在 root 环境下找不到，脚本立刻退出，日志停在 `Configuring CSI capture` 那一行。

**修复**：`start_csi_rx.sh` 已改为从脚本自身位置推导 Nexmon 路径（`PILOT_OWNER_HOME`），
不再依赖当前用户 `$HOME`。确保 Pi 端脚本已同步到最新版本。

**Bug 3：sudo 凭证不继承到 detached tmux**

即使在 SSH 会话里 `sudo -n true` 返回 `sudo_ok`，
daemon 模式的 tmux pane 使用的是不同 TTY，sudo ticket 可能失效。
用 `sudo tmux` 整体提权可以完全绕开这个问题。

**诊断步骤**：
```bash
# 1. 看日志，确认脚本运行到哪一步
ssh pi@192.168.2.3 "ls -1t /home/pi/pilot/logs/ | grep csi_SESSION | head -1"
ssh pi@192.168.2.3 "tail -n 50 \$(ls -1t /home/pi/pilot/logs/csi_SESSION*.log | head -1)"
# 2. 如果日志都不存在，说明脚本连启动都没到，是 Bug 1 或 Bug 2
# 3. 如果日志停在 Configuring，是 Bug 2 或 Bug 3
# 4. 如果有 STEP DONE: enable monitor mode 但没有 Writing CSI packets，是 nexutil 或 tcpdump 权限问题
```

### 9.5 为什么不建议让 Mac 直接前台挂着跑采集命令

因为你真正想要的是“Mac 远程控制，Pi 本地采集”，不是“Mac 代替 Pi 采集”。

不建议的方式：

- 在 Mac 上开一条 SSH 前台跑长时间抓包
- 让远端任务绑定在一个脆弱的 SSH 会话上
- 让远端录制数据实时写回 Mac

建议的方式就是本文现在这套：

- Mac 只负责 SSH 下发启动和停止命令
- Pi 本地写 raw data
- 结束后统一 pull 回来

## 10. 最短实战模板

如果你已经确认 SSH、tmux、声卡编号都没问题，最短的实战顺序就是：

```bash
cd /Users/labahua/Desktop/CUHK-Y

PI2_SSH="pi@192.168.2.2"
PI3_SSH="pi@192.168.2.3"
PI4_SSH="pi4@192.168.2.4"
PI5_SSH="pi5@192.168.2.6"

SESSION="room01_$(date +%Y%m%d_%H%M%S)"
DURATION=60
CSI_CHANNEL="11/20"
CARD_A=3
CARD_B=4

# 运行 setup_pilot.sh 后无需 sudo tmux 或 -tt
ssh "$PI3_SSH" "tmux new-session -d -s csi_${SESSION} /home/pi/pilot/scripts/csi_launcher.sh ${SESSION} ${CSI_CHANNEL}"
ssh "$PI3_SSH" "tmux new-session -d -s env_${SESSION} 'cd ~/pilot/scripts && ./start_audio_env.sh --session ${SESSION} --duration ${DURATION}'"

ssh "$PI4_SSH" "tmux new-session -d -s csi_${SESSION} /home/pi4/pilot/scripts/csi_launcher.sh ${SESSION} ${CSI_CHANNEL}"
ssh "$PI4_SSH" "tmux new-session -d -s env_${SESSION} 'cd ~/pilot/scripts && ./start_audio_env.sh --session ${SESSION} --duration ${DURATION}'"

ssh "$PI5_SSH" "tmux new-session -d -s lav_${SESSION} 'cd ~/pilot/scripts && ./start_audio_lav.sh --session ${SESSION} --card-a ${CARD_A} --card-b ${CARD_B} --duration ${DURATION}'"

ssh "$PI2_SSH" "tmux new-session -d -s tx_${SESSION} 'cd ~/pilot/scripts && ./start_tx.sh --session ${SESSION} --mode ping --target auto-gateway --interface wlan0 --duration ${DURATION}'"

sleep $((DURATION + 5))

ssh "$PI3_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session ${SESSION} --kind csi"
ssh "$PI4_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session ${SESSION} --kind csi"

cd /Users/labahua/Desktop/CUHK-Y/pilot/scripts
./pull_session.sh --session "$SESSION" --include-logs \
  "$PI2_SSH" \
  "$PI3_SSH" \
  "$PI4_SSH" \
  "$PI5_SSH"
```

## 11. 三节点降级流程

如果 `pi4` 当前还卡在 `start_csi_rx.sh` 的 `configure csi params` 阶段，你仍然可以先用 `pi2 + pi3 + pi5` 跑通一轮可用的 raw capture。

这条降级流程能完成的内容：

- `pi2`：Tx 发流量
- `pi3`：一份 CSI `pcap` + 一份环境麦 `wav`
- `pi5`：两份个人麦 `wav`
- Mac：统一 pull 回本地并生成 manifest

这条降级流程不能替代的内容：

- 缺少 `pi4` 的第二视角 CSI
- 缺少 `pi4` 的第二路环境音频
- 不能完成双接收点拓扑下的空间冗余和双点对照

也就是说，它可以完成“当前 runbook 的一轮可执行采集”，但不能等价替代原始 4 节点设计目标。

### 11.1 启动三节点采集

```bash
cd /Users/labahua/Desktop/CUHK-Y

PI2_SSH="pi@192.168.2.2"
PI3_SSH="pi@192.168.2.3"
PI5_SSH="pi5@192.168.2.6"

SESSION="room01_$(date +%Y%m%d_%H%M%S)"
DURATION=120
CSI_CHANNEL="11/20"
CARD_A=3
CARD_B=4

# 运行 setup_pilot.sh 后无需 sudo tmux 或 -tt
ssh "$PI3_SSH" "tmux new-session -d -s csi_${SESSION} /home/pi/pilot/scripts/csi_launcher.sh ${SESSION} ${CSI_CHANNEL}"
ssh "$PI3_SSH" "tmux new-session -d -s env_${SESSION} 'cd ~/pilot/scripts && ./start_audio_env.sh --session ${SESSION} --duration ${DURATION}'"

ssh "$PI5_SSH" "tmux new-session -d -s lav_${SESSION} 'cd ~/pilot/scripts && ./start_audio_lav.sh --session ${SESSION} --card-a ${CARD_A} --card-b ${CARD_B} --duration ${DURATION}'"

ssh "$PI2_SSH" "tmux new-session -d -s tx_${SESSION} 'cd ~/pilot/scripts && ./start_tx.sh --session ${SESSION} --mode ping --target auto-gateway --interface wlan0 --duration ${DURATION}'"
```

### 11.2 检查 CSI 是否真的在跑（启动后 5 秒执行）

```bash
ssh pi@192.168.2.3 "tmux ls 2>&1"
ssh pi@192.168.2.3 "ls -1t /home/pi/pilot/logs/ | grep csi_${SESSION} | head -1"
ssh pi@192.168.2.3 "tail -n 20 \$(ls -1t /home/pi/pilot/logs/csi_${SESSION}*.log 2>/dev/null | head -1)"
```

正常输出应包含 `Writing CSI packets to` 和 `tcpdump: listening on wlan0`。
如果 `tmux ls` 报 `no server running`，说明会话秒退，去看日志找退出原因。

### 11.3 停止三节点采集

```bash
#就是你录完等上三秒 其实也可以不等直接干就完
sleep $((DURATION + 3))

ssh "$PI3_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session ${SESSION} --kind csi"
ssh "$PI2_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session ${SESSION} --kind tx"
ssh "$PI3_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session ${SESSION} --kind audio-env"
ssh "$PI5_SSH" "cd ~/pilot/scripts && ./stop_capture.sh --session ${SESSION} --kind audio-lav"
```

### 11.4 先验证 Pi 本机文件，再 pull

```bash
# 先看 pi3 本地有没有 pcap，不要依赖 pull 来判断采集是否成功
ssh pi@192.168.2.3 "ls -lh /home/pi/pilot/data/raw/csi/${SESSION}.pcap 2>&1"
```

### 11.5 拉回三节点数据

```bash
cd /Users/labahua/Desktop/CUHK-Y/pilot/scripts

./pull_session.sh --session "$SESSION" --include-logs \
  "$PI2_SSH" \
  "$PI3_SSH" \
  "$PI5_SSH"
```

### 11.6 这一轮最少应该看到什么

- `pi3`：一个 `pcap`，一个环境麦 `wav`
- `pi5`：两个个人麦 `wav`
- `pi2`：一份 Tx 日志，若拉日志则会一并带回