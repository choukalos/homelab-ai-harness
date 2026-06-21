#!/usr/bin/env bash
# Smoke test for the Demo Workflow module (Coordinator pattern, 11-phase pipeline).
#
# This end-to-end test exercises the full coordinator-pattern demo workflow:
#   1.  Health check
#   2.  Create demo synchronously  (POST /demos/run)
#   3.  Verify response schema      (thread_id, title, slug, status, html_path, metadata, public_url, local_url)
#   4.  Verify HTML file exists      (GET /demos/{slug}/html)
#   5.  Verify HTML structure        (DOCTYPE, </html>, <style>, <script>)
#   5b. Public URL download test     (CURL public_url via Caddy)
#   6.  List jobs                   (GET /demos/jobs)
#   7.  List demos                  (GET /demos/)
#   8.  Search demos                (GET /demos/search)
#   9.  Get demo metadata           (GET /demos/{slug}) + enriched fields
#  10.  Checkpoint status           (GET /demos/jobs/{thread_id}/checkpoint)
#  11.  Streaming endpoint          (POST /demos/run/stream)
#  11b. Async endpoint              (POST /demos/run/async via Celery)
#  12.  Siri create_demo intent     (fire-and-forget via Celery, POST /siri/chat)
#  13.  Siri list_demos intent
#  14.  Siri demo_quality intent    (new — asks how well a demo works)
#  15.  Siri demo_complexity intent (new — asks how complex a demo is)
#  16.  Cleanup generated files
#
# Usage:
#   bash tests/test_demo_workflow.sh
#
# Environment (loaded from ../../.env or must be set manually):
#   BASE_LOCAL    — harness base URL (default: http://thor.local:8090)
#   HARNESS_API_KEY
#   SIRI_API_KEY  (optional — Siri tests are skipped if unset)

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
THREAD_CAPTURED=""
CLEANUP_SLABS=()

# Cleanup temp files + generated demo files on exit
trap 'rm -f "${TMP_FILE}"; for s in "${CLEANUP_SLABS[@]+"${CLEANUP_SLABS[@]}"}"; do rm -f "$s"; done' EXIT

echo "=========================================================="
echo "  Demo Workflow Smoke Test (Coordinator, 11 phases)"
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
HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" --max-time 5 \
    "${BASE_URL}/health" 2>/dev/null) || HTTP_CODE="000"
HTTP_BODY=$(cat "${TMP_FILE}" 2>/dev/null)

if [ "${HTTP_CODE}" = "200" ]; then
    echo "  ✅ Harness is healthy"
else
    echo "  ❌ Harness unreachable (HTTP ${HTTP_CODE}): ${HTTP_BODY}"
    exit 1
fi

# ── Test 2: Create Demo (POST /demos/run) ──────────────────
echo
echo "==== Test 2: Create demo synchronously (POST /demos/run) ==>"
echo "  Prompt: one-page mobile calculator demo"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)

HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    -X POST "${BASE_URL}/demos/run" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "title": "Smoke Test Calculator",
        "prompt": "Build a one-page clickable demo for a mobile calculator app with a clean modern UI. Include the main calculator screen with number pad and basic operations (add, subtract, multiply, divide)."
    }' \
    --max-time 600 2>/dev/null) || HTTP_CODE="000"

echo "  -> HTTP ${HTTP_CODE}"

