#!/usr/bin/env bash
set -euo pipefail

PILOT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PILOT_ROOT/logs"
PID_DIR="$LOG_DIR/pids"

ensure_dir() {
  mkdir -p "$1"
}

ensure_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 1
  fi
}

timestamp_utc() {
  date -u +"%Y%m%dT%H%M%SZ"
}

log() {
  printf '[%s] %s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$*"
}

prepare_log() {
  local file_name="$1"
  ensure_dir "$LOG_DIR"
  ensure_dir "$PID_DIR"
  if command -v stdbuf >/dev/null 2>&1; then
    exec > >(stdbuf -oL -eL tee -a "$LOG_DIR/$file_name") 2>&1
  else
    exec > >(tee -a "$LOG_DIR/$file_name") 2>&1
  fi
  log "Logging to $LOG_DIR/$file_name"
}

pidfile_path() {
  local session_name="$1"
  local kind="$2"
  printf '%s/%s.%s.pid\n' "$PID_DIR" "$session_name" "$kind"
}

write_pidfile() {
  local session_name="$1"
  local kind="$2"
  printf '%s\n' "$$" > "$(pidfile_path "$session_name" "$kind")"
}

cleanup_pidfile() {
  local session_name="$1"
  local kind="$2"
  local file_path
  file_path="$(pidfile_path "$session_name" "$kind")"
  if [[ -f "$file_path" ]]; then
    rm -f "$file_path"
  fi
}

check_ntp_sync() {
  if command -v timedatectl >/dev/null 2>&1; then
    local synced
    synced="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
    if [[ "$synced" == "yes" || "$synced" == "1" ]]; then
      log "NTP status: synchronized"
    else
      log "Warning: system clock is not synchronized yet"
    fi
  fi

  if command -v chronyc >/dev/null 2>&1; then
    chronyc tracking || true
  fi
}

resolve_gateway() {
  local interface_name="$1"
  ip route show default dev "$interface_name" | awk 'NR == 1 { print $3 }'
}

resolve_arecord_card() {
  local pattern="$1"
  arecord -l | awk -v pattern="$pattern" '
    BEGIN {
      IGNORECASE = 1
    }
    /^card [0-9]+:/ {
      line = tolower($0)
      wanted = tolower(pattern)
      if (line ~ wanted) {
        gsub(":", "", $2)
        print $2
        exit
      }
    }
  '
}

kill_child_if_running() {
  local child_pid="$1"
  if [[ -n "$child_pid" ]] && kill -0 "$child_pid" >/dev/null 2>&1; then
    kill "$child_pid" >/dev/null 2>&1 || true
  fi
}