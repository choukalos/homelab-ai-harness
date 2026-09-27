#!/usr/bin/env bash
# =====================================================================
# backup-setup.sh — ONE-TIME root setup for the Lego backup mount.
#
#   sudo scripts/backup-setup.sh            # uses share from <host>.json
#   sudo scripts/backup-setup.sh <share>    # override the share name
#   CONFIG=/path/to/host.json sudo scripts/backup-setup.sh   # other host
#
# Host-agnostic: reads scripts/backup-hosts/<hostname>.json for the
# server/mountpoint/credentials. Idempotent — safe to re-run after
# changing the share or password.
#
# Order (matters — fstab must exist before the first mount):
#   1. verify ~/.smbcredentials has a real password (not CHANGE_ME)
#   2. install cifs-utils (mount.cifs) if missing
#   3. create the mountpoint dir
#   4. write the fstab entry:
#        //lego.local/<share>  /mnt/lego  cifs  credentials=...,uid=,gid=,
#        vers=2.1,soft,noauto,x-systemd.automount,_netdev
#      (vers=2.1: Lego's SMB server rejects SMB3 (EOPNOTSUPP) and
#       SMB2.0.2 (EINVAL); 2.1 is the highest dialect it accepts —
#       measured 2026-09-26. soft: a dead session errors out instead of
#       wedging the kernel into D-state zombies. noauto +
#       x-systemd.automount: a downed NAS can't wedge boot.)
#   5. install a scoped sudoers rule so the backup user can (re)mount
#      /mnt/lego without a password (the self-heal needs it)
#   6. mount, check free capacity, write a test file
# =====================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fail() { echo "SETUP FAILED: $*" >&2; exit 1; }

# --- config (from the host JSON; override with CONFIG=... for other hosts) ---
CONFIG="${CONFIG:-$SCRIPT_DIR/backup-hosts/thor.json}"
[[ -f "$CONFIG" ]] || fail "config not found: $CONFIG"
SERVER="$(jq -r '.nas.server' "$CONFIG")"
SHARE="$(jq -r '.nas.share' "$CONFIG")"
MOUNT="$(jq -r '.nas.mountpoint' "$CONFIG")"
CRED_FILE="$(jq -r '.nas.credentials // "~/.smbcredentials"' "$CONFIG")"
CRED_FILE="${CRED_FILE/#\~/$HOME}"
HOST_ID="$(jq -r '.host_id // empty' "$CONFIG")"; [[ -n "$HOST_ID" ]] || HOST_ID="$(hostname -s)"
MOUNT_UID="${MOUNT_UID:-$(id -u)}"
MOUNT_GID="${MOUNT_GID:-$(id -g)}"
BACKUP_USER="$(getent passwd "$MOUNT_UID" | cut -d: -f1)"
[[ -n "$BACKUP_USER" ]] || fail "could not resolve username for uid $MOUNT_UID"
MARKER="# lego-backup-managed"

