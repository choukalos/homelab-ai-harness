#!/usr/bin/env bash
# plausible-install-timer.sh — install + start the plausible-export-daily
# systemd timer (sudo required). Idempotent: safe to re-run.
#
#   sudo bash scripts/plausible-install-timer.sh
#
# The timer runs scripts/plausible-export.sh daily at 02:00 UTC, which drops
# a Plausible daily-aggregates CSV into the data-hub inbox; the data-hub
# watcher ingests it into hub.ds_plausible.
set -euo pipefail

REPO="${REPO:-/home/chuck/homelab}"
cd "$REPO"

# 1. Register the dataset (idempotent) — do this first so the watcher can
#    claim the first export as soon as it lands.
bash scripts/plausible-register-dataset.sh

# 2. Install the units.
sudo cp scripts/systemd/plausible-export-daily.service scripts/systemd/plausible-export-daily.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now plausible-export-daily.timer

echo "✓ installed + started plausible-export-daily.timer"
systemctl list-timers plausible-export-daily.timer --no-pager || true
echo
echo "Run an export now (and watch data-hub ingest it):"
echo "  bash scripts/plausible-export.sh"
echo "  curl -s http://192.168.4.54:8100/api/datasets/plausible/preview?limit=5"
