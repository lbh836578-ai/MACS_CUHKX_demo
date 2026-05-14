#!/usr/bin/env bash
# Thin launcher for start_csi_rx.sh that accepts positional args.
# Usage: csi_launcher.sh SESSION CHANNEL [SRC_MACS] [PACKETS]
set -euo pipefail

SESSION="$1"
CHANNEL="$2"
SRC_MACS="${3:-}"
PACKETS="${4:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ARGS=(--session "$SESSION" --channel "$CHANNEL")
[[ -n "$SRC_MACS" ]] && ARGS+=(--src-macs "$SRC_MACS")
[[ -n "$PACKETS" ]] && ARGS+=(--packets "$PACKETS")

exec "$SCRIPT_DIR/start_csi_rx.sh" "${ARGS[@]}"
