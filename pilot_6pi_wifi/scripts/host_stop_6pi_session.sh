#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage:
  host_stop_6pi_session.sh --session SESSION [--remote-root /home/pi/pilot_6pi_wifi]

Environment overrides:
  TX_A_SSH, TX_B_SSH, TX_C_SSH, RX_A_SSH, RX_B_SSH, RX_C_SSH
EOF
}

SESSION_NAME=""
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

if [[ -z "$SESSION_NAME" ]]; then
  usage
  exit 1
fi

prepare_log "host_stop_${SESSION_NAME}_$(timestamp_utc).log"
ensure_command ssh

TX_HOSTS=("$TX_A_SSH" "$TX_B_SSH" "$TX_C_SSH")
RX_HOSTS=("$RX_A_SSH" "$RX_B_SSH" "$RX_C_SSH")

for host in "${RX_HOSTS[@]}"; do
  log "Stopping CSI on $host"
  ssh "$host" "cd $REMOTE_ROOT/scripts && ./stop_capture.sh --session $SESSION_NAME --kind csi --fallback && tmux kill-session -t csi_${SESSION_NAME} >/dev/null 2>&1 || true"
done

for host in "${TX_HOSTS[@]}"; do
  log "Stopping TDMA Tx on $host"
  ssh "$host" "cd $REMOTE_ROOT/scripts && ./stop_capture.sh --session $SESSION_NAME --kind tx --fallback && tmux kill-session -t tx_${SESSION_NAME} >/dev/null 2>&1 || true"
done

log "Session stopped: $SESSION_NAME"
