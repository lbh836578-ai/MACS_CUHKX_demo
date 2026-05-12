#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage:
  stop_capture.sh [--session SESSION] [--kind tx|csi|audio-env|audio-lav|all] [--fallback]

The script first looks for pid files written by the pilot scripts.
If --fallback is set, it also issues broad pkill commands for known capture processes.
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
    PID_FILES=("$PID_DIR/${SESSION_NAME}.*.pid")
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

  if [[ "$pid_file" == *.csi.pid ]]; then
    sudo -n kill "$pid_value" >/dev/null 2>&1 || true
  fi
done

if [[ "$FALLBACK" == "true" ]]; then
  log "Fallback mode enabled"
  case "$KIND" in
    all|tx)
      pkill -f 'ping -I|iperf3 -u -c' >/dev/null 2>&1 || true
      ;;
  esac
  case "$KIND" in
    all|csi)
      sudo pkill -f 'tcpdump -ni .*udp dst port 5500' >/dev/null 2>&1 || true
      ;;
  esac
  case "$KIND" in
    all|audio-env|audio-lav)
      pkill arecord >/dev/null 2>&1 || true
      ;;
  esac
fi

if [[ "$FOUND_ANY" == "false" && "$FALLBACK" != "true" ]]; then
  log "No pid files matched the requested filters"
fi