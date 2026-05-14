#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  check_csi_rate.sh FILE.pcap DURATION_SECONDS
EOF
}

if [[ $# -ne 2 ]]; then
  usage
  exit 1
fi

PCAP_PATH="$1"
DURATION_SECONDS="$2"

if [[ ! -f "$PCAP_PATH" ]]; then
  echo "pcap not found: $PCAP_PATH" >&2
  exit 1
fi

if ! command -v tcpdump >/dev/null 2>&1; then
  echo "Missing required command: tcpdump" >&2
  exit 1
fi

PACKET_COUNT="$(tcpdump -nn -r "$PCAP_PATH" 2>/dev/null | wc -l | awk '{print $1}')"
PPS="$(awk -v packets="$PACKET_COUNT" -v duration="$DURATION_SECONDS" 'BEGIN { if (duration <= 0) { print "0.0" } else { printf "%.1f", packets / duration } }')"

printf 'pcap=%s\n' "$PCAP_PATH"
printf 'packets=%s\n' "$PACKET_COUNT"
printf 'duration_seconds=%s\n' "$DURATION_SECONDS"
printf 'pps=%s\n' "$PPS"
