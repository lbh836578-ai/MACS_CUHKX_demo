#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage:
  start_csi_rx.sh --session SESSION [--channel 36/80] [--interface wlan0]
                  [--outdir PATH] [--packets 1000]

Notes:
  - Defaults assume nexmon_csi is installed at ~/nexmon/patches/bcm43455c0/7_45_189/nexmon_csi
  - tcpdump runs in the foreground until packet limit is reached or the process is stopped
EOF
}

require_option_value() {
  local option_name="$1"
  local option_value="${2-}"

  if [[ -z "$option_value" || "$option_value" == --* ]]; then
    echo "Missing value for $option_name" >&2
    usage
    exit 1
  fi
}

SESSION_NAME=""
CHANNEL="36/80"
INTERFACE="wlan0"
PACKETS=""
OUTDIR="$PILOT_ROOT/data/raw/csi"
PILOT_OWNER_HOME="$(cd "$PILOT_ROOT/.." && pwd)"
DEFAULT_NEXMON_ROOT="$PILOT_OWNER_HOME/nexmon"
NEXMON_CSI_DIR="${NEXMON_CSI_DIR:-$DEFAULT_NEXMON_ROOT/patches/bcm43455c0/7_45_189/nexmon_csi}"
MAKECSIPARAMS="$NEXMON_CSI_DIR/utils/makecsiparams/makecsiparams"
CHILD_PID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      require_option_value "$1" "${2-}"
      SESSION_NAME="$2"
      shift 2
      ;;
    --channel)
      require_option_value "$1" "${2-}"
      CHANNEL="$2"
      shift 2
      ;;
    --interface)
      require_option_value "$1" "${2-}"
      INTERFACE="$2"
      shift 2
      ;;
    --outdir)
      require_option_value "$1" "${2-}"
      OUTDIR="$2"
      shift 2
      ;;
    --packets)
      require_option_value "$1" "${2-}"
      PACKETS="$2"
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
  echo "Missing required non-empty --session value" >&2
  usage
  exit 1
fi

prepare_log "csi_${SESSION_NAME}_$(timestamp_utc).log"
write_pidfile "$SESSION_NAME" csi

cleanup() {
  kill_child_if_running "$CHILD_PID"
  cleanup_pidfile "$SESSION_NAME" csi
}
trap cleanup EXIT INT TERM

run_step() {
  local step_name="$1"
  shift

  log "STEP START: $step_name"
  "$@"
  log "STEP DONE: $step_name"
}

run_optional_step() {
  local step_name="$1"
  local timeout_seconds="${CSI_OPTIONAL_STEP_TIMEOUT_SEC:-3}"
  local status=0
  shift

  log "STEP START: $step_name"

  if ! command -v timeout >/dev/null 2>&1; then
    log "STEP SKIP: $step_name (timeout command unavailable)"
    return 0
  fi

  set +e
  timeout "$timeout_seconds" "$@"
  status=$?
  set -e

  if [[ "$status" -eq 0 ]]; then
    log "STEP DONE: $step_name"
    return 0
  fi

  if [[ "$status" -eq 124 ]]; then
    log "STEP TIMEOUT: $step_name"
    return 0
  fi

  log "STEP WARN: $step_name exited with status $status"
  return 0
}

bring_interface_up() {
  if command -v ip >/dev/null 2>&1; then
    sudo -n ip link set dev "$INTERFACE" up
    return
  fi

  if command -v ifconfig >/dev/null 2>&1; then
    sudo -n ifconfig "$INTERFACE" up
    return
  fi

  log "Missing required command: need either ip or ifconfig to bring up $INTERFACE"
  exit 1
}

resolve_nexutil() {
  local candidate

  if [[ -n "${NEXUTIL_BIN:-}" && -x "${NEXUTIL_BIN}" ]]; then
    printf '%s\n' "${NEXUTIL_BIN}"
    return
  fi

  if command -v nexutil >/dev/null 2>&1; then
    command -v nexutil
    return
  fi

  for candidate in \
    "$DEFAULT_NEXMON_ROOT/utilities/nexutil/nexutil" \
    "$NEXMON_CSI_DIR/../nexutil/nexutil" \
    "$DEFAULT_NEXMON_ROOT/patches/bcm43455c0/7_45_189/nexutil/nexutil" \
    "$HOME/nexmon/utilities/nexutil/nexutil" \
    "$HOME/nexmon/patches/bcm43455c0/7_45_189/nexutil/nexutil"
  do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  return 1
}

ensure_command sudo
ensure_command tcpdump

require_noninteractive_sudo() {
  if sudo -n true >/dev/null 2>&1; then
    return 0
  fi

  log "CSI capture requires sudo, but no non-interactive sudo credential is available"
  log "Run 'ssh -tt <host> \"sudo -v\"' immediately before starting tmux CSI capture, or configure limited NOPASSWD sudo for the required commands"
  exit 1
}

if [[ ! -x "$MAKECSIPARAMS" ]]; then
  log "makecsiparams not found: $MAKECSIPARAMS"
  exit 1
fi

NEXUTIL_BIN="$(resolve_nexutil || true)"
if [[ -z "$NEXUTIL_BIN" ]]; then
  log "Missing required command: nexutil (not found in PATH or standard Nexmon directories)"
  exit 1
fi

ensure_dir "$OUTDIR"
check_ntp_sync
require_noninteractive_sudo

cd "$NEXMON_CSI_DIR"
PARAMS="$("$MAKECSIPARAMS" -c "$CHANNEL" -C 1 -N 1)"

if [[ -z "$PARAMS" ]]; then
  log "makecsiparams returned an empty string for channel $CHANNEL"
  exit 1
fi

log "Configuring CSI capture on $INTERFACE with channel $CHANNEL"
run_step "nmcli managed no" sudo -n nmcli dev set "$INTERFACE" managed no || true
run_step "stop wpa_supplicant" sudo -n pkill wpa_supplicant || true
run_step "bring interface up" bring_interface_up
run_step "set channel" sudo -n "$NEXUTIL_BIN" -I"$INTERFACE" "-k$CHANNEL"
run_optional_step "query channel" sudo -n "$NEXUTIL_BIN" -I"$INTERFACE" -k
run_step "configure csi params" sudo -n "$NEXUTIL_BIN" -I"$INTERFACE" -s500 -b -l34 -v"$PARAMS"
run_step "enable monitor mode" sudo -n "$NEXUTIL_BIN" -I"$INTERFACE" -m1
run_optional_step "query monitor mode" sudo -n "$NEXUTIL_BIN" -m

OUTFILE="$OUTDIR/${SESSION_NAME}.pcap"
sudo -n rm -f "$OUTFILE"

CMD=(sudo -n tcpdump -ni "$INTERFACE" udp dst port 5500 -w "$OUTFILE")
if [[ -n "$PACKETS" ]]; then
  CMD+=( -c "$PACKETS" )
fi

log "Writing CSI packets to $OUTFILE"
printf 'Command: %q ' "${CMD[@]}"
printf '\n'

"${CMD[@]}" &
CHILD_PID="$!"
wait "$CHILD_PID"

log "CSI capture completed"