# optional share override
if [[ $# -ge 1 && -n "${1:-}" ]]; then SHARE="$1"; fi
[[ "$SHARE" =~ ^[A-Za-z0-9_-]{1,63}$ ]] || { echo "invalid share name: $SHARE (allowed: letters, digits, -, _)" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail "must run as root (sudo):  sudo $0"

# --- 1. credentials --------------------------------------------------------
[[ -f "$CRED_FILE" ]] || fail "credentials file $CRED_FILE missing — create it (username=/password=, chmod 600)"
if grep -qE '^password=CHANGE_ME' "$CRED_FILE"; then
  fail "$CRED_FILE still contains the CHANGE_ME placeholder — set the real Lego password first"
fi
echo "credentials: $CRED_FILE present"

# --- 2. cifs-utils (mount.cifs) -------------------------------------------
if ! command -v mount.cifs >/dev/null 2>&1; then
  echo "installing cifs-utils (mount.cifs)..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq >/dev/null 2>&1 || true
  apt-get install -y -qq cifs-utils >/dev/null 2>&1 || fail "install cifs-utils failed — run manually: sudo apt-get install -y cifs-utils"
fi
command -v mount.cifs >/dev/null 2>&1 || fail "mount.cifs still missing after install — check apt"
echo "cifs-utils: $(mount.cifs --version 2>/dev/null | head -1 || echo present)"

# --- 3. mountpoint dir -----------------------------------------------------
mkdir -p "$MOUNT"
chmod 755 "$MOUNT"
echo "mountpoint: $MOUNT ready"

# --- 4. fstab (replace any previous managed entry) ------------------------
# uid=/gid= make the root-mounted share appear owned by the backup user.
# NO file_mode/dir_mode: Lego's SMB server doesn't expose real Unix modes
# (client reports 755 for everything), and a forced file_mode breaks rsync
# --link-dest hardlinking. The backup scripts use rsync -rt.
# `soft` (not `hard`): a dead session on a hard mount blocks I/O forever and
# wedges the kernel (D-state zombies + stuck umount -l). With soft, I/O fails
# with an error instead; the post-run verify catches partial runs.
FSTAB_LINE="//$SERVER/$SHARE	$MOUNT	cifs	credentials=$CRED_FILE,uid=$MOUNT_UID,gid=$MOUNT_GID,vers=2.1,soft,noauto,x-systemd.automount,_netdev	0 0"
if grep -qF "$MARKER" /etc/fstab; then
  sed -i "/$MARKER/d; /^\/\/$SERVER/d" /etc/fstab
  echo "fstab: removed previous managed entry"
fi
cp /etc/fstab /etc/fstab.bak-lego-backup 2>/dev/null || true
printf '%s\n%s\n' "$MARKER" "$FSTAB_LINE" >> /etc/fstab
grep -qF "$MOUNT" /etc/fstab || fail "fstab write failed — $MOUNT not in /etc/fstab"
echo "fstab: installed"
echo "        $FSTAB_LINE"

# --- 5. scoped sudoers: let the backup user (re)mount $MOUNT passwordless ---
SUDOERS_FILE=/etc/sudoers.d/lego-backup
printf '%s ALL=(root) NOPASSWD: /bin/mount %s, /bin/umount -l %s\n' "$BACKUP_USER" "$MOUNT" "$MOUNT" > "$SUDOERS_FILE"
chmod 440 "$SUDOERS_FILE"
visudo -c -f "$SUDOERS_FILE" >/dev/null 2>&1 || { rm -f "$SUDOERS_FILE"; fail "sudoers validation failed"; }
echo "sudoers: $BACKUP_USER can mount/remount $MOUNT without password"

# --- 6. systemd: regenerate the fstab units (x-systemd.automount) ----------
systemctl daemon-reload 2>/dev/null && echo "systemd: fstab units regenerated" || echo "WARNING: systemctl daemon-reload failed (units appear after reboot)"

# --- 7. cifs kernel module -------------------------------------------------
lsmod | grep -q '^cifs ' || modprobe cifs || echo "WARNING: could not load cifs module (try: sudo depmod -a && sudo modprobe cifs)"

# --- 8. mount + verify -----------------------------------------------------
# Self-heal: a previous mount may be hung (Lego's SMB server kills idle
# sessions and rate-limits after churn). Bounded: umount -l 30s, mount 600s.
if timeout 15 ls "$MOUNT" >/dev/null 2>&1; then
  echo "$MOUNT already mounted and responsive"
else
  echo "$MOUNT missing or unresponsive — (re)mounting"
  timeout 30 umount -l "$MOUNT" 2>/dev/null || true
  sleep 1
  if grep -qE "^[^ ]+ $MOUNT " /proc/mounts 2>/dev/null; then
    fail "stale mount of $MOUNT still attached (umount -l timed out) — wedged CIFS state, reboot the host to clear it"
  fi
  # Mount with a clear error if it fails (share name / creds / network / SMB version).
  if ! timeout 600 mount "$MOUNT" 2>&1; then
    echo "--- diagnostics ---"
    echo "  ping:   $(ping -c 1 -W 2 "$SERVER" 2>&1 | grep -E 'bytes from|100% packet' | head -1 || echo unreachable)"
    echo "  creds:  $CRED_FILE ($( [[ -f $CRED_FILE ]] && echo present || echo MISSING ))"
    echo "  share:  //${SERVER}/${SHARE}"
    echo "  try:    smbclient -L //$SERVER -U backup -m 'SMB2,2.1'  (lists shares; confirms SMB dialect)"
    fail "mount failed — see diagnostics above"
  fi
  timeout 15 ls "$MOUNT" >/dev/null 2>&1 || fail "$MOUNT still unresponsive after remount — check the NAS (dmesg | grep -i cifs)"
fi
echo "mounted $MOUNT"

# host tree (created AFTER the mount so it lands on the share)
mkdir -p "$MOUNT/$HOST_ID"
chmod 755 "$MOUNT/$HOST_ID"
echo "layout: //${SERVER}/${SHARE} -> $MOUNT ; this host's tree: $MOUNT/$HOST_ID"

# --- capacity check (Thor needs ~5 GB; warn if < 10 GB) --------------------
avail_kb="$(df -Pk "$MOUNT/$HOST_ID" | awk 'NR==2 {print $4}')"
avail_gb="$((avail_kb / 1024 / 1024))"
if (( avail_gb < 5 )); then
  fail "only ${avail_gb}GB free on the share — Thor's backup needs ~5GB; free up space or reduce scope"
elif (( avail_gb < 10 )); then
  echo "WARNING: ${avail_gb}GB free — Thor's backup needs ~5GB; little headroom"
else
  echo "capacity OK: ${avail_gb}GB free"
fi

# --- write test -------------------------------------------------------------
testfile="$MOUNT/$HOST_ID/.write-test-$$"
echo "lego-backup setup $(date -Is)" > "$testfile"
rm -f "$testfile"
echo "write test OK"

echo
echo "=== setup complete ==="
echo "Next steps:"
echo "  1. scripts/backup-nas.sh daily --dry-run    # sanity check (generates + hashes, no commit)"
echo "  2. scripts/backup-nas.sh daily              # first real daily run (verify must say 'verify OK')"
echo "  3. scripts/backup-nas.sh weekly             # then the weekly scope"
echo "Don't panic if the mount blocks for minutes on the first run (Lego's"
echo "login rate-limit after session churn); the self-heal waits it out."