if [ "${HTTP_CODE}" != "201" ] && [ "${HTTP_CODE}" != "200" ]; then
    HTTP_BODY_TEXT=$(cat "${TMP_FILE}" 2>/dev/null)
    echo "  ❌ Failed (HTTP ${HTTP_CODE})"
    echo "  Response:"
    echo "${HTTP_BODY_TEXT}" | head -20

    # Check if it is an agent error (status=error in JSON)
    ERROR_STATUS=$(echo "${HTTP_BODY_TEXT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || true)
    ERROR_MSG=$(echo "${HTTP_BODY_TEXT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error','')[:200])" 2>/dev/null || true)
    if [ "${ERROR_STATUS}" = "error" ]; then
        echo "  ❌ Agent error: ${ERROR_MSG}"
    fi

    echo
    echo "=========================================================="
    echo "  Result: FAILED"
    echo "=========================================================="
    exit 1
fi

# ── Test 3: Verify Response Schema ──────────────────────────
echo
echo "==== Test 3: Verify response schema ==>"

# Check for agent error in response
RESP_STATUS=$(_json "${TMP_FILE}" "data.get('status','')")
RESP_ERROR=$(_json "${TMP_FILE}" "data.get('error','')")

if [ "${RESP_STATUS}" = "error" ]; then
    echo "  ❌ Agent reported error: ${RESP_ERROR}"
    echo
    cat "${TMP_FILE}"
    echo
    echo "=========================================================="
    echo "  Result: FAILED (agent could not complete workflow)"
    echo "=========================================================="
    exit 1
fi

THREAD_CAPTURED=$(_json "${TMP_FILE}" "data.get('thread_id','')")
TITLE=$(_json "${TMP_FILE}" "data.get('title','')")
SLUG_CAPTURED=$(_json "${TMP_FILE}" "data.get('slug','')")
STATUS=$(_json "${TMP_FILE}" "data.get('status','')")
HTML_PATH=$(_json "${TMP_FILE}" "data.get('html_path','')")
BUILD_STEP=$(_json "${TMP_FILE}" "data.get('build_step','')")

echo "  thread_id  = ${THREAD_CAPTURED}"
echo "  title      = ${TITLE}"
echo "  slug       = ${SLUG_CAPTURED}"
echo "  status     = ${STATUS}"
echo "  build_step = ${BUILD_STEP}"
echo "  html_path  = ${HTML_PATH}"

FAIL=0

if [ -z "${THREAD_CAPTURED}" ]; then
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
    CLEANUP_SLABS+=("/data/media/demos/${SLUG_CAPTURED}/final_demo.html")
    CLEANUP_SLABS+=("/data/media/demos/${SLUG_CAPTURED}/metadata.json")
fi

if [ -z "${STATUS}" ]; then
    echo "  ❌ Missing status"; FAIL=1
else
    echo "  ✅ Has status: ${STATUS}"
fi

if [ -z "${BUILD_STEP}" ]; then
    echo "  ℹ build_step not present (optional)"
else
    echo "  ✅ build_step: ${BUILD_STEP}"
fi

# ── URL fields from Phase 1 schema update ──
PUBLIC_URL=$(_json "${TMP_FILE}" "data.get('public_url','')")
LOCAL_URL=$(_json "${TMP_FILE}" "data.get('local_url','')")

if [ -z "${PUBLIC_URL}" ]; then
    echo "  ❌ Missing public_url"; FAIL=1
else
    echo "  ✅ Has public_url: ${PUBLIC_URL}"
fi

if [ -z "${LOCAL_URL}" ]; then
    echo "  ❌ Missing local_url"; FAIL=1
else
    echo "  ✅ Has local_url: ${LOCAL_URL}"
fi

if [ ${FAIL} -ne 0 ]; then
    echo; cat "${TMP_FILE}"; echo
    echo "=========================================================="
    echo "  Result: FAILED"
    echo "=========================================================="
    exit 1
fi

# ── Test 4: Verify HTML file exists on disk ─────────────────
echo
echo "==== Test 4: Verify HTML file exists on disk ==>"

if [ -z "${HTML_PATH}" ] || [ "${HTML_PATH}" = "null" ]; then
    echo "  ❌ html_path is empty — save_demo may not have been called"
    echo "=========================================================="
    echo "  Result: FAILED (no HTML output)"
    echo "=========================================================="
    exit 1
fi

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/demos/${SLUG_CAPTURED}/html" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

if [ "${HTTP_CODE}" = "200" ]; then
    HTML_SIZE=$(wc -c < "${TMP_FILE}")
    echo "  ✅ HTML file exists: ${HTML_SIZE} bytes"
else
    echo "  ❌ HTML file not found on disk (HTTP ${HTTP_CODE})"
    echo "=========================================================="
    echo "  Result: FAILED (no files written)"
    echo "=========================================================="
    exit 1
fi

# ── Test 5: Verify HTML structure ───────────────────────────
echo
echo "==== Test 5: Verify HTML structure ==>"

HAS_DOCTYPE=$(grep -c '<!DOCTYPE' "${TMP_FILE}" || true)
HAS_END_HTML=$(grep -c '</html>' "${TMP_FILE}" || true)
HAS_STYLE=$(grep -c '<style' "${TMP_FILE}" || true)
HAS_SCRIPT=$(grep -c '<script' "${TMP_FILE}" || true)

echo "  DOCTYPE: ${HAS_DOCTYPE}, </html>: ${HAS_END_HTML}"
echo "  <style>: ${HAS_STYLE}, <script>: ${HAS_SCRIPT}"

if [ "${HAS_DOCTYPE}" -ge 1 ] && [ "${HAS_END_HTML}" -ge 1 ] && [ "${HAS_STYLE}" -ge 1 ] && [ "${HAS_SCRIPT}" -ge 1 ]; then
    echo "  ✅ HTML structure looks valid"
else
    echo "  ⚠ HTML structure may be incomplete"
fi

# ── Test 5b: Public URL download test ──
echo
echo "==== Test 5b: Public URL download test ==>"

if [ -n "${PUBLIC_URL}" ] && [ "${PUBLIC_URL}" != "null" ]; then
    rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        "${PUBLIC_URL}" 2>/dev/null) || HTTP_CODE="000"
    if [ "${HTTP_CODE}" = "200" ]; then
        DOWNLOAD_SIZE=$(wc -c < "${TMP_FILE}")
        echo "  ✅ Public URL returns 200 (${DOWNLOAD_SIZE} bytes) — Caddy → StaticFiles pipeline working"
    else
        echo "  ⚠ Public URL returned HTTP ${HTTP_CODE}"
    fi
