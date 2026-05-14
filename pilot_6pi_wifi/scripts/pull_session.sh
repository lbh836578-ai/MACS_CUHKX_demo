#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage:
  pull_session.sh --session SESSION [--remote-root /home/pi/pilot_6pi_wifi]
                  [--local-root PATH] [--include-logs] host1 [host2 ...]
EOF
}

remote_dir_exists() {
  local host="$1"
  local remote_dir="$2"
  ssh "$host" "test -d $remote_dir" >/dev/null 2>&1
}

SESSION_NAME=""
REMOTE_ROOT="/home/pi/pilot_6pi_wifi"
LOCAL_ROOT="$PILOT_ROOT/data/pulls"
INCLUDE_LOGS="false"
HOSTS=()

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
    --local-root)
      LOCAL_ROOT="$2"
      shift 2
      ;;
    --include-logs)
      INCLUDE_LOGS="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      HOSTS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$SESSION_NAME" || ${#HOSTS[@]} -eq 0 ]]; then
  usage
  exit 1
fi

prepare_log "pull_${SESSION_NAME}_$(timestamp_utc).log"

ensure_command rsync
ensure_command ssh
ensure_command shasum

SESSION_DIR="$LOCAL_ROOT/$SESSION_NAME"
ensure_dir "$SESSION_DIR"

for host in "${HOSTS[@]}"; do
  DEST_ROOT="$SESSION_DIR/$host"
  ensure_dir "$DEST_ROOT"
  if remote_dir_exists "$host" "$REMOTE_ROOT/data/raw"; then
    log "Pulling raw data from $host"

    rsync -av --prune-empty-dirs \
      --include='*/' \
      --include="*${SESSION_NAME}*" \
      --exclude='*' \
      "$host:$REMOTE_ROOT/data/raw/" \
      "$DEST_ROOT/raw/"
  else
    log "Skipping raw data pull from $host: $REMOTE_ROOT/data/raw does not exist"
  fi

  if [[ "$INCLUDE_LOGS" == "true" ]]; then
    if remote_dir_exists "$host" "$REMOTE_ROOT/logs"; then
      log "Pulling logs from $host"
      rsync -av --prune-empty-dirs \
        --include='*/' \
        --include="*${SESSION_NAME}*" \
        --exclude='*' \
        "$host:$REMOTE_ROOT/logs/" \
        "$DEST_ROOT/logs/"
    else
      log "Skipping log pull from $host: $REMOTE_ROOT/logs does not exist"
    fi
  fi
done

MANIFEST_PATH="$SESSION_DIR/manifest.sha256"
find "$SESSION_DIR" -type f ! -name 'manifest.sha256' -print0 | sort -z | while IFS= read -r -d '' file_path; do
  shasum -a 256 "$file_path"
done > "$MANIFEST_PATH"

log "Wrote manifest to $MANIFEST_PATH"
