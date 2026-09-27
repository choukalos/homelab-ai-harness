#!/usr/bin/env bash
# =====================================================================
# backup-install-timers.sh — install + enable the backup systemd timers.
#
#   sudo scripts/backup-install-timers.sh
#
# Copies the unit files from scripts/systemd/ into /etc/systemd/system,
# reloads systemd, and enables + starts the daily + weekly timers.
# Idempotent — safe to re-run.
# =====================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "must run as root (sudo)" >&2; exit 1; }

UNITS=(backup-nas-daily.service backup-nas-daily.timer backup-nas-weekly.service backup-nas-weekly.timer)

for u in "${UNITS[@]}"; do
  src="$SCRIPT_DIR/systemd/$u"
  [[ -f "$src" ]] || { echo "missing unit file: $src" >&2; exit 1; }
  cp "$src" "/etc/systemd/system/$u"
  echo "installed /etc/systemd/system/$u"
done

systemctl daemon-reload
echo "systemd reloaded"

for t in backup-nas-daily.timer backup-nas-weekly.timer; do
  systemctl enable "$t" >/dev/null
  systemctl restart "$t"
  echo "enabled + started $t"
done

echo
echo "=== timers (next scheduled runs) ==="
systemctl list-timers 'backup-nas-*' --all --no-pager 2>/dev/null || true
echo
echo "=== run one on demand (no timer needed) ==="
echo "  sudo systemctl start backup-nas-daily.service    # run the daily scope now"
echo "  journalctl -u backup-nas-daily.service -n 50     # see the result"
echo
echo "=== done ==="