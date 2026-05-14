#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage:
  host_start_6pi_session.sh [--session SESSION] [--duration 60]
                           [--channel 36/40] [--start-delay 10]
                           [--slot-ms 300] [--burst-count 120]
                           [--burst-interval 0.002]
                           [--tx-target auto-gateway]
                           [--tx-macs aa:bb:cc:dd:ee:ff,11:22:33:44:55:66,77:88:99:aa:bb:cc]
                           [--remote-root /home/pi/pilot_6pi_wifi]

Environment overrides:
  TX_A_SSH, TX_B_SSH, TX_C_SSH, RX_A_SSH, RX_B_SSH, RX_C_SSH
EOF
}

SESSION_NAME="sixpi_$(date +%Y%m%d_%H%M%S)"
DURATION="60"
CHANNEL="36/40"
START_DELAY_SEC="10"
SLOT_MS="300"
CYCLE_SLOTS="3"
BURST_COUNT="120"
BURST_INTERVAL="0.002"
TX_TARGET="auto-gateway"
TX_MACS=""
PACKETS=""
REMOTE_ROOT="/home/pi/pilot_6pi_wifi"

TX_A_SSH="${TX_A_SSH:-pi@10.0.50.11}"
TX_B_SSH="${TX_B_SSH:-pi@10.0.50.12}"
TX_C_SSH="${TX_C_SSH:-pi@10.0.50.13}"
RX_A_SSH="${RX_A_SSH:-pi@10.0.50.21}"
RX_B_SSH="${RX_B_SSH:-pi@10.0.50.22}"
RX_C_SSH="${RX_C_SSH:-pi@10.0.50.23}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      SESSION_NAME="$2"
      shift 2
      ;;
    --duration)
      DURATION="$2"
      shift 2
      ;;
    --channel)
      CHANNEL="$2"
      shift 2
      ;;
    --start-delay)
      START_DELAY_SEC="$2"
      shift 2
      ;;
    --slot-ms)
      SLOT_MS="$2"
      shift 2
      ;;
    --burst-count)
      BURST_COUNT="$2"
      shift 2
      ;;
    --burst-interval)
      BURST_INTERVAL="$2"
      shift 2
      ;;
    --tx-target)
      TX_TARGET="$2"
      shift 2
      ;;
    --tx-macs)
      TX_MACS="$2"
      shift 2
      ;;
    --packets)
      PACKETS="$2"
      shift 2
      ;;
    --remote-root)
      REMOTE_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

prepare_log "host_start_${SESSION_NAME}_$(timestamp_utc).log"
ensure_command ssh

START_EPOCH="$(( $(date +%s) + START_DELAY_SEC ))"
TX_HOSTS=("$TX_A_SSH" "$TX_B_SSH" "$TX_C_SSH")
RX_HOSTS=("$RX_A_SSH" "$RX_B_SSH" "$RX_C_SSH")

if [[ -z "$TX_MACS" ]]; then
  log "Warning: --tx-macs not set. Receivers will capture matching CSI on the configured channel without firmware-level MAC filtering."
fi

start_rx() {
  local host="$1"
  local remote_cmd="cd $REMOTE_ROOT/scripts && ./csi_launcher.sh $SESSION_NAME $CHANNEL"
  if [[ -n "$TX_MACS" ]]; then
    remote_cmd="$remote_cmd $TX_MACS"
  fi
  if [[ -n "$PACKETS" ]]; then
    remote_cmd="$remote_cmd $PACKETS"
  fi
  log "Starting Rx on $host"
  ssh "$host" "tmux new-session -d -s csi_${SESSION_NAME} '$remote_cmd'"
}

start_tx() {
  local host="$1"
  local slot_index="$2"
  local remote_cmd="cd $REMOTE_ROOT/scripts && ./start_tx_tdma.sh --session $SESSION_NAME --slot-index $slot_index --cycle-slots $CYCLE_SLOTS --slot-ms $SLOT_MS --start-epoch $START_EPOCH --duration $DURATION --interface wlan0 --target $TX_TARGET --burst-count $BURST_COUNT --burst-interval $BURST_INTERVAL"
  log "Starting Tx slot $slot_index on $host"
  ssh "$host" "tmux new-session -d -s tx_${SESSION_NAME} '$remote_cmd'"
}

for host in "${RX_HOSTS[@]}"; do
  start_rx "$host"
done

start_tx "$TX_A_SSH" 0
start_tx "$TX_B_SSH" 1
start_tx "$TX_C_SSH" 2

log "Shared start epoch: $START_EPOCH"
log "Verifying tmux sessions"
for host in "${TX_HOSTS[@]}" "${RX_HOSTS[@]}"; do
  ssh "$host" "tmux ls | grep '$SESSION_NAME' || true"
done

log "Session started: $SESSION_NAME"
