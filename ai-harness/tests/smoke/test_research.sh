#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Research Smoke Test — Web Search, Summarized Search,
# Research Brief, and Deep Research
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
echo "  Research Smoke Test"
echo "  Base URL: ${BASE_URL}"
echo "=========================================================="

# ── Helpers ──────────────────────────────────────────────────

call_post() {
  local name="$1" path="$2" payload="$3"
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
    --max-time 240 2>/dev/null) || HTTP_CODE="000"

  if [ "${HTTP_CODE}" = "200" ]; then
    echo "  ✅ ${name} (HTTP 200)"
    python3 -c "import json; json.load(open('${resp}'))" 2>/dev/null && echo "  ℹ Valid JSON response"
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

call_post "Web Search (sources)" "/web/search" '{
  "query": "FastAPI health check best practices",
  "max_results": 5,
  "crawl_results": 0,
  "summarize": false,
  "mode": "sources"
}'

call_post "Summarized Web Search (answer)" "/web/search" '{
  "query": "FastAPI health check best practices",
  "max_results": 5,
  "crawl_results": 3,
  "summarize": true,
  "mode": "answer"
}'

call_post "Research Brief" "/web/research" '{
  "topic": "local first AI knowledge base architecture for a homelab",
  "max_queries": 3,
  "results_per_query": 4
}'

call_post "Deep Research" "/workflows/deep-research/run" '{
  "query": "What are the top 3 trends in local-first AI?"
}'

echo
echo "=========================================================="
echo "  Research smoke tests complete"
echo "=========================================================="
echo
