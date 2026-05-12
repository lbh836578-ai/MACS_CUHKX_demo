#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage:
  start_audio_lav.sh --session SESSION [--card CARD_ID] [--duration 30]
                     [--outdir PATH] [--channels 2] [--rate 48000]
  start_audio_lav.sh --session SESSION --card-a CARD_ID --card-b CARD_ID
                     [--outdir PATH] [--duration 30] [--rate 48000]
                     [--channels-a 1] [--channels-b 1]

Single-device mode writes SESSION.wav.
Dual-device mode writes SESSION_lavA.wav and SESSION_lavB.wav.
If --card is omitted in single-device mode, the script tries to find a card matching usb or audio.
EOF
}

SESSION_NAME=""
CARD=""
CARD_A=""
CARD_B=""
DURATION="30"
CHANNELS="2"
CHANNELS_A="1"
CHANNELS_B="1"
RATE="48000"
FORMAT="S16_LE"
OUTDIR="$PILOT_ROOT/data/raw/audio/lav"
CHILD_PID=""
CHILD_PID_A=""
CHILD_PID_B=""

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
    --card-a)
      CARD_A="$2"
      shift 2
      ;;
    --card-b)
      CARD_B="$2"
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
    --channels-a)
      CHANNELS_A="$2"
      shift 2
      ;;
    --channels-b)
      CHANNELS_B="$2"
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

if [[ -n "$CARD" && ( -n "$CARD_A" || -n "$CARD_B" ) ]]; then
  echo "Use either --card or the --card-a/--card-b pair, not both." >&2
  exit 1
fi

if [[ -n "$CARD_A" || -n "$CARD_B" ]]; then
  if [[ -z "$CARD_A" || -z "$CARD_B" ]]; then
    echo "Dual-device mode requires both --card-a and --card-b." >&2
    exit 1
  fi
  if [[ "$CARD_A" == "$CARD_B" ]]; then
    echo "--card-a and --card-b must point to different capture devices." >&2
    exit 1
  fi
fi

prepare_log "audio_lav_${SESSION_NAME}_$(timestamp_utc).log"
write_pidfile "$SESSION_NAME" audio-lav

cleanup() {
  kill_child_if_running "$CHILD_PID"
  kill_child_if_running "$CHILD_PID_A"
  kill_child_if_running "$CHILD_PID_B"
  cleanup_pidfile "$SESSION_NAME" audio-lav
}
trap cleanup EXIT INT TERM

ensure_command arecord

if [[ -z "$CARD" && -z "$CARD_A" && -z "$CARD_B" ]]; then
  CARD="$(resolve_arecord_card 'usb|audio')"
fi

if [[ -z "$CARD" && -z "$CARD_A" && -z "$CARD_B" ]]; then
  log "Could not resolve a lavalier microphone card. Use --card explicitly."
  exit 1
fi

ensure_dir "$OUTDIR"
check_ntp_sync

wait_for_children() {
  local status=0
  local pid_value
  set +e
  for pid_value in "$@"; do
    wait "$pid_value"
    if [[ $? -ne 0 ]]; then
      status=1
    fi
  done
  set -e
  return "$status"
}

if [[ -n "$CARD_A" && -n "$CARD_B" ]]; then
  OUTFILE_A="$OUTDIR/${SESSION_NAME}_lavA.wav"
  OUTFILE_B="$OUTDIR/${SESSION_NAME}_lavB.wav"
  CMD_A=(arecord -D "plughw:${CARD_A},0" -c "$CHANNELS_A" -r "$RATE" -f "$FORMAT" -d "$DURATION" "$OUTFILE_A")
  CMD_B=(arecord -D "plughw:${CARD_B},0" -c "$CHANNELS_B" -r "$RATE" -f "$FORMAT" -d "$DURATION" "$OUTFILE_B")

  log "Recording lavalier audio with split mono devices"
  printf 'Command A: %q ' "${CMD_A[@]}"
  printf '\n'
  printf 'Command B: %q ' "${CMD_B[@]}"
  printf '\n'

  "${CMD_A[@]}" &
  CHILD_PID_A="$!"
  "${CMD_B[@]}" &
  CHILD_PID_B="$!"

  wait_for_children "$CHILD_PID_A" "$CHILD_PID_B"

  if command -v soxi >/dev/null 2>&1; then
    soxi "$OUTFILE_A" || true
    soxi "$OUTFILE_B" || true
  fi

  log "Lavalier split-device recording completed"
  exit 0
fi

OUTFILE="$OUTDIR/${SESSION_NAME}.wav"
CMD=(arecord -D "plughw:${CARD},0" -c "$CHANNELS" -r "$RATE" -f "$FORMAT" -d "$DURATION" "$OUTFILE")

log "Recording lavalier audio to $OUTFILE with card $CARD"
printf 'Command: %q ' "${CMD[@]}"
printf '\n'

"${CMD[@]}" &
CHILD_PID="$!"
wait_for_children "$CHILD_PID"

if command -v soxi >/dev/null 2>&1; then
  soxi "$OUTFILE" || true
fi

log "Lavalier audio recording completed"