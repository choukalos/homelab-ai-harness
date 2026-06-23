#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Filetools Smoke Test (stub — no filetools endpoints yet)
# ─────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set -a
source "${SCRIPT_DIR}/../../../.env"
set +a

BASE_URL="${BASE_LOCAL:-http://${THOR_IP:-192.168.4.54}:8090}"

echo "=========================================================="
echo "  Filetools Smoke Test"
echo "  Base URL: ${BASE_URL}"
echo "=========================================================="

# ── Health check ─────────────────────────────────────────────
echo -n "Health check... "
HC=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${BASE_URL}/health" 2>/dev/null) || HC="000"
if [ "${HC}" = "200" ]; then
    echo "✅ OK"
else
    echo "❌ FAILED (HTTP ${HC}) — aborting"
    exit 1
fi

echo ""
echo "ℹ  No filetools smoke tests yet. Add tests here as endpoints are built."
echo ""
echo "=========================================================="
echo "  Filetools smoke tests complete (no-op)"
echo "=========================================================="
echo
