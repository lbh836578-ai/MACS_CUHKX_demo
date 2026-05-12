#!/usr/bin/env bash
# Thin launcher for start_csi_rx.sh that accepts positional args.
# Usage: csi_launcher.sh SESSION CHANNEL [PACKETS]
# This wrapper exists so the tmux command line stays simple and quote-free.
set -euo pipefail

SESSION="$1"
CHANNEL="$2"
PACKETS="${3:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ARGS=(--session "$SESSION" --channel "$CHANNEL")
[[ -n "$PACKETS" ]] && ARGS+=(--packets "$PACKETS")

exec "$SCRIPT_DIR/start_csi_rx.sh" "${ARGS[@]}"
