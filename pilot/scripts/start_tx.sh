#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage:
  start_tx.sh --session SESSION [--mode ping|iperf3] [--target TARGET]
              [--interface wlan0] [--interval 0.02] [--duration 600]
              [--bandwidth 20M] [--length 1470]

Examples:
  start_tx.sh --session csi_single_walk_01 --mode ping --target auto-gateway
  start_tx.sh --session csi_dual_D1_01 --mode iperf3 --target 10.0.50.10 --duration 600
EOF
}

SESSION_NAME=""
MODE="ping"
TARGET="auto-gateway"
INTERFACE="wlan0"
INTERVAL="0.02"
DURATION="600"
BANDWIDTH="20M"
LENGTH="1470"
CHILD_PID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      SESSION_NAME="$2"
      shift 2
      ;;
    --mode)
      MODE="$2"
      shift 2
      ;;
    --target)
      TARGET="$2"
      shift 2
      ;;
    --interface)
      INTERFACE="$2"
      shift 2
      ;;
    --interval)
      INTERVAL="$2"
      shift 2
      ;;
    --duration)
      DURATION="$2"
      shift 2
      ;;
    --bandwidth)
      BANDWIDTH="$2"
      shift 2
      ;;
    --length)
      LENGTH="$2"
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

prepare_log "tx_${SESSION_NAME}_$(timestamp_utc).log"
write_pidfile "$SESSION_NAME" tx

cleanup() {
  kill_child_if_running "$CHILD_PID"
  cleanup_pidfile "$SESSION_NAME" tx
}
trap cleanup EXIT INT TERM

ensure_command ip
ensure_command ping

if [[ "$MODE" == "iperf3" ]]; then
  ensure_command iperf3
fi

check_ntp_sync

if [[ "$TARGET" == "auto-gateway" ]]; then
  TARGET="$(resolve_gateway "$INTERFACE")"
fi

if [[ -z "$TARGET" ]]; then
  log "Could not resolve a target for interface $INTERFACE"
  exit 1
fi

log "Starting traffic source: mode=$MODE interface=$INTERFACE target=$TARGET"

case "$MODE" in
  ping)
    CMD=(ping -I "$INTERFACE" -i "$INTERVAL")
    if [[ "$DURATION" != "0" ]]; then
      CMD+=( -w "$DURATION" )
    fi
    CMD+=( "$TARGET" )
    ;;
  iperf3)
    CMD=(iperf3 -u -c "$TARGET" -b "$BANDWIDTH" -l "$LENGTH" -t "$DURATION")
    ;;
  *)
    log "Unsupported mode: $MODE"
    exit 1
    ;;
esac

printf 'Command: %q ' "${CMD[@]}"
printf '\n'

"${CMD[@]}" &
CHILD_PID="$!"
wait "$CHILD_PID"

log "Traffic source completed"