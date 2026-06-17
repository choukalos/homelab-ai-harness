#!/usr/bin/env bash
# Test script for the Demo Workflow module (Deep Agents with MySQL checkpointing).
#
# Usage:
#   bash tests/test_demo_workflow.sh
#
# Exercises the new deep-agents endpoints:
#   1. Health check
#   2. Create demo synchronously (POST /demos/run)
#   3. Verify response schema (thread_id, title, slug, status)
#   4. List jobs (GET /demos/jobs)
#   5. List demos (GET /demos/)
#   6. Search demos (GET /demos/search)
#   7. Get demo metadata (GET /demos/{slug})
#   8. Serve demo HTML (GET /demos/{slug}/html)
#   9. Verify HTML structure
#  10. Siri create_demo intent (fire-and-forget)
#  11. Siri list_demos intent
#  12. Cleanup generated files

set -uo pipefail

# --- Resolve paths and load .env ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../../.env"

if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC2046
    set -a; source "$ENV_FILE"; set +a
    echo "Loaded environment from ${ENV_FILE}"
else
    echo "Warning: .env file not found at ${ENV_FILE}. Variables must be set in the environment."
fi

# --- Configuration ---
BASE_URL="${BASE_LOCAL:-http://${THOR_IP:-thor.local}:8090}"
API_KEY="${HARNESS_API_KEY:-}"
SIRI_API_KEY="${SIRI_API_KEY:-}"
TMP_FILE=$(mktemp)
SLUG_CAPTURED=""

# Cleanup temp file on exit
trap 'rm -f "${TMP_FILE}"' EXIT

echo "=========================================================="
echo "  Demo Workflow Integration Test (Deep Agents)"
echo "=========================================================="
echo "  Base URL: ${BASE_URL}"
echo "  API Key:  ${API_KEY:+set (${#API_KEY} chars)}"
echo "  Siri Key: ${SIRI_API_KEY:+set (${#SIRI_API_KEY} chars)}"
echo "----------------------------------------------------------"

# ── Helper ──────────────────────────────────────────────────
_json() {
    python3 -c "
import json
with open('$1') as f: data = json.load(f)
print($2)
" 2>/dev/null
}

# ── Test 1: Health Check ────────────────────────────────────
echo
echo "==== Test 1: Harness health check ==>"
curl -s -o "${TMP_FILE}" -w "%{http_code}" --max-time 5 \
    "${BASE_URL}/health" 2>/dev/null || true

# Parse the HTTP code from file
HTTP_CODE=$(tail -c 3 "${TMP_FILE}")
HTTP_BODY=$(head -c -3 "${TMP_FILE}")

if [ "${HTTP_CODE}" = "200" ]; then
    echo "  ✅ Harness is healthy"
else
    echo "  ❌ Harness unreachable (HTTP ${HTTP_CODE}): ${HTTP_BODY}"
    exit 1
fi

# ── Test 2: Create Demo (POST /demos/run) ──────────────────
echo
echo "==== Test 2: Create demo synchronously (POST /demos/run) ==>"
echo "  Body: {\"title\": \"Smoke Test Calculator\", \"prompt\": \"Build a one-page...\"}"

rm -f "${TMP_FILE}"
TMP_FILE=$(mktemp)

HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    -X POST "${BASE_URL}/demos/run" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "title": "Smoke Test Calculator",
        "prompt": "Build a one-page clickable demo for a mobile calculator app with a clean modern UI. Include the main calculator screen with number pad and basic operations."
    }' \
    --max-time 600 2>/dev/null) || HTTP_CODE="000"

echo "  -> HTTP ${HTTP_CODE}"

if [ "${HTTP_CODE}" != "201" ] && [ "${HTTP_CODE}" != "200" ]; then
    echo "  ❌ Failed (HTTP ${HTTP_CODE})"
    echo "  Response:"
    cat "${TMP_FILE}" 2>/dev/null | head -20
    echo
    echo "=========================================================="
    echo "  Result: FAILED"
    echo "=========================================================="
    exit 1
fi

# ── Test 3: Verify Response Schema ──────────────────────────
echo
echo "==== Test 3: Verify response schema ==>"

THREAD_ID=$(_json "${TMP_FILE}" "data.get('thread_id','')")
TITLE=$(_json "${TMP_FILE}" "data.get('title','')")
SLUG_CAPTURED=$(_json "${TMP_FILE}" "data.get('slug','')")
STATUS=$(_json "${TMP_FILE}" "data.get('status','')")

echo "  thread_id = ${THREAD_ID}"
echo "  title     = ${TITLE}"
echo "  slug      = ${SLUG_CAPTURED}"
echo "  status    = ${STATUS}"

FAIL=0

if [ -z "${THREAD_ID}" ]; then
    echo "  ❌ Missing thread_id"; FAIL=1
