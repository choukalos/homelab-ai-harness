#!/usr/bin/env bash
# =====================================================================
# key-watch-install-timers.sh — install + enable the SEC Phase 6 timers.
#
#   sudo scripts/key-watch-install-timers.sh
#
# Copies the unit files from scripts/systemd/ into /etc/systemd/system,
# reloads systemd, and enables + starts the 5-min key/auth watch and
# the monthly key audit. Idempotent — safe to re-run.
#
# SEC Phase 6 deploy step (see security_todo.md § Phase 6).
# =====================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "must run as root (sudo)" >&2; exit 1; }

UNITS=(key-watch.service key-watch.timer key-audit-monthly.service key-audit-monthly.timer)

for u in "${UNITS[@]}"; do
  src="$SCRIPT_DIR/systemd/$u"
  [[ -f "$src" ]] || { echo "missing unit file: $src" >&2; exit 1; }
  cp "$src" "/etc/systemd/system/$u"
  echo "installed /etc/systemd/system/$u"
done

systemctl daemon-reload
echo "systemd reloaded"

for t in key-watch.timer key-audit-monthly.timer; do
  systemctl enable "$t" >/dev/null
  systemctl restart "$t"
  echo "enabled + started $t"
done

echo
echo "=== timers (next scheduled runs) ==="
systemctl list-timers 'key-*' --all --no-pager 2>/dev/null || true
echo
echo "=== run on demand (no timer needed) ==="
echo "  sudo systemctl start key-watch.service          # run the watch now"
echo "  sudo systemctl start key-audit-monthly.service  # run the audit now"
echo "  journalctl -u key-watch.service -n 50           # see the result"
echo
echo "=== done ==="
