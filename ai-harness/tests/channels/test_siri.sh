#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Siri Channel Smoke Test
# ─────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set -a
source "${SCRIPT_DIR}/../../../.env"
set +a

BASE_LOCAL="${BASE_LOCAL:-http://${THOR_IP:?THOR_IP is not set}:8090}"
BASE_PUBLIC="${BASE_PUBLIC:-https://siri.choukalos.com}"
SIRI_API_KEY="${SIRI_API_KEY:?SIRI_API_KEY is not set}"

echo "=========================================================="
echo "  Siri Channel Smoke Test"
echo "  Local:  ${BASE_LOCAL}"
echo "  Public: ${BASE_PUBLIC}"
echo "=========================================================="

echo "== Local health =="
curl -fsS "$BASE_LOCAL/health"
echo

echo "== Local Siri chat =="
curl -fsS -X POST "$BASE_LOCAL/siri/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SIRI_API_KEY" \
  -d '{"text":"Say hello from the local Siri harness test."}'
echo

echo "== Public health =="
curl -fsS "$BASE_PUBLIC/health"
echo

echo "== Public Siri chat =="
curl -fsS -X POST "$BASE_PUBLIC/siri/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SIRI_API_KEY" \
  -d '{"text":"Say hello from the public Siri harness test."}'
echo

echo "== Public auth should fail =="
status="$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_PUBLIC/siri/chat" \
  -H "Content-Type: application/json" \
  -d '{"text":"This should fail."}')"

if [ "$status" = "401" ]; then
  echo "PASS: unauthenticated request returned 401"
else
  echo "FAIL: expected 401, got $status"
  exit 1
fi

echo
echo "=========================================================="
echo "  ✅ Siri smoke tests passed"
echo "=========================================================="
echo
