#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage:
  host_prepare_6pi.sh [--remote-root /home/pi/pilot_6pi_wifi]

Environment overrides:
  TX_A_SSH, TX_B_SSH, TX_C_SSH, RX_A_SSH, RX_B_SSH, RX_C_SSH
EOF
}

REMOTE_ROOT="/home/pi/pilot_6pi_wifi"
TX_A_SSH="${TX_A_SSH:-pi@10.0.50.11}"
TX_B_SSH="${TX_B_SSH:-pi@10.0.50.12}"
TX_C_SSH="${TX_C_SSH:-pi@10.0.50.13}"
RX_A_SSH="${RX_A_SSH:-pi@10.0.50.21}"
RX_B_SSH="${RX_B_SSH:-pi@10.0.50.22}"
RX_C_SSH="${RX_C_SSH:-pi@10.0.50.23}"

while [[ $# -gt 0 ]]; do
  case "$1" in
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

ALL_HOSTS=("$TX_A_SSH" "$TX_B_SSH" "$TX_C_SSH" "$RX_A_SSH" "$RX_B_SSH" "$RX_C_SSH")

prepare_log "host_prepare_6pi_$(timestamp_utc).log"
ensure_command ssh
ensure_command rsync

for host in "${ALL_HOSTS[@]}"; do
  log "Preparing remote root on $host"
  ssh "$host" "mkdir -p $REMOTE_ROOT"

  rsync -av --delete \
    --exclude '.DS_Store' \
    --exclude '__pycache__/' \
    --exclude 'data/raw/' \
    --exclude 'data/pulls/' \
    --exclude 'logs/' \
    "$PILOT_ROOT/" \
    "$host:$REMOTE_ROOT/"

  ssh "$host" "chmod +x $REMOTE_ROOT/scripts/*.sh && bash -n $REMOTE_ROOT/scripts/*.sh"
done

log "6Pi Wi-Fi folder synced to all nodes"