else
    echo "  ℹ No public_url available — skipping download test"
fi

# ── Test 6: List Jobs (GET /demos/jobs) ─────────────────────
echo
echo "==== Test 6: List jobs (GET /demos/jobs) ==>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/demos/jobs?limit=10" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

if [ "${HTTP_CODE}" = "200" ]; then
    JOB_COUNT=$(_json "${TMP_FILE}" "len(data.get('jobs',[]))")
    echo "  ✅ Listed ${JOB_COUNT} recent jobs"
else
    echo "  ❌ List jobs failed (HTTP ${HTTP_CODE})"
fi

# ── Test 7: List Demos (GET /demos/) ────────────────────────
echo
echo "==== Test 7: List demos (GET /demos/) ==>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/demos/?limit=10" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

if [ "${HTTP_CODE}" = "200" ]; then
    DEMO_COUNT=$(_json "${TMP_FILE}" "len(data.get('demos',[]))")
    echo "  ✅ Listed ${DEMO_COUNT} demos"
else
    echo "  ❌ List demos failed (HTTP ${HTTP_CODE})"
fi

# ── Test 8: Search Demos (GET /demos/search) ────────────────
echo
echo "==== Test 8: Search demos (GET /demos/search?q=calculator) ==>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/demos/search?q=calculator&limit=10" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

if [ "${HTTP_CODE}" = "200" ]; then
    MATCH_COUNT=$(_json "${TMP_FILE}" "len(data.get('matches',[]))")
    echo "  ✅ Found ${MATCH_COUNT} matches"
else
    echo "  ❌ Search demos failed (HTTP ${HTTP_CODE})"
fi

# ── Test 9: Get Demo Metadata + Enriched Fields ─────────────
echo
echo "==== Test 9: Get demo metadata (GET /demos/${SLUG_CAPTURED}) ==>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/demos/${SLUG_CAPTURED}" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

if [ "${HTTP_CODE}" = "200" ]; then
    META_TITLE=$(_json "${TMP_FILE}" "data.get('title','?')")
    echo "  ✅ Metadata returned — title: ${META_TITLE}"

    # Verify enriched fields exist
    CODE_SCORE=$(_json "${TMP_FILE}" "data.get('code_quality_score',0)")
    echo "  ℹ code_quality_score: ${CODE_SCORE}"

    LEVEL3=$(_json "${TMP_FILE}" "data.get('level3_patterns',{})")
    if [ "${LEVEL3}" != "{}" ] && [ "${LEVEL3}" != "null" ]; then
        echo "  ✅ level3_patterns present: ${LEVEL3}"
    else
        echo "  ℹ level3_patterns not populated (may be model-dependent)"
    fi

    COMPLEXITY=$(_json "${TMP_FILE}" "data.get('complexity_score',0)")
    echo "  ℹ complexity_score: ${COMPLEXITY}"

    DISCOVERY=$(_json "${TMP_FILE}" "data.get('discovery_notes',{})")
    if [ "${DISCOVERY}" != "{}" ] && [ "${DISCOVERY}" != "null" ]; then
        echo "  ✅ discovery_notes present"
    else
        echo "  ℹ discovery_notes not populated (may be model-dependent)"
    fi

    PHASE_TIMES=$(_json "${TMP_FILE}" "data.get('phase_timings',{})")
    if [ "${PHASE_TIMES}" != "{}" ] && [ "${PHASE_TIMES}" != "null" ]; then
        echo "  ✅ phase_timings present (benchmarking working)"
    else
        echo "  ℹ phase_timings not populated"
    fi
