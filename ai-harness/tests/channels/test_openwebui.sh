#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# OpenWebUI Channel Smoke Test
#
# Validates that the harness endpoints the OpenWebUI tools call
# are reachable and return valid JSON. Each test mirrors one or
# more tool methods from the modular tool files in
# channels/openwebui/.
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
echo "  OpenWebUI Channel Smoke Test"
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
    python3 -c "import json; json.load(open('${resp}'))" 2>/dev/null && echo "  ℹ Valid JSON response"
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

# ── research_tools.py ────────────────────────────────────────

call_post "web_search" "/web/search" '{
  "query": "FastAPI health check best practices",
  "max_results": 3,
  "crawl_results": 0,
  "summarize": false,
  "mode": "sources"
}'

call_post "summarize_web_search" "/web/search" '{
  "query": "FastAPI health check best practices",
  "max_results": 3,
  "crawl_results": 2,
  "summarize": true,
  "mode": "answer"
}' 120

# ── knowledge_tools.py ───────────────────────────────────────

call_post "family_kb_search" "/kb/search" '{
  "query": "family knowledge base",
  "limit": 3
}'

call_post "family_kb_ask" "/kb/ask" '{
  "query": "What information is saved in the family knowledge base?",
  "limit": 3
}'

# ── creative_tools.py ────────────────────────────────────────

call_get "list_presentations" "/presentation/list"

call_post "create_presentation_async" "/presentation/generate/async" '{
  "title": "OpenWebUI Smoke Test",
  "content": "A quick smoke test presentation.",
  "n_slides": 2,
  "template": "general",
  "tone": "professional",
  "verbosity": "concise"
}' 30

call_post "generate_outline" "/presentation/outline" '{
  "topic": "Introduction to AI homelabs",
  "instructions": "3 slides max",
  "research": false,
  "kb_search": false
}' 120

call_post "create_document" "/layout/build" '{
  "title": "Smoke Test Document",
  "template": "minimal",
  "orientation": "portrait",
  "zones": [{"type":"title","text":"Hello from OpenWebUI test"}],
  "output_path": "documents/smoke-test-ow.html"
}' 30

# ── apps_tools.py ────────────────────────────────────────────

call_get "list_demos" "/demos/?limit=3"

call_get "find_demo" "/demos/search?q=test&limit=3"

# ── scheduler_tools.py ───────────────────────────────────────

call_get "list_schedules" "/schedules"

echo
echo "=========================================================="
echo "  OpenWebUI channel smoke tests complete"
echo "=========================================================="
echo