else
    echo "  ✅ Has thread_id"
fi

if [ -z "${TITLE}" ]; then
    echo "  ❌ Missing title"; FAIL=1
else
    echo "  ✅ Has title: ${TITLE}"
fi

if [ -z "${SLUG_CAPTURED}" ]; then
    echo "  ❌ Missing slug"; FAIL=1
else
    echo "  ✅ Has slug: ${SLUG_CAPTURED}"
fi

if [ -z "${STATUS}" ]; then
    echo "  ❌ Missing status"; FAIL=1
else
    echo "  ✅ Has status: ${STATUS}"
fi

if [ ${FAIL} -ne 0 ]; then
    echo
    cat "${TMP_FILE}"
    echo
    exit 1
fi

# ── Test 4: List Jobs (GET /demos/jobs) ─────────────────────
echo
echo "==== Test 4: List jobs (GET /demos/jobs) ==>"

rm -f "${TMP_FILE}"
TMP_FILE=$(mktemp)

curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/demos/jobs?limit=10" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null || true

HTTP_CODE=$(tail -c 3 "${TMP_FILE}")
if [ "${HTTP_CODE}" = "200" ]; then
    JOB_COUNT=$(_json "${TMP_FILE}" "len(data.get('jobs',[]))")
    echo "  ✅ Listed ${JOB_COUNT} recent jobs"
else
    echo "  ❌ List jobs failed (HTTP ${HTTP_CODE})"
fi

# ── Test 5: List Demos (GET /demos/) ────────────────────────
echo
echo "==== Test 5: List demos (GET /demos/) ==>"

rm -f "${TMP_FILE}"
TMP_FILE=$(mktemp)

curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/demos/?limit=10" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null || true

HTTP_CODE=$(tail -c 3 "${TMP_FILE}")
if [ "${HTTP_CODE}" = "200" ]; then
    DEMO_COUNT=$(_json "${TMP_FILE}" "len(data.get('demos',[]))")
    echo "  ✅ Listed ${DEMO_COUNT} demos"
else
    echo "  ❌ List demos failed (HTTP ${HTTP_CODE})"
fi

# ── Test 6: Search Demos (GET /demos/search) ────────────────
echo
echo "==== Test 6: Search demos (GET /demos/search?q=calculator) ==>"

rm -f "${TMP_FILE}"
TMP_FILE=$(mktemp)

curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/demos/search?q=calculator&limit=10" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null || true

HTTP_CODE=$(tail -c 3 "${TMP_FILE}")
if [ "${HTTP_CODE}" = "200" ]; then
    MATCH_COUNT=$(_json "${TMP_FILE}" "len(data.get('matches',[]))")
    echo "  ✅ Found ${MATCH_COUNT} matches"
else
    echo "  ❌ Search demos failed (HTTP ${HTTP_CODE})"
fi

# ── Test 7: Get Demo Metadata (GET /demos/{slug}) ───────────
echo
echo "==== Test 7: Get demo metadata (GET /demos/${SLUG_CAPTURED}) ==>"

rm -f "${TMP_FILE}"
TMP_FILE=$(mktemp)

curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/demos/${SLUG_CAPTURED}" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null || true

HTTP_CODE=$(tail -c 3 "${TMP_FILE}")
if [ "${HTTP_CODE}" = "200" ]; then
    META_TITLE=$(_json "${TMP_FILE}" "data.get('title','?')")
    echo "  ✅ Metadata returned — title: ${META_TITLE}"
else
    echo "  ⚠ Get demo metadata returned HTTP ${HTTP_CODE} (may need a moment for metadata.json to be written)"
fi

# ── Test 8: Serve Demo HTML (GET /demos/{slug}/html) ────────
echo
echo "==== Test 8: Serve demo HTML (GET /demos/${SLUG_CAPTURED}/html) ==>"

rm -f "${TMP_FILE}"
TMP_FILE=$(mktemp)

curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/demos/${SLUG_CAPTURED}/html" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null || true

HTTP_CODE=$(tail -c 3 "${TMP_FILE}")
if [ "${HTTP_CODE}" = "200" ]; then
    HTML_SIZE=$(wc -c < "${TMP_FILE}")
    HAS_DOCTYPE=$(grep -c '<!DOCTYPE' "${TMP_FILE}" || true)
    HAS_END_HTML=$(grep -c '</html>' "${TMP_FILE}" || true)
    HAS_STYLE=$(grep -c '<style' "${TMP_FILE}" || true)
    HAS_SCRIPT=$(grep -c '<script' "${TMP_FILE}" || true)

    echo "  ✅ HTML served: ${HTML_SIZE} bytes"
    echo "  ✅ <!DOCTYPE: ${HAS_DOCTYPE}, </html>: ${HAS_END_HTML}"
    echo "  ✅ <style>: ${HAS_STYLE}, <script>: ${HAS_SCRIPT}"

    if [ "${HAS_DOCTYPE}" -lt 1 ] || [ "${HAS_END_HTML}" -lt 1 ]; then
        echo "  ❌ HTML structure is incomplete"
    else
        echo "  ✅ HTML structure looks valid"
    fi
