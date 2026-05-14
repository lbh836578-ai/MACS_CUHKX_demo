#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║  setup_6pi_bootstrap.sh                                          ║
# ║  从 Mac 控制主机一键引导全部 6 台 Pi 5：                          ║
# ║  执行 Runbook §6.2（安装依赖包）+ §8（Nexmon + nexmon_csi）       ║
# ║                                                                  ║
# ║  SECURITY: 此脚本含有明文密码，仅适用于隔离研究内网。             ║
# ║  chmod 700 本文件，不要提交到任何共享仓库。                       ║
# ╚══════════════════════════════════════════════════════════════════╝
set -euo pipefail

# ── 节点定义：label:user@ip:password ─────────────────────────────────────────
NODES=(
  "pi5-1:pi5-1@192.168.2.7:raspberrypi5-1"
  "pi5-2:pi5-2@192.168.2.10:raspberrypi5-2"
  "pi5-3:pi5-3@192.168.2.13:raspberrypi5-3"
  "pi5-4:pi5-4@192.168.2.14:raspberrypi5-4"
  "pi5-5:pi5-5@192.168.2.12:raspberrypi5-5"
  "pi5-6:pi5-6@192.168.2.11:raspberrypi5-6"
)

SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o ServerAliveInterval=30 -o BatchMode=no"

# ── 前置检查 ──────────────────────────────────────────────────────────────────
if ! command -v sshpass >/dev/null 2>&1; then
  printf '\nERROR: sshpass not found.\n'
  printf '  Install (macOS): brew install hudochenkov/sshpass/sshpass\n\n'
  exit 1
fi

# ── 远端引导脚本（单引号 HEREDOC：Mac 侧不展开任何变量）─────────────────────
# $(uname -r)、$HOME 等均在 Pi 侧运行时展开，行为正确。
read -r -d '' REMOTE_SCRIPT << 'REMOTE_EOF' || true
#!/usr/bin/env bash
set -euo pipefail

LOGFILE="$HOME/bootstrap_$(hostname)_$(date +%Y%m%dT%H%M%S).log"
exec > >(tee -a "$LOGFILE") 2>&1

echo "[$(date)] ── Bootstrap 开始: $(hostname) 内核=$(uname -r) ──"

# ── §6.2 安装系统依赖 ──────────────────────────────────────────────────────────
echo "[$(date)] §6.2 apt update + upgrade"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

echo "[$(date)] §6.2 安装编译与 CSI 依赖"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  git gawk qpdf bison flex make xxd automake autoconf libtool texinfo \
  tcpdump iw wireless-tools net-tools pkg-config \
  libnl-3-dev libnl-genl-3-dev libcap2-bin \
  chrony tmux rsync python3-pip python3-venv \
  raspberrypi-kernel-headers

echo "[$(date)] §6.2 设置时区"
sudo timedatectl set-timezone Asia/Hong_Kong

# ── §8.1 克隆 nexmon ───────────────────────────────────────────────────────────
echo "[$(date)] §8.1 克隆 nexmon"
cd "$HOME"
if [[ ! -d nexmon ]]; then
  git clone https://github.com/seemoo-lab/nexmon.git
else
  echo "  nexmon 目录已存在，跳过克隆"
fi

# ── §8.2 构建 nexmon buildtools ────────────────────────────────────────────────
echo "[$(date)] §8.2 source setup_env.sh + make buildtools"
cd "$HOME/nexmon"
# shellcheck disable=SC1091
source setup_env.sh

# b43/assembler 对 bcm43455c0 (Pi 5) 非必要；即使失败也继续。
# 安装 bison 后通常全部成功，|| true 作为保险。
make 2>&1 | tail -30 || {
  echo "[WARN] make buildtools 出现错误（b43/assembler 对 Pi 5 非致命，继续执行）"
}

# ── §8.3 构建并安装 nexutil ────────────────────────────────────────────────────
echo "[$(date)] §8.3 构建 nexutil (USE_VENDOR_CMD=1)"
cd "$HOME/nexmon/utilities/nexutil"
make USE_VENDOR_CMD=1
sudo make install USE_VENDOR_CMD=1
sudo setcap cap_net_admin+ep /usr/bin/nexutil
echo "  nexutil 版本: $(nexutil --version 2>&1 || echo '（版本查询失败，但二进制已安装）')"

# ── §8.4 克隆 nexmon_csi ───────────────────────────────────────────────────────
echo "[$(date)] §8.4 克隆 nexmon_csi"
CSI_DIR="$HOME/nexmon/patches/bcm43455c0/7_45_189"
mkdir -p "$CSI_DIR"
cd "$CSI_DIR"
if [[ ! -d nexmon_csi ]]; then
  git clone https://github.com/seemoo-lab/nexmon_csi.git
else
  echo "  nexmon_csi 目录已存在，跳过克隆"
fi

# ── §8.5 安装固件 + 重载驱动 ──────────────────────────────────────────────────
echo "[$(date)] §8.5 make install-firmware"
cd "$CSI_DIR/nexmon_csi"
make -f Makefile.rpi install-firmware

echo "[$(date)] §8.5 make reload-full（重载 brcmfmac）"
make -f Makefile.rpi reload-full

echo ""
echo "[$(date)] ── Bootstrap 完成: $(hostname) ──"
touch "$HOME/bootstrap_done.flag"
REMOTE_EOF

# ── 逐台节点部署 ─────────────────────────────────────────────────────────────
FAILED_NODES=()

for node_info in "${NODES[@]}"; do
  IFS=':' read -r label ssh_target password <<< "$node_info"
  username="${ssh_target%%@*}"

  echo ""
  printf '═%.0s' {1..58}; echo ""
  printf '  节点: %-8s  (%s)\n' "$label" "$ssh_target"
  printf '═%.0s' {1..58}; echo ""

  # ── 1/3 配置临时 NOPASSWD sudo（让引导脚本免密执行 sudo） ─────────────────
  echo "  [1/3] 配置临时 NOPASSWD sudo for $username"
  SUDOERS_LINE="$username ALL=(ALL) NOPASSWD: ALL"
  if sshpass -p "$password" ssh $SSH_OPTS "$ssh_target" \
    "echo '$password' | sudo -S bash -c 'echo \"$SUDOERS_LINE\" > /etc/sudoers.d/99-bootstrap-tmp && chmod 440 /etc/sudoers.d/99-bootstrap-tmp'" 2>&1; then
    echo "  NOPASSWD sudo 配置完成"
  else
    echo "  [WARN] NOPASSWD sudo 配置失败 — sudo 提示可能会阻塞构建"
    FAILED_NODES+=("$label:nopasswd_failed")
  fi

  # ── 2/3 推送引导脚本 ──────────────────────────────────────────────────────
  echo "  [2/3] 推送引导脚本到 ~/bootstrap_6pi.sh"
  printf '%s\n' "$REMOTE_SCRIPT" | sshpass -p "$password" ssh $SSH_OPTS "$ssh_target" \
    'cat > ~/bootstrap_6pi.sh && chmod +x ~/bootstrap_6pi.sh'
  echo "  脚本已推送"

  # ── 3/3 在 tmux 里后台启动（断线不丢失） ─────────────────────────────────
  echo "  [3/3] 启动 tmux 会话 'bootstrap'"
  sshpass -p "$password" ssh $SSH_OPTS "$ssh_target" \
    'rm -f ~/bootstrap_done.flag; tmux kill-session -t bootstrap 2>/dev/null || true; tmux new-session -d -s bootstrap "bash ~/bootstrap_6pi.sh"'
  echo "  已在后台启动（tmux session: bootstrap）"
done

# ── 输出监控命令 ──────────────────────────────────────────────────────────────
echo ""
printf '═%.0s' {1..58}; echo ""
echo "  全部 6 台节点已在后台引导（预计 15–30 分钟/台）"
echo ""
echo "  实时日志（附加到 tmux）："
for node_info in "${NODES[@]}"; do
  IFS=':' read -r label ssh_target password <<< "$node_info"
  printf "    sshpass -p '%s' ssh %s 'tmux attach -t bootstrap'  # %s\n" \
    "$password" "$ssh_target" "$label"
done

echo ""
echo "  查看当前进度（tail 日志最后 30 行）："
for node_info in "${NODES[@]}"; do
  IFS=':' read -r label ssh_target password <<< "$node_info"
  printf "    sshpass -p '%s' ssh %s 'tail -30 \$(ls -1t ~/bootstrap_*.log | head -1)'  # %s\n" \
    "$password" "$ssh_target" "$label"
done

echo ""
echo "  批量确认是否全部完成："
echo "  ──"
for node_info in "${NODES[@]}"; do
  IFS=':' read -r label ssh_target password <<< "$node_info"
  printf "    sshpass -p '%s' ssh %s 'ls ~/bootstrap_done.flag 2>/dev/null && echo DONE || echo RUNNING'  # %s\n" \
    "$password" "$ssh_target" "$label"
done
printf '═%.0s' {1..58}; echo ""

if [[ ${#FAILED_NODES[@]} -gt 0 ]]; then
  echo ""
  echo "  [WARN] 以下节点部署时出现警告："
  for item in "${FAILED_NODES[@]}"; do
    echo "    $item"
  done
fi
