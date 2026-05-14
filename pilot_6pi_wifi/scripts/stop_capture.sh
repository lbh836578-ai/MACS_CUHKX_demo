#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage:
  stop_capture.sh [--session SESSION] [--kind tx|csi|all] [--fallback]

The script first looks for pid files written by the 6Pi Wi-Fi scripts.
If --fallback is set, it also issues broader pkill commands for known CSI and Tx processes.
EOF
}

SESSION_NAME=""
KIND="all"
FALLBACK="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      SESSION_NAME="$2"
      shift 2
      ;;
    --kind)
      KIND="$2"
      shift 2
      ;;
    --fallback)
      FALLBACK="true"
      shift
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

prepare_log "stop_capture_$(timestamp_utc).log"
ensure_dir "$PID_DIR"

shopt -s nullglob
PID_FILES=()

if [[ -n "$SESSION_NAME" ]]; then
  if [[ "$KIND" == "all" ]]; then
    PID_FILES=("$PID_DIR/${SESSION_NAME}."*.pid)
  else
    PID_FILES=("$PID_DIR/${SESSION_NAME}.${KIND}.pid")
  fi
else
  if [[ "$KIND" == "all" ]]; then
    PID_FILES=("$PID_DIR"/*.pid)
  else
    PID_FILES=("$PID_DIR"/*."$KIND".pid)
  fi
fi

FOUND_ANY="false"
for pid_file in "${PID_FILES[@]}"; do
  [[ -f "$pid_file" ]] || continue
  FOUND_ANY="true"
  pid_value="$(cat "$pid_file")"
  log "Stopping pid $pid_value from $pid_file"
  if kill "$pid_value" >/dev/null 2>&1; then
    continue
  fi

  sudo -n kill "$pid_value" >/dev/null 2>&1 || true
done

if [[ "$FALLBACK" == "true" ]]; then
  log "Fallback mode enabled"
  case "$KIND" in
    all|tx)
      pkill -f 'start_tx_tdma.sh|ping -n -q -I|iperf3 -u -c' >/dev/null 2>&1 || true
      sudo -n pkill -f 'ping -n -q -I|iperf3 -u -c' >/dev/null 2>&1 || true
      ;;
  esac
  case "$KIND" in
    all|csi)
      sudo -n pkill -f 'tcpdump -ni .*udp dst port 5500' >/dev/null 2>&1 || true
      ;;
  esac
fi

if [[ "$FOUND_ANY" == "false" && "$FALLBACK" != "true" ]]; then
  log "No pid files matched the requested filters"
fi
