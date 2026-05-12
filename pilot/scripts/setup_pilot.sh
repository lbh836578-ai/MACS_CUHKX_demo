#!/usr/bin/env bash
# setup_pilot.sh
# One-time setup: SSH key distribution + NOPASSWD sudoers for pilot capture nodes.
# Run from Mac. Each Pi's password is required once; never again after.
#
# After this script succeeds:
#   - All ssh / rsync commands work without password prompts
#   - CSI sudo commands (nexutil, tcpdump, nmcli, ip …) work non-interactively
#   - Capture scripts no longer need 'sudo tmux' or 'ssh -tt'

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
PI2_SSH="pi@192.168.2.2"
PI3_SSH="pi@192.168.2.3"
PI4_SSH="pi4@192.168.2.4"
PI5_SSH="pi5@192.168.2.6"

ALL_HOSTS=("$PI2_SSH" "$PI3_SSH" "$PI4_SSH" "$PI5_SSH")

# CSI nodes: "ssh_target:home_dir:username:sudo_password"
CSI_NODES=(
  "pi@192.168.2.3:/home/pi:pi:raspberry"
  "pi4@192.168.2.4:/home/pi4:pi4:raspberrypi4"
)

SSH_KEY="$HOME/.ssh/id_pilot"
SSH_CONFIG="$HOME/.ssh/config"

# ── Helper ────────────────────────────────────────────────────────────────────
log() { printf '\n[setup] %s\n' "$*"; }

# ── Step 1: Generate SSH key ──────────────────────────────────────────────────
log "Step 1: SSH key"
if [[ -f "$SSH_KEY" ]]; then
  echo "  Key already exists: $SSH_KEY"
else
  ssh-keygen -t ed25519 -f "$SSH_KEY" -N "" -C "cuhk-y-pilot"
  echo "  Generated: $SSH_KEY"
fi

# ── Step 2: Add subnet rule to ~/.ssh/config ──────────────────────────────────
log "Step 2: ~/.ssh/config"
touch "$SSH_CONFIG"
chmod 600 "$SSH_CONFIG"

if grep -q "Host 192\.168\.2\.\*" "$SSH_CONFIG" 2>/dev/null; then
  echo "  Subnet rule already present, skipping."
else
  cat >> "$SSH_CONFIG" <<'EOF'

# cuhk-y pilot nodes (added by setup_pilot.sh)
Host 192.168.2.*
  IdentityFile ~/.ssh/id_pilot
  StrictHostKeyChecking accept-new
  ServerAliveInterval 30
EOF
  echo "  Added 192.168.2.* rule."
fi

# ── Step 3: Copy SSH public key to all nodes ──────────────────────────────────
log "Step 3: Copy SSH key (enter each node's password when prompted)"
for host in "${ALL_HOSTS[@]}"; do
  echo "  --- $host ---"
  ssh-copy-id -i "${SSH_KEY}.pub" "$host" || echo "  Warning: $host skipped (already set up?)"
done

# ── Step 4: Test passwordless SSH ────────────────────────────────────────────
log "Step 4: Test passwordless SSH"
ALL_OK=true
for host in "${ALL_HOSTS[@]}"; do
  if ssh -o BatchMode=yes "$host" 'echo ok' >/dev/null 2>&1; then
    echo "  $host: OK"
  else
    echo "  $host: FAILED"
    ALL_OK=false
  fi
done

if [[ "$ALL_OK" != "true" ]]; then
  echo ""
  echo "ERROR: Some nodes failed passwordless SSH. Fix before continuing."
  exit 1
fi

# ── Step 5: Install NOPASSWD sudoers on CSI nodes ────────────────────────────
log "Step 5: NOPASSWD sudoers on CSI nodes"

for node_info in "${CSI_NODES[@]}"; do
  host="${node_info%%:*}"
  rest="${node_info#*:}"
  home_dir="${rest%%:*}"
  rest2="${rest#*:}"
  username="${rest2%%:*}"
  sudo_pass="${rest2##*:}"

  echo "  --- $host (user: $username, home: $home_dir) ---"

  # Generate sudoers content locally
  TMPFILE=$(mktemp)
  cat > "$TMPFILE" <<SUDOERS
# pilot-csi: NOPASSWD for CSI capture commands
# Managed by setup_pilot.sh — do not edit manually
# Security note: intended for a local research network only

Cmnd_Alias PILOT_WIFI    = /usr/bin/nmcli, /usr/bin/pkill
Cmnd_Alias PILOT_IFACE   = /sbin/ip, /usr/sbin/ip, /bin/ip, /sbin/ifconfig, /usr/sbin/ifconfig, /sbin/ipconfig
Cmnd_Alias PILOT_CAPTURE = /usr/sbin/tcpdump, /usr/bin/tcpdump
Cmnd_Alias PILOT_FILES   = /bin/rm, /usr/bin/rm
Cmnd_Alias PILOT_SIGNAL  = /bin/kill, /usr/bin/kill
Cmnd_Alias PILOT_NEXUTIL = ${home_dir}/nexmon/utilities/nexutil/nexutil, \
                           ${home_dir}/nexmon/patches/bcm43455c0/7_45_189/nexmon_csi/utils/makecsiparams/makecsiparams

${username} ALL=(root) NOPASSWD: PILOT_WIFI, PILOT_IFACE, PILOT_CAPTURE, PILOT_FILES, PILOT_SIGNAL, PILOT_NEXUTIL
SUDOERS

  # Copy to Pi, validate with visudo, install — use sudo -S to pipe password non-interactively
  scp -q "$TMPFILE" "${host}:/tmp/90-pilot-csi"
  printf '%s\n' "$sudo_pass" | ssh "$host" \
    'sudo -S visudo -c -f /tmp/90-pilot-csi 2>&1 \
     && sudo -S install -m 440 /tmp/90-pilot-csi /etc/sudoers.d/90-pilot-csi 2>&1 \
     && rm /tmp/90-pilot-csi \
     && echo "  sudoers installed OK"' \
    || echo "  Warning: sudoers setup failed on $host"

  rm "$TMPFILE"
done

# ── Step 6: Verify non-interactive sudo on CSI nodes ─────────────────────────
log "Step 6: Verify non-interactive sudo on CSI nodes"
for node_info in "${CSI_NODES[@]}"; do
  host="${node_info%%:*}"
  if ssh "$host" 'sudo -n true 2>&1 && echo sudo_ok' | grep -q sudo_ok; then
    echo "  $host: sudo OK"
  else
    echo "  $host: sudo FAILED — check /etc/sudoers.d/90-pilot-csi"
  fi
done

# ── Step 7: Sync updated scripts to all nodes ─────────────────────────────────
log "Step 7: Sync capture scripts to all Pi nodes"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for host in "${ALL_HOSTS[@]}"; do
  rsync -av --delete \
    "$SCRIPT_DIR/" \
    "$host:~/pilot/scripts/" \
    | grep -v '^sending\|^sent\|^total\|^$' || true
  echo "  $host: synced"
done

# ── Done ──────────────────────────────────────────────────────────────────────
log "Setup complete"
cat <<'MSG'

All nodes are ready. CSI capture no longer needs 'sudo tmux' or 'ssh -tt'.
Use the standard launch command:

  ssh "$PI3_SSH" "tmux new-session -d -s csi_${SESSION} \
    /home/pi/pilot/scripts/csi_launcher.sh ${SESSION} ${CSI_CHANNEL}"

See pilot/SSH_REMOTE_CAPTURE_RUNBOOK.md § 11 for the full three-node flow.
MSG
