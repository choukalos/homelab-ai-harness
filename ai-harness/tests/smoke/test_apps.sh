#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Apps Smoke Test — PM Demo + Demo Workflow
# ─────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set -a
source "${SCRIPT_DIR}/../../../.env"
set +a

BASE_URL="${BASE_LOCAL:-http://${THOR_IP:-192.168.4.54}:8090}"
API_KEY="${HARNESS_API_KEY:-}"
TMP_FILE=$(mktemp)

trap 'rm -f "${TMP_FILE}"' EXIT

echo "=========================================================="
echo "  Apps Smoke Test"
echo "  Base URL: ${BASE_URL}"
echo "=========================================================="

# ── Helpers ──────────────────────────────────────────────────

call_post() {
  local name="$1" path="$2" payload="$3" timeout="${4:-600}"
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

  if [ "${HTTP_CODE}" = "200" ] || [ "${HTTP_CODE}" = "201" ] || [ "${HTTP_CODE}" = "202" ]; then
    echo "  ✅ ${name} (HTTP ${HTTP_CODE})"
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

# ── PM Demo ──────────────────────────────────────────────────

call_post "PM Demo Generation" "/pm/demo" '{
  "title": "Smoke Test Mobile PM Demo",
  "prompt": "Create a simple 3-screen clickable mobile product demo for a family task tracker. Include home, task detail, and add task screens.",
  "save_name": "smoke-test-pm-demo"
}' 600

# ── Demo Workflow ────────────────────────────────────────────

call_post "Demo Workflow (sync)" "/demos/run" '{
  "title": "Smoke Test Calculator",
  "prompt": "Build a one-page clickable demo for a mobile calculator app with a clean modern UI."
}' 600

call_post "Demo Workflow (async)" "/demos/run/async" '{
  "title": "Smoke Test Async Demo",
  "prompt": "Build a one-page demo for a todo list app with add/delete functionality."
}' 30

call_get "List Demos" "/demos/?limit=5"

call_get "Search Demos" "/demos/search?q=calculator&limit=5"

echo
echo "=========================================================="
echo "  Apps smoke tests complete"
echo "=========================================================="
echo
