#!/usr/bin/env bash
# =====================================================================
# security-install-timers.sh — install + enable the security timers.
#
#   sudo scripts/security-install-timers.sh
#
# Copies the unit files from scripts/systemd/ into /etc/systemd/system,
# reloads systemd, and enables + starts the daily scan + weekly digest
# timers. Idempotent — safe to re-run.
#
# SEC Phase 10 deploy step (see docs/security_phase10_deploy.md).
# =====================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "must run as root (sudo)" >&2; exit 1; }

UNITS=(security-scan-daily.service security-scan-daily.timer security-digest-weekly.service security-digest-weekly.timer)

for u in "${UNITS[@]}"; do
  src="$SCRIPT_DIR/systemd/$u"
  [[ -f "$src" ]] || { echo "missing unit file: $src" >&2; exit 1; }
  cp "$src" "/etc/systemd/system/$u"
  echo "installed /etc/systemd/system/$u"
done

systemctl daemon-reload
echo "systemd reloaded"

for t in security-scan-daily.timer security-digest-weekly.timer; do
  systemctl enable "$t" >/dev/null
  systemctl restart "$t"
  echo "enabled + started $t"
done

echo
echo "=== timers (next scheduled runs) ==="
systemctl list-timers 'security-*' --all --no-pager 2>/dev/null || true
echo
echo "=== run one on demand (no timer needed) ==="
echo "  sudo systemctl start security-scan-daily.service      # run the daily scan now"
echo "  sudo systemctl start security-digest-weekly.service   # run the weekly digest now"
echo "  journalctl -u security-scan-daily.service -n 50       # see the result"
echo
echo "=== done ==="