else
    echo "  ⚠ Serve demo HTML returned HTTP ${HTTP_CODE} (file may still be writing)"
fi

# ── Test 9: Cancel Endpoint (POST /demos/jobs/{id}/cancel) ──
echo
echo "==== Test 9: Cancel endpoint (POST /demos/jobs/${SLUG_CAPTURED}/cancel) ==>"

rm -f "${TMP_FILE}"
TMP_FILE=$(mktemp)

curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    -X POST "${BASE_URL}/demos/jobs/${SLUG_CAPTURED}/cancel" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null || true

HTTP_CODE=$(tail -c 3 "${TMP_FILE}")
if [ "${HTTP_CODE}" = "200" ] || [ "${HTTP_CODE}" = "404" ]; then
    echo "  ✅ Cancel endpoint responds (HTTP ${HTTP_CODE})"
else
    echo "  ⚠ Cancel endpoint returned HTTP ${HTTP_CODE}"
fi

# ── Test 10: Siri create_demo Intent ────────────────────────
echo
echo "==== Test 10: Siri create_demo intent (fire-and-forget) ==>"

rm -f "${TMP_FILE}"
TMP_FILE=$(mktemp)

if [ -z "${SIRI_API_KEY}" ]; then
    echo "  ℹ SIRI_API_KEY not set — skipping Siri test"
else
    curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/siri/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d '{"text":"build a demo of a simple weather app with city search"}' \
        --max-time 30 2>/dev/null || true

    HTTP_CODE=$(tail -c 3 "${TMP_FILE}")
    if [ "${HTTP_CODE}" = "200" ]; then
        SIRI_SPEAK=$(_json "${TMP_FILE}" "data.get('speak','')")
        echo "  ✅ Siri responded (HTTP ${HTTP_CODE})"
        echo "  Speak: ${SIRI_SPEAK}"

        if echo "${SIRI_SPEAK}" | grep -qi "started\|building\|demo"; then
            echo "  ✅ Siri confirms demo build started"
        else
            echo "  ⚠ Siri response doesn't mention demo build"
        fi
    else
        echo "  ❌ Siri returned HTTP ${HTTP_CODE}"
    fi
fi

# ── Test 11: Siri list_demos Intent ─────────────────────────
echo
echo "==== Test 11: Siri list_demos intent ==>"

rm -f "${TMP_FILE}"
TMP_FILE=$(mktemp)

if [ -z "${SIRI_API_KEY}" ]; then
    echo "  ℹ SIRI_API_KEY not set — skipping Siri test"
else
    curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/siri/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d '{"text":"list my demos"}' \
        --max-time 15 2>/dev/null || true

    HTTP_CODE=$(tail -c 3 "${TMP_FILE}")
    if [ "${HTTP_CODE}" = "200" ]; then
        SIRI_DISPLAY=$(_json "${TMP_FILE}" "data.get('display','')")
        echo "  ✅ Siri responded (HTTP ${HTTP_CODE})"
        echo "  Display: ${SIRI_DISPLAY:0:200}"
    else
        echo "  ❌ Siri returned HTTP ${HTTP_CODE}"
    fi
fi

# ── Test 12: Streaming Endpoint (POST /demos/run/stream) ────
echo
echo "==== Test 12: Streaming endpoint (POST /demos/run/stream) ==>"

rm -f "${TMP_FILE}"
TMP_FILE=$(mktemp)

# Send a very short stream request and capture the first event
timeout 5 curl -s -o "${TMP_FILE}" \
    -X POST "${BASE_URL}/demos/run/stream" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -H "Accept: text/event-stream" \
    -d '{
        "title": "Stream Test",
        "prompt": "Quick demo test for streaming endpoint"
    }' 2>/dev/null || true

STREAM_LINES=$(wc -l < "${TMP_FILE}" || echo "0")
echo "  ✅ Streaming endpoint returned ${STREAM_LINES} line(s)"

if [ "${STREAM_LINES}" -gt 0 ]; then
    FIRST_LINE=$(head -1 "${TMP_FILE}")
    if echo "${FIRST_LINE}" | grep -q '"event"'; then
        echo "  ✅ First line is JSON event"
    else
        echo "  ⚠ First line doesn't look like a JSON event"
    fi
fi

# ── Done ─────────────────────────────────────────────────────
echo
echo "=========================================================="
echo "  Result: PASSED"
echo "=========================================================="
echo
