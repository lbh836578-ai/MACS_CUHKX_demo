#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage:
  start_tx_tdma.sh --session SESSION --slot-index 0|1|2 [--cycle-slots 3]
                   [--slot-ms 300] [--start-epoch UNIX_SECONDS]
                   [--duration 60] [--interface wlan0]
                   [--target auto-gateway] [--burst-count 120]
                   [--burst-interval 0.002]

Notes:
  - This script implements TDMA-style transmit bursts for one transmitter node.
  - All transmitters must share the same --start-epoch, --cycle-slots, and --slot-ms.
  - For high-rate ping bursts, the node needs passwordless sudo for /bin/ping or /usr/bin/ping.
EOF
}

SESSION_NAME=""
SLOT_INDEX=""
CYCLE_SLOTS="3"
SLOT_MS="300"
START_EPOCH="$(( $(date +%s) + 5 ))"
DURATION="60"
INTERFACE="wlan0"
TARGET="auto-gateway"
BURST_COUNT="120"
BURST_INTERVAL="0.002"
CHILD_PID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      SESSION_NAME="$2"
      shift 2
      ;;
    --slot-index)
      SLOT_INDEX="$2"
      shift 2
      ;;
    --cycle-slots)
      CYCLE_SLOTS="$2"
      shift 2
      ;;
    --slot-ms)
      SLOT_MS="$2"
      shift 2
      ;;
    --start-epoch)
      START_EPOCH="$2"
      shift 2
      ;;
    --duration)
      DURATION="$2"
      shift 2
      ;;
    --interface)
      INTERFACE="$2"
      shift 2
      ;;
    --target)
      TARGET="$2"
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

if [[ -z "$SESSION_NAME" || -z "$SLOT_INDEX" ]]; then
  usage
  exit 1
fi

if (( SLOT_INDEX < 0 || SLOT_INDEX >= CYCLE_SLOTS )); then
  echo "slot index must be in [0, cycle-slots)" >&2
  exit 1
fi

prepare_log "tx_${SESSION_NAME}_slot${SLOT_INDEX}_$(timestamp_utc).log"
write_pidfile "$SESSION_NAME" tx

cleanup() {
  kill_child_if_running "$CHILD_PID"
  cleanup_pidfile "$SESSION_NAME" tx
}
trap cleanup EXIT INT TERM

ensure_command ping
ensure_command sudo
ensure_command ip

check_ntp_sync

if [[ "$TARGET" == "auto-gateway" ]]; then
  TARGET="$(resolve_gateway "$INTERFACE")"
fi

if [[ -z "$TARGET" ]]; then
  log "Could not resolve target for interface $INTERFACE"
  exit 1
fi

if ! sudo -n ping -V >/dev/null 2>&1; then
  log "This script needs passwordless sudo for ping. Configure a restricted NOPASSWD sudoers entry on the transmitter node."
  exit 1
fi

START_MS=$(( START_EPOCH * 1000 ))
END_MS=$(( START_MS + DURATION * 1000 ))
EXPECTED_AVG_PPS="$(awk -v c="$BURST_COUNT" -v i="$BURST_INTERVAL" -v s="$CYCLE_SLOTS" 'BEGIN { printf "%.1f", c / (i * c * s) }')"

log "TDMA Tx configuration: session=$SESSION_NAME slot_index=$SLOT_INDEX cycle_slots=$CYCLE_SLOTS slot_ms=$SLOT_MS start_epoch=$START_EPOCH duration=$DURATION interface=$INTERFACE target=$TARGET burst_count=$BURST_COUNT burst_interval=$BURST_INTERVAL avg_pps_per_tx_approx=$EXPECTED_AVG_PPS"
log "Waiting for shared start epoch $START_EPOCH"
wait_until_epoch "$START_EPOCH"

ACTIVE_HITS=0
while true; do
  NOW_MS="$(epoch_ms)"
  if (( NOW_MS >= END_MS )); then
    break
  fi

  ELAPSED_MS=$(( NOW_MS - START_MS ))
  if (( ELAPSED_MS < 0 )); then
    sleep_ms 50
    continue
  fi

  SLOT_NUMBER=$(( ELAPSED_MS / SLOT_MS ))
  SLOT_POSITION=$(( SLOT_NUMBER % CYCLE_SLOTS ))
  NEXT_BOUNDARY_MS=$(( START_MS + (SLOT_NUMBER + 1) * SLOT_MS ))

  if (( SLOT_POSITION == SLOT_INDEX )); then
    ACTIVE_HITS=$(( ACTIVE_HITS + 1 ))
    if (( ACTIVE_HITS == 1 || ACTIVE_HITS % 10 == 0 )); then
      log "Active slot hit $ACTIVE_HITS at cycle_slot=$SLOT_POSITION"
    fi

    CMD=(sudo -n ping -n -q -I "$INTERFACE" -i "$BURST_INTERVAL" -c "$BURST_COUNT" "$TARGET")
    "${CMD[@]}" &
    CHILD_PID="$!"
    if ! wait "$CHILD_PID"; then
      log "Warning: ping burst exited with non-zero status on slot hit $ACTIVE_HITS"
    fi
    CHILD_PID=""
  fi

  NOW_MS="$(epoch_ms)"
  sleep_ms $(( NEXT_BOUNDARY_MS - NOW_MS ))
done

log "TDMA Tx completed after $ACTIVE_HITS active slots"
