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

# Verify response URLs don't contain internal hostname (thor.local)
# Used after call_post / call_post_and_verify_url to check URL fields
verify_urls() {
  local resp="$1"
  local has_internal
  has_internal=$(jq -r '[
    (.url // empty), (.local_url // empty), (.public_url // empty),
    (.download_url // empty), (.pdf_url // empty), (.html_url // empty),
    (.image_url // empty)
  ] | map(select(type == "string")) | map(select(contains("thor.local"))) | if length > 0 then "yes" else "no" end' "${resp}" 2>/dev/null)
  if [ "${has_internal}" = "yes" ]; then
    echo "  ⚠️  URL rewrite check FAILED — response contains thor.local URLs:"
    jq -r '[
      (.url // empty), (.local_url // empty), (.public_url // empty),
      (.download_url // empty), (.pdf_url // empty), (.html_url // empty),
      (.image_url // empty)
    ] | map(select(type == "string")) | .[] | select(contains("thor.local"))' "${resp}" 2>/dev/null | while read -r url; do
      echo "    ⚠️  ${url}"
    done
  else
    echo "  ✅ URL rewrite check passed (no thor.local in response)"
  fi
}

# POST + URL verification in one call
call_post_and_verify_url() {
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

  if [ "${HTTP_CODE}" = "200" ] || [ "${HTTP_CODE}" = "201" ] || [ "${HTTP_CODE}" = "202" ]; then
    echo "  ✅ ${name} (HTTP ${HTTP_CODE})"
    verify_urls "${resp}"
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
  "n_slides": 3,
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

call_post_and_verify_url "create_document" "/layout/build" '{
  "title": "Smoke Test Document",
  "template": "minimal",
  "orientation": "portrait",
  "zones": [{"zone":"header","content_type":"text","content":"Hello from OpenWebUI test"}],
  "output_path": "documents/smoke-test-ow.html"
}' 30

# ── apps_tools.py ────────────────────────────────────────────

call_get "list_demos" "/demos/?limit=3"

call_get "find_demo" "/demos/search?q=test&limit=3"

call_post_and_verify_url "Quick Demo (apps_tools: create_quick_demo)" "/pm/demo" '{
  "title": "OpenWebUI Smoke Test Quick Demo",
  "prompt": "Create a simple 2-screen clickable mobile demo for a notes app.",
  "save_name": "smoke-test-ow-quick-demo"
}' 300

call_post_and_verify_url "Workflow Demo (apps_tools: create_workflow_demo)" "/demos/run" '{
  "title": "OpenWebUI Smoke Test Workflow Demo",
  "prompt": "Build a one-page clickable demo for a settings page with toggles."
}' 600

# ── scheduler_tools.py ───────────────────────────────────────

call_get "list_schedules" "/schedules"

echo
echo "=========================================================="
echo "  OpenWebUI channel smoke tests complete"
echo "=========================================================="
echo
