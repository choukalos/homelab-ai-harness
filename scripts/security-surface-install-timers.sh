#!/usr/bin/env bash
# =====================================================================
# security-surface-install-timers.sh — install + enable the
# public-surface (SEC Phase 11) timers.
#
#   sudo scripts/security-surface-install-timers.sh
#
# Copies the unit files from scripts/systemd/ into /etc/systemd/system,
# reloads systemd, and enables + starts the surface daily scan + weekly
# check timers. Idempotent — safe to re-run.
#
# SEC Phase 11 deploy step (see docs/security_phase11_deploy.md).
# Phase 10's scripts/security-install-timers.sh is left untouched —
# each phase's deploy is self-contained.
# =====================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "must run as root (sudo)" >&2; exit 1; }

UNITS=(security-surface-daily.service security-surface-daily.timer security-surface-weekly.service security-surface-weekly.timer)

for u in "${UNITS[@]}"; do
  src="$SCRIPT_DIR/systemd/$u"
  [[ -f "$src" ]] || { echo "missing unit file: $src" >&2; exit 1; }
  cp "$src" "/etc/systemd/system/$u"
  echo "installed /etc/systemd/system/$u"
done

systemctl daemon-reload
echo "systemd reloaded"

for t in security-surface-daily.timer security-surface-weekly.timer; do
  systemctl enable "$t" >/dev/null
  systemctl restart "$t"
  echo "enabled + started $t"
done

echo
echo "=== timers (next scheduled runs) ==="
systemctl list-timers 'security-surface-*' --all --no-pager 2>/dev/null || true
echo
echo "=== run one on demand (no timer needed) ==="
echo "  sudo systemctl start security-surface-daily.service   # run the daily surface scan now"
echo "  sudo systemctl start security-surface-weekly.service  # run the weekly check now (schema-diff baseline on first run)"
echo "  journalctl -u security-surface-daily.service -n 50    # see the result"
echo "  ./homelab.sh security surface                          # on-demand status"
echo
echo "=== done ==="