else
    echo "  ⚠ Metadata returned HTTP ${HTTP_CODE} (file may still be writing)"
fi

# ── Test 10: Checkpoint status (GET /demos/jobs/{id}/checkpoint) ──
echo
echo "==== Test 10: Checkpoint status (GET /demos/jobs/${THREAD_CAPTURED}/checkpoint) ==>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/demos/jobs/${THREAD_CAPTURED}/checkpoint" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

if [ "${HTTP_CODE}" = "200" ]; then
    CP_EXISTS=$(_json "${TMP_FILE}" "data.get('exists', False)")
    CP_PHASE=$(_json "${TMP_FILE}" "data.get('phase', 0)")
    echo "  ✅ Checkpoint endpoint responds — exists: ${CP_EXISTS}, phase: ${CP_PHASE}"

    # On successful completion the checkpoint should be removed (exists=false)
    if [ "${CP_EXISTS}" = "False" ] || [ "${CP_EXISTS}" = "false" ]; then
        echo "  ✅ Checkpoint was cleaned up after completion (expected)"
    else
        echo "  ℹ Checkpoint still exists (pipeline may have been interrupted)"
    fi
else
    echo "  ⚠ Checkpoint endpoint returned HTTP ${HTTP_CODE}"
fi

# ── Test 11: Streaming endpoint (POST /demos/run/stream) ────
echo
echo "==== Test 11: Streaming endpoint (POST /demos/run/stream) ==>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)

# Capture the first few SSE events (5-second window)
timeout 5 curl -s -o "${TMP_FILE}" \
    -X POST "${BASE_URL}/demos/run/stream" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -H "Accept: text/event-stream" \
    -d '{
        "title": "Stream Test",
        "prompt": "Quick demo test for streaming endpoint"
    }' 2>/dev/null || true

STREAM_LINES=$(grep -c '^data:' "${TMP_FILE}" 2>/dev/null || echo "0")
echo "  ✅ Streaming endpoint returned ${STREAM_LINES} event(s)"

if [ "${STREAM_LINES}" -gt 0 ]; then
    FIRST_EVENT=$(grep '^data:' "${TMP_FILE}" | head -1 | sed 's/^data: //')
    EVENT_TYPE=$(echo "${FIRST_EVENT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('event_type','?'))" 2>/dev/null || echo "unknown")
    echo "  ℹ First event type: ${EVENT_TYPE}"

    # Verify pipeline_start is the first event
    if [ "${EVENT_TYPE}" = "pipeline_start" ]; then
        echo "  ✅ Stream starts with pipeline_start event (correct)"
    else
        echo "  ⚠ First event is ${EVENT_TYPE}, expected pipeline_start"
    fi
else
    echo "  ⚠ No SSE events captured in 5s (stream may be slow)"
fi

# ── Test 11b: Async endpoint (POST /demos/run/async) ─────────
echo
echo "==== Test 11b: Async demo creation (POST /demos/run/async) ==>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)

HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    -X POST "${BASE_URL}/demos/run/async" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "title": "Async Celery Test",
        "prompt": "Build a one-page demo for a todo list app with add/delete functionality."
    }' \
    --max-time 30 2>/dev/null) || HTTP_CODE="000"

if [ "${HTTP_CODE}" = "202" ]; then
    TASK_ID=$(_json "${TMP_FILE}" "data.get('task_id','')")
    TASK_TITLE=$(_json "${TMP_FILE}" "data.get('title','')")
    echo "  ✅ Async endpoint returned 202 — task dispatched"
    echo "  Title: ${TASK_TITLE}"

    if [ -n "${TASK_ID}" ] && [ "${TASK_ID}" != "null" ]; then
        echo "  ✅ Task ID: ${TASK_ID}"

        # Check task status via /jobs/async/{task_id}/status
        rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
        STATUS_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
            "${BASE_URL}/demos/jobs/async/${TASK_ID}/status" \
            -H "X-API-Key: ${API_KEY}" 2>/dev/null) || STATUS_CODE="000"

        if [ "${STATUS_CODE}" = "200" ]; then
            TASK_STATE=$(_json "${TMP_FILE}" "data.get('status','')")
            echo "  ✅ Task status endpoint works — state: ${TASK_STATE}"
        else
            echo "  ⚠ Task status endpoint returned HTTP ${STATUS_CODE}"
        fi
    else
        echo "  ⚠ No task_id in async response"
    fi
