#!/usr/bin/env bash
# =====================================================================
# setup-media-nas.sh — one-time setup for the Media project's NAS mount
# =====================================================================
# Mounts the lego `workspace` share (the media archive) at
# /home/chuck/data/media-nas, following the backup share's proven pattern
# (scripts/backup-setup.sh): fstab automount (vers=2.1,soft) + a scoped
# sudoers rule so chuck can (re)mount without a password.
#
# Run once (idempotent — safe to re-run):
#   sudo ./scripts/setup-media-nas.sh
#
# After it succeeds, the mcp_kanban container (compose/compose.mcp.yml)
# binds the mount at /media-store and the blog file drop at /publish.
# =====================================================================
set -euo pipefail

SERVER="lego.local"
SHARE="workspace"
MOUNT="/home/chuck/data/media-nas"
CRED_FILE="/home/chuck/.smbcredentials"
MARKER="# managed: media-nas (setup-media-nas.sh)"
SUDOERS_FILE="/etc/sudoers.d/media-nas"
SUDO_USER_NAME="${SUDO_USER:-chuck}"

fail() { echo "ERROR: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail "must run as root:  sudo $0"
[[ -f "$CRED_FILE" ]] || fail "credentials file $CRED_FILE missing (username=/password=)"

# --- 1. mountpoint (chuck-owned so host-side tools work pre-mount) ---------
mkdir -p "$MOUNT"
chown 1000:1000 "$MOUNT"
chmod 755 "$MOUNT"
echo "mountpoint: $MOUNT ready"

# --- 2. fstab (replace any previous managed entry) -------------------------
# Same options as the backup share (scripts/backup-setup.sh):
# vers=2.1 + soft (Lego's SMB server kills idle sessions; a hard mount +
# dead session wedges the kernel), noauto + x-systemd.automount (mount on
# access), _netdev. uid=/gid= make the share appear owned by chuck (1000).
FSTAB_LINE="//$SERVER/$SHARE	$MOUNT	cifs	credentials=$CRED_FILE,uid=1000,gid=1000,vers=2.1,soft,noauto,x-systemd.automount,_netdev	0 0"
if grep -qF "$MARKER" /etc/fstab; then
  sed -i "/$MARKER/d" /etc/fstab
  sed -i "/^\/\/$SERVER\/$SHARE[[:space:]]/d" /etc/fstab
  echo "fstab: removed previous managed entry"
fi
cp /etc/fstab /etc/fstab.bak-media-nas 2>/dev/null || true
printf '%s\n%s\n' "$MARKER" "$FSTAB_LINE" >> /etc/fstab
grep -qF "$MOUNT" /etc/fstab || fail "fstab write failed — $MOUNT not in /etc/fstab"
echo "fstab: installed"
echo "        $FSTAB_LINE"

# --- 3. scoped sudoers: chuck can (re)mount $MOUNT passwordless -------------
printf '%s ALL=(root) NOPASSWD: /bin/mount %s, /bin/umount -l %s\n' \
  "$SUDO_USER_NAME" "$MOUNT" "$MOUNT" > "$SUDOERS_FILE"
chmod 440 "$SUDOERS_FILE"
visudo -c -f "$SUDOERS_FILE" >/dev/null 2>&1 || { rm -f "$SUDOERS_FILE"; fail "sudoers validation failed"; }
echo "sudoers: $SUDO_USER_NAME can mount/remount $MOUNT without password"

# --- 4. systemd + cifs module ------------------------------------------------
systemctl daemon-reload 2>/dev/null && echo "systemd: fstab units regenerated" || echo "WARNING: systemctl daemon-reload failed (units appear after reboot)"
lsmod | grep -q '^cifs ' || modprobe cifs || echo "WARNING: could not load cifs module (try: sudo depmod -a && sudo modprobe cifs)"

# --- 5. mount + verify -------------------------------------------------------
# Self-heal, bounded (same as backup-setup.sh): a stale kernel mount blocks
# the next mount until lazy-unmounted; Lego rate-limits logins after churn.
if timeout 15 ls "$MOUNT" >/dev/null 2>&1; then
  echo "$MOUNT already mounted and responsive"
else
  echo "$MOUNT missing or unresponsive — (re)mounting"
  timeout 30 umount -l "$MOUNT" 2>/dev/null || true
  sleep 1
  if grep -qE "^[^ ]+ $MOUNT " /proc/mounts; then
    fail "stale mount of $MOUNT still attached (umount -l timed out) — wedged CIFS state, reboot the host to clear it"
  fi
  timeout 600 mount "$MOUNT" || fail "mount failed — is $SERVER up? (ping $SERVER)"
fi
timeout 15 ls "$MOUNT" >/dev/null 2>&1 || fail "mounted but probe failed after mount — check $SERVER"
echo "mount: $MOUNT healthy"
echo
echo "Done. Re-run anytime (idempotent). The mcp_kanban container picks the"
echo "mount up on its next (re)start: docker compose -f compose/compose.mcp.yml up -d mcp_kanban"
