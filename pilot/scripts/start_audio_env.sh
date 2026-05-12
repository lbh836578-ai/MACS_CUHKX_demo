#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage:
  start_audio_env.sh --session SESSION [--card CARD_ID] [--duration 30]
                     [--outdir PATH] [--channels 2] [--rate 48000]

If --card is omitted, the script tries to find a card matching seeed or respeaker.
EOF
}

SESSION_NAME=""
CARD=""
DURATION="30"
CHANNELS="2"
RATE="48000"
FORMAT="S16_LE"
OUTDIR="$PILOT_ROOT/data/raw/audio/env"
CHILD_PID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      SESSION_NAME="$2"
      shift 2
      ;;
    --card)
      CARD="$2"
      shift 2
      ;;
    --duration)
      DURATION="$2"
      shift 2
      ;;
    --channels)
      CHANNELS="$2"
      shift 2
      ;;
    --rate)
      RATE="$2"
      shift 2
      ;;
    --outdir)
      OUTDIR="$2"
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

prepare_log "audio_env_${SESSION_NAME}_$(timestamp_utc).log"
write_pidfile "$SESSION_NAME" audio-env

cleanup() {
  kill_child_if_running "$CHILD_PID"
  cleanup_pidfile "$SESSION_NAME" audio-env
}
trap cleanup EXIT INT TERM

ensure_command arecord

if [[ -z "$CARD" ]]; then
  CARD="$(resolve_arecord_card 'seeed|respeaker')"
fi

if [[ -z "$CARD" ]]; then
  log "Could not resolve an environment microphone card. Use --card explicitly."
  exit 1
fi

ensure_dir "$OUTDIR"
check_ntp_sync

OUTFILE="$OUTDIR/${SESSION_NAME}.wav"
CMD=(arecord -D "plughw:${CARD},0" -c "$CHANNELS" -r "$RATE" -f "$FORMAT" -d "$DURATION" "$OUTFILE")

log "Recording environment audio to $OUTFILE with card $CARD using $CHANNELS channel(s)"
printf 'Command: %q ' "${CMD[@]}"
printf '\n'

"${CMD[@]}" &
CHILD_PID="$!"
wait "$CHILD_PID"

if command -v soxi >/dev/null 2>&1; then
  soxi "$OUTFILE" || true
fi

log "Environment audio recording completed"