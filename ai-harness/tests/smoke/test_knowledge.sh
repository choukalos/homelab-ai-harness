#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Knowledge Smoke Test — Family KB health, ingest, search, ask
# ─────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set -a
source "${SCRIPT_DIR}/../../../.env"
set +a

BASE_URL="${BASE_LOCAL:-http://${THOR_IP:-192.168.4.54}:8090}"
API_KEY="${HARNESS_API_KEY:-}"

echo "=========================================================="
echo "  Knowledge Smoke Test"
echo "  Base URL: ${BASE_URL}"
echo "=========================================================="

# ── Helpers ──────────────────────────────────────────────────

call_post() {
  local name="$1" path="$2" payload="$3" timeout="${4:-120}"
  local resp
  resp="$(mktemp)"

  echo ""
  echo "==== ${name} ===>"
  echo "  POST ${path}"

  HTTP_CODE=$(curl -sS -o "${resp}" -w "%{http_code}" \
    -X POST "${BASE_URL}${path}" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d "${payload}" \
    --max-time "${timeout}" 2>/dev/null) || HTTP_CODE="000"

  if [ "${HTTP_CODE}" = "200" ]; then
    echo "  ✅ ${name} (HTTP 200)"
  else
    echo "  ❌ ${name} (HTTP ${HTTP_CODE})"
    head -10 "${resp}"
  fi
  rm -f "${resp}"
}

call_get() {
  local name="$1" path="$2"
  local resp
  resp="$(mktemp)"

  echo ""
  echo "==== ${name} ===>"
  echo "  GET ${path}"

  HTTP_CODE=$(curl -sS -o "${resp}" -w "%{http_code}" \
    "${BASE_URL}${path}" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

  if [ "${HTTP_CODE}" = "200" ]; then
    echo "  ✅ ${name} (HTTP 200)"
  else
    echo "  ❌ ${name} (HTTP ${HTTP_CODE})"
    head -10 "${resp}"
  fi
  rm -f "${resp}"
}

# ── Health check ─────────────────────────────────────────────
echo -n "Health check... "
HC=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${BASE_URL}/health" 2>/dev/null) || HC="000"
if [ "${HC}" = "200" ]; then
    echo "✅ OK"
else
    echo "❌ FAILED (HTTP ${HC}) — aborting"
    exit 1
fi

# ── Tests ────────────────────────────────────────────────────

call_get "KB Health" "/kb/health"

call_post "KB Raw Ingest" "/kb/ingest/raw" '{}' 600

call_post "KB Index Markdown" "/kb/ingest" '{}' 600

call_post "KB Search" "/kb/search" '{
  "query": "family knowledge base",
  "limit": 5
}'

call_post "KB Ask" "/kb/ask" '{
  "query": "What information is saved in the family knowledge base?",
  "limit": 5
}'

echo
echo "=========================================================="
echo "  Knowledge smoke tests complete"
echo "=========================================================="
echo
