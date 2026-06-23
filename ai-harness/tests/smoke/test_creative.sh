#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Creative Smoke Test — Charts + Presentations
# ─────────────────────────────────────────────────────────────
# Quick smoke test hitting key creative endpoints.
# For exhaustive testing see the original test_charts.sh /
# test_presentation.sh in this directory.
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
echo "  Creative Smoke Test (Charts + Presentations)"
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

# ── Charts ───────────────────────────────────────────────────

call_post "Line Chart (HTML)" "/chart/line" '{
  "config": { "title": "Smoke Test Chart", "width": 600, "height": 400 },
  "traces": [
    { "name": "Series", "x": [1, 2, 3], "y": [10, 15, 13], "mode": "lines+markers" }
  ],
  "output_format": "html_fragment"
}' 30

call_post "Unified Chart (bar)" "/chart/any" '{
  "chart_type": "bar",
  "output_format": "html_fragment",
  "bar_traces": [
    { "name": "Test", "x": ["A", "B"], "y": [10, 20] }
  ]
}' 30

# ── Presentations ────────────────────────────────────────────

call_get "List Presentations" "/presentation/list"

call_post "Presentation Outline" "/presentation/outline" '{
  "topic": "Introduction to homelab infrastructure",
  "instructions": "Keep it to 4-5 slides",
  "research": false,
  "kb_search": false
}' 120

call_post "Presentation (async)" "/presentation/generate/async" '{
  "title": "Smoke Test Creative Presentation",
  "content": "A simple smoke test about creative AI tools.",
  "n_slides": 3,
  "template": "general",
  "tone": "professional",
  "verbosity": "concise"
}' 30

call_get "Search Presentations" "/presentation/search?title=Smoke"

echo
echo "=========================================================="
echo "  Creative smoke tests complete"
echo "=========================================================="
echo