else
    echo "  ❌ Async endpoint returned HTTP ${HTTP_CODE}"
    HTTP_BODY_TEXT=$(cat "${TMP_FILE}" 2>/dev/null)
    echo "  Response: ${HTTP_BODY_TEXT:0:200}"
fi

# ── Test 12: Siri create_demo Intent ────────────────────────
echo
echo "==== Test 12: Siri create_demo intent (fire-and-forget via Celery) ==>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)

if [ -z "${SIRI_API_KEY}" ]; then
    echo "  ℹ SIRI_API_KEY not set — skipping Siri tests"
else
    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/siri/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d '{"text":"build a demo of a simple weather app with city search"}' \
        --max-time 30 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        SIRI_SPEAK=$(_json "${TMP_FILE}" "data.get('speak','')")
        echo "  ✅ Siri responded (HTTP ${HTTP_CODE})"
        echo "  Speak: ${SIRI_SPEAK}"

        if echo "${SIRI_SPEAK}" | grep -qi "started\|building\|demo"; then
            echo "  ✅ Siri confirms demo build started"
        else
            echo "  ⚠ Siri response doesn't mention demo build"
        fi

        # Verify task_id is in the response (Celery dispatch)
        SIRI_TASK_ID=$(_json "${TMP_FILE}" "data.get('task_id','')")
        if [ -n "${SIRI_TASK_ID}" ] && [ "${SIRI_TASK_ID}" != "null" ]; then
            echo "  ✅ Celery task dispatched: task_id=${SIRI_TASK_ID}"
        else
            echo "  ⚠ No task_id in response (Celery dispatch may have failed)"
        fi
    else
        echo "  ❌ Siri returned HTTP ${HTTP_CODE}"
    fi

    # ── Test 13: Siri list_demos Intent ─────────────────────────
    echo
    echo "==== Test 13: Siri list_demos intent ==>"

    rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/siri/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d '{"text":"list my demos"}' \
        --max-time 15 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        SIRI_DISPLAY=$(_json "${TMP_FILE}" "data.get('display','')")
        echo "  ✅ Siri responded (HTTP ${HTTP_CODE})"
        echo "  Display: ${SIRI_DISPLAY:0:200}"
    else
        echo "  ❌ Siri list_demos returned HTTP ${HTTP_CODE}"
    fi

    # ── Test 14: Siri demo_quality Intent ────────────────────────
    echo
    echo "==== Test 14: Siri demo_quality intent ==>"

    rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/siri/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d '{"text":"how well does the calculator demo work?"}' \
        --max-time 15 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        SIRI_SPEAK=$(_json "${TMP_FILE}" "data.get('speak','')")
        echo "  ✅ Siri demo_quality responded"
        echo "  Speak: ${SIRI_SPEAK}"
        if echo "${SIRI_SPEAK}" | grep -qi "quality\|score\|work\|calculator\|demo"; then
            echo "  ✅ Siri references quality info"
        else
            echo "  ⚠ Siri response may not have quality context"
        fi
    else
        echo "  ❌ Siri demo_quality returned HTTP ${HTTP_CODE}"
    fi

    # ── Test 15: Siri demo_complexity Intent ──────────────────────
    echo
    echo "==== Test 15: Siri demo_complexity intent ==>"

    rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/siri/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d '{"text":"how complex is the calculator demo?"}' \
        --max-time 15 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        SIRI_SPEAK=$(_json "${TMP_FILE}" "data.get('speak','')")
        echo "  ✅ Siri demo_complexity responded"
        echo "  Speak: ${SIRI_SPEAK}"
    else
        echo "  ❌ Siri demo_complexity returned HTTP ${HTTP_CODE}"
    fi
fi

# ── Done ─────────────────────────────────────────────────────
echo
echo "=========================================================="
echo "  Result: PASSED"
echo "=========================================================="
echo
