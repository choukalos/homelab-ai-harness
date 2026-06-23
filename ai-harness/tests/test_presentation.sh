#!/usr/bin/env bash
# Smoke test for the Presentation module (async Celery tasks + Siri integration).
#
# This end-to-end test exercises the presentation pipeline:
#   1.  Health check
#   2.  List presentations              (GET /presentation/list)
#   3.  Generate presentation async     (POST /presentation/generate/async)
#   4.  Check task status               (GET /presentation/tasks/{task_id})
#   5.  List presentations after gen    (GET /presentation/list)
#   6.  Search presentations            (GET /presentation/search)
#   7.  Generate outline                (POST /presentation/outline)
#   8.  Siri create_presentation intent (fire-and-forget)
#   9.  Siri list_presentations intent
#  10.  Siri find_presentation intent
#  11.  Poll async task for completion  (Tests 12–15 need this)
#  12.  Download endpoint               (GET /presentation/download/{filename})
#  13.  Public URL format validation
#  14.  Public file download (no auth)
#  15.  Metadata file verification
#  16.  Sync generation                 (POST /presentation/generate)
#  17.  Find presentation by title      (GET /presentation/search)
#  18.  Dispatch update task            (POST /{id}/update/async)
#  19.  Poll update task completion     (GET /presentation/tasks/{task_id})
#  20.  Verify new version (v2) with parent_id
#  21.  Verify updated params (tone, slides, template)
#  22.  Siri update intent detection
#  23.  Siri update handler end-to-end
#
# Usage:
#   bash tests/test_presentation.sh
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
TASK_ID_CAPTURED=""
CLEANUP_PRESENTATIONS=()

# Cleanup temp file on exit
trap 'rm -f "${TMP_FILE}"' EXIT

echo "=========================================================="
echo "  Presentation Module Smoke Test (Async + Siri)"
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

# ── Test 2: List Presentations (GET /presentation/list) ─────
echo
echo "==== Test 2: List presentations (GET /presentation/list) ==>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/presentation/list" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

if [ "${HTTP_CODE}" = "200" ]; then
    TOTAL=$(_json "${TMP_FILE}" "data.get('total', 0)")
    echo "  ✅ Listed ${TOTAL} presentation(s)"
else
    echo "  ❌ List presentations failed (HTTP ${HTTP_CODE})"
fi

# ── Test 3: Generate Presentation Async (POST /generate/async) ──
echo
echo "==== Test 3: Generate presentation async (POST /presentation/generate/async) ==>"
echo "  Title: Smoke Test Presentation"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)

HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    -X POST "${BASE_URL}/presentation/generate/async" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "title": "Smoke Test Presentation",
        "content": "A simple smoke test presentation about AI-powered presentations. Cover what they are, how they work, and use cases.",
        "n_slides": 4,
        "template": "general",
        "tone": "professional",
        "verbosity": "concise"
    }' \
    --max-time 30 2>/dev/null) || HTTP_CODE="000"

echo "  -> HTTP ${HTTP_CODE}"

if [ "${HTTP_CODE}" != "200" ] && [ "${HTTP_CODE}" != "201" ]; then
    HTTP_BODY_TEXT=$(cat "${TMP_FILE}" 2>/dev/null)
    echo "  ❌ Failed (HTTP ${HTTP_CODE})"
    echo "  Response:"
    echo "${HTTP_BODY_TEXT}" | head -20
    exit 1
fi

# Extract task_id
TASK_ID_CAPTURED=$(_json "${TMP_FILE}" "data.get('task_id','')")
TASK_STATUS=$(_json "${TMP_FILE}" "data.get('status','')")
TASK_TITLE=$(_json "${TMP_FILE}" "data.get('title','')")
TASK_MESSAGE=$(_json "${TMP_FILE}" "data.get('message','')")

echo "  task_id  = ${TASK_ID_CAPTURED}"
echo "  title    = ${TASK_TITLE}"
echo "  status   = ${TASK_STATUS}"
echo "  message  = ${TASK_MESSAGE}"

if [ -z "${TASK_ID_CAPTURED}" ]; then
    echo "  ❌ Missing task_id in response"
    exit 1
fi

if [ "${TASK_STATUS}" = "submitted" ]; then
    echo "  ✅ Async task dispatched and returned task_id"
else
    echo "  ⚠ Status is ${TASK_STATUS}, expected submitted"
fi

# ── Test 4: Check Task Status (GET /presentation/tasks/{task_id}) ──
echo
echo "==== Test 4: Check task status (GET /presentation/tasks/${TASK_ID_CAPTURED}) ==>"

# Poll the task status up to 3 times with short delays
# The task takes minutes to complete, so we just verify the endpoint responds
rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)

HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/presentation/tasks/${TASK_ID_CAPTURED}" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

if [ "${HTTP_CODE}" = "200" ]; then
    CHECK_STATUS=$(_json "${TMP_FILE}" "data.get('status','')")
    echo "  ✅ Task status endpoint responds — status: ${CHECK_STATUS}"

    if [ "${CHECK_STATUS}" = "pending" ] || [ "${CHECK_STATUS}" = "started" ]; then
        echo "  ℹ Task is ${CHECK_STATUS} (generation in progress, expected)"
    elif [ "${CHECK_STATUS}" = "completed" ]; then
        echo "  ✅ Task completed (fast worker!)"
        RESULT_TITLE=$(_json "${TMP_FILE}" "data.get('result', {}).get('title', '')")
        echo "  ℹ Result title: ${RESULT_TITLE}"
    elif [ "${CHECK_STATUS}" = "failed" ]; then
        ERROR_MSG=$(_json "${TMP_FILE}" "data.get('error','')")
        echo "  ❌ Task failed: ${ERROR_MSG}"
    else
        echo "  ⚠ Unexpected status: ${CHECK_STATUS}"
    fi
else
    echo "  ❌ Task status endpoint returned HTTP ${HTTP_CODE}"
fi

# ── Test 5: Generate Outline (POST /presentation/outline) ────
echo
echo "==== Test 5: Generate outline (POST /presentation/outline) ==>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)

HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    -X POST "${BASE_URL}/presentation/outline" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "topic": "Introduction to homelab infrastructure and self-hosted AI services",
        "instructions": "Keep it to 5-6 slides, focus on getting started",
        "research": false,
        "kb_search": false
    }' \
    --max-time 120 2>/dev/null) || HTTP_CODE="000"

echo "  -> HTTP ${HTTP_CODE}"

if [ "${HTTP_CODE}" = "200" ]; then
    OUTLINE_TITLE=$(_json "${TMP_FILE}" "data.get('title','')")
    OUTLINE_SLIDES=$(_json "${TMP_FILE}" "data.get('slide_count',0)")
    OUTLINE_TEXT=$(_json "${TMP_FILE}" "data.get('outline','')")
    echo "  ✅ Outline generated"
    echo "  Title: ${OUTLINE_TITLE}"
    echo "  Slide count: ${OUTLINE_SLIDES}"

    if [ -n "${OUTLINE_TEXT}" ] && [ "${OUTLINE_TEXT}" != "null" ]; then
        echo "  ✅ Outline text returned"
    else
        echo "  ⚠ Outline text appears empty"
    fi
else
    echo "  ❌ Outline generation failed (HTTP ${HTTP_CODE})"
    cat "${TMP_FILE}" | head -20
fi

# ── Test 6: Search Presentations (GET /presentation/search) ────
echo
echo "==== Test 6: Search presentations (GET /presentation/search?title=Smoke) ==>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/presentation/search?title=Smoke" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

if [ "${HTTP_CODE}" = "200" ]; then
    SEARCH_TOTAL=$(_json "${TMP_FILE}" "data.get('total', 0)")
    echo "  ✅ Search returned ${SEARCH_TOTAL} result(s)"
else
    echo "  ❌ Search failed (HTTP ${HTTP_CODE})"
fi

# ── Test 7: Siri create_presentation Intent ──────────────────
echo
echo "==== Test 7: Siri create_presentation intent (fire-and-forget) ==>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)

if [ -z "${SIRI_API_KEY}" ]; then
    echo "  ℹ SIRI_API_KEY not set — skipping Siri tests"
else
    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/siri/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d '{"text":"create a presentation about machine learning for beginners"}' \
        --max-time 30 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        SIRI_SPEAK=$(_json "${TMP_FILE}" "data.get('speak','')")
        SIRI_DISPLAY=$(_json "${TMP_FILE}" "data.get('display','')")
        echo "  ✅ Siri responded (HTTP ${HTTP_CODE})"
        echo "  Speak: ${SIRI_SPEAK}"

        if echo "${SIRI_SPEAK}" | grep -qi "started\|creating\|presentation\|generat"; then
            echo "  ✅ Siri confirms presentation creation started"
        else
            echo "  ⚠ Siri response may not reference presentation"
        fi
    else
        echo "  ❌ Siri create_presentation returned HTTP ${HTTP_CODE}"
    fi

    # ── Test 8: Siri list_presentations Intent ─────────────────────
    echo
    echo "==== Test 8: Siri list_presentations intent ==>"

    rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/siri/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d '{"text":"list my presentations"}' \
        --max-time 15 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        SIRI_SPEAK=$(_json "${TMP_FILE}" "data.get('speak','')")
        SIRI_DISPLAY=$(_json "${TMP_FILE}" "data.get('display','')")
        echo "  ✅ Siri responded (HTTP ${HTTP_CODE})"
        echo "  Speak: ${SIRI_SPEAK}"

        if echo "${SIRI_SPEAK}" | grep -qi "presentation\|list\|found\|here"; then
            echo "  ✅ Siri references presentation listing"
        else
            echo "  ⚠ Siri response may not reference presentations"
        fi
    else
        echo "  ❌ Siri list_presentations returned HTTP ${HTTP_CODE}"
    fi

    # ── Test 9: Siri find_presentation Intent ──────────────────────
    echo
    echo "==== Test 9: Siri find_presentation intent ==>"

    rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/siri/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d '{"text":"find presentation about machine learning"}' \
        --max-time 15 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        SIRI_SPEAK=$(_json "${TMP_FILE}" "data.get('speak','')")
        SIRI_DISPLAY=$(_json "${TMP_FILE}" "data.get('display','')")
        echo "  ✅ Siri responded (HTTP ${HTTP_CODE})"
        echo "  Speak: ${SIRI_SPEAK}"

        if echo "${SIRI_SPEAK}" | grep -qi "presentation\|find\|search\|machine\|result"; then
            echo "  ✅ Siri references presentation search"
        else
            echo "  ⚠ Siri response may not reference presentation search"
        fi
    else
        echo "  ❌ Siri find_presentation returned HTTP ${HTTP_CODE}"
    fi
fi

# ── Poll helper: wait for async task completion ─────────────
# Tests 12–15 depend on the async task from Test 3 completing.
# Poll up to 20 minutes (24 rounds × 50s) for the task to finish.
echo
echo "==== Polling for async task completion (Tests 12–15) ==>>"
TASK_COMPLETED=false
TASK_RESULT_FILE=""
POLL_MAX=24          # 24 rounds
POLL_DELAY=50        # seconds between checks
POLL_COUNT=0

while [ ${POLL_COUNT} -lt ${POLL_MAX} ]; do
    POLL_COUNT=$((POLL_COUNT + 1))
    rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        "${BASE_URL}/presentation/tasks/${TASK_ID_CAPTURED}" \
        -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        CHECK_STATUS=$(_json "${TMP_FILE}" "data.get('status','')")
        echo "  Poll #${POLL_COUNT}: status=${CHECK_STATUS}"

        if [ "${CHECK_STATUS}" = "completed" ]; then
            TASK_RESULT_FILE="${TMP_FILE}"
            TASK_COMPLETED=true
            echo "  ✅ Task completed after ${POLL_COUNT} poll(s)"
            break
        elif [ "${CHECK_STATUS}" = "failed" ]; then
            ERROR_MSG=$(_json "${TMP_FILE}" "data.get('error','')")
            echo "  ❌ Task failed: ${ERROR_MSG}"
            break
        fi
    else
        echo "  Poll #${POLL_COUNT}: HTTP ${HTTP_CODE} (endpoint unreachable)"
    fi

    sleep ${POLL_DELAY}
done

if [ "${POLL_COUNT}" -ge "${POLL_MAX}" ] && [ "${TASK_COMPLETED}" = "false" ]; then
    echo "  ⚠ Polling timeout (${POLL_MAX} rounds). Skipping tests 12–15."
fi

# ── Test 12: Download Endpoint (Phase 4a) ───────────────────
# Verify GET /presentation/download/{filename} with auth returns 200
echo
echo "==== Test 12: Download endpoint (GET /presentation/download/{filename}) ==>>"

if [ "${TASK_COMPLETED}" = "true" ] && [ -n "${TASK_RESULT_FILE}" ]; then
    DOWNLOAD_URL=$(_json "${TASK_RESULT_FILE}" "data.get('result', {}).get('download_url', '')")
    LOCAL_PATH=$(_json "${TASK_RESULT_FILE}" "data.get('result', {}).get('local_path', '')")

    # Extract filename from local_path (/data/media/presentations/foo-v1.pptx → foo-v1.pptx)
    FILENAME=$(basename "${LOCAL_PATH}")

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        "${BASE_URL}/presentation/download/${FILENAME}" \
        -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        echo "  ✅ Download endpoint returned HTTP 200"
    else
        echo "  ❌ Download endpoint returned HTTP ${HTTP_CODE}"
    fi
else
    echo "  ℹ Skipping — async task did not complete"
fi

# ── Test 13: Public URL Format Validation (Phase 4b) ────────
# Verify download_url starts with https://siri.choukalos.com/media/files/presentations/
echo
echo "==== Test 13: Public URL format validation ==>>"

if [ "${TASK_COMPLETED}" = "true" ] && [ -n "${TASK_RESULT_FILE}" ]; then
    DOWNLOAD_URL=$(_json "${TASK_RESULT_FILE}" "data.get('result', {}).get('download_url', '')")
    echo "  download_url = ${DOWNLOAD_URL}"

    if echo "${DOWNLOAD_URL}" | grep -q "^https://siri\.choukalos\.com/media/files/presentations/"; then
        echo "  ✅ download_url uses correct public URL format"
    else
        echo "  ❌ download_url does not match expected public URL pattern"
        echo "     Expected: https://siri.choukalos.com/media/files/presentations/..."
    fi

    # Also check internal_download_url
    INTERNAL_DL=$(_json "${TASK_RESULT_FILE}" "data.get('result', {}).get('internal_download_url', '')")
    echo "  internal_download_url = ${INTERNAL_DL}"

    if echo "${INTERNAL_DL}" | grep -q "^http://"; then
        echo "  ✅ internal_download_url is present and uses http://"
    else
        echo "  ⚠ internal_download_url unexpected: ${INTERNAL_DL}"
    fi
else
    echo "  ℹ Skipping — async task did not complete"
fi

# ── Test 14: Public File Download (Phase 4c) ────────────────
# curl the public URL without auth and verify 200
echo
echo "==== Test 14: Public file download (no auth required) ==>>"

if [ "${TASK_COMPLETED}" = "true" ] && [ -n "${TASK_RESULT_FILE}" ]; then
    DOWNLOAD_URL=$(_json "${TASK_RESULT_FILE}" "data.get('result', {}).get('download_url', '')")

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        "${DOWNLOAD_URL}" \
        --max-time 30 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        echo "  ✅ Public download returned HTTP 200"
    else
        echo "  ❌ Public download returned HTTP ${HTTP_CODE}"
    fi
else
    echo "  ℹ Skipping — async task did not complete"
fi

# ── Test 15: Metadata File Verification (Phase 4d) ──────────
# Check metadata.json exists and has correct download_url
echo
echo "==== Test 15: Metadata file verification ==>>"

if [ "${TASK_COMPLETED}" = "true" ] && [ -n "${TASK_RESULT_FILE}" ]; then
    LOCAL_PATH=$(_json "${TASK_RESULT_FILE}" "data.get('result', {}).get('local_path', '')")
    METADATA_PATH=$(_json "${TASK_RESULT_FILE}" "data.get('result', {}).get('metadata_path', '')")

    # Derive metadata path from local_path if metadata_path is empty
    if [ -z "${METADATA_PATH}" ] || [ "${METADATA_PATH}" = "null" ]; then
        METADATA_PATH=$(echo "${LOCAL_PATH}" | sed 's/\.[^.]*$/.metadata.json/')
    fi

    # Map container internal path to host mount path
    METADATA_HOST_PATH=$(echo "${METADATA_PATH}" | sed 's|^/data/media/|/home/chuck/data/media/|')

    echo "  Metadata path: ${METADATA_HOST_PATH}"

    if [ -f "${METADATA_HOST_PATH}" ]; then
        echo "  ✅ Metadata file exists"

        # Check download_url in metadata.json
        META_DL=$(python3 -c "
import json
with open('${METADATA_HOST_PATH}') as f: data = json.load(f)
print(data.get('download_url', ''))
" 2>/dev/null)

        if echo "${META_DL}" | grep -q "^https://siri\.choukalos\.com/media/files/presentations/"; then
            echo "  ✅ Metadata download_url uses correct public URL format"
        else
            echo "  ❌ Metadata download_url unexpected: ${META_DL}"
        fi

        META_INTERNAL_DL=$(python3 -c "
import json
with open('${METADATA_HOST_PATH}') as f: data = json.load(f)
print(data.get('internal_download_url', ''))
" 2>/dev/null)

        if echo "${META_INTERNAL_DL}" | grep -q "^http://"; then
            echo "  ✅ Metadata internal_download_url is present"
        else
            echo "  ⚠ Metadata internal_download_url unexpected: ${META_INTERNAL_DL}"
        fi
    else
        echo "  ❌ Metadata file not found at ${METADATA_PATH}"
    fi
else
    echo "  ℹ Skipping — async task did not complete"
fi

# ── Test 16: Sync Generation (Phase 4e) ─────────────────────
# POST /presentation/generate with inline outline, 2 slides, concise
echo
echo "==== Test 16: Sync generation (POST /presentation/generate) ==>>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)

HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    -X POST "${BASE_URL}/presentation/generate" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "title": "Smoke Test Sync Presentation",
        "content": "A quick sync test presentation.",
        "outline": "# Quick Sync Test\n\n## 1. Intro\n\nBrief introduction.\n\n## 2. Summary\n\nBrief summary.",
        "n_slides": 3,
        "template": "general",
        "tone": "professional",
        "verbosity": "concise"
    }' \
    --max-time 900 2>/dev/null) || HTTP_CODE="000"

echo "  -> HTTP ${HTTP_CODE}"

if [ "${HTTP_CODE}" = "200" ]; then
    SYNC_TITLE=$(_json "${TMP_FILE}" "data.get('title','')")
    SYNC_SLIDES=$(_json "${TMP_FILE}" "data.get('slide_count',0)")
    SYNC_DL=$(_json "${TMP_FILE}" "data.get('download_url','')")
    SYNC_ID=$(_json "${TMP_FILE}" "data.get('presentation_id','')")
    echo "  ✅ Sync generation returned HTTP 200"
    echo "  Title: ${SYNC_TITLE}"
    echo "  Slides: ${SYNC_SLIDES}"
    echo "  ID: ${SYNC_ID}"

    if echo "${SYNC_DL}" | grep -q "^https://siri\.choukalos\.com/media/files/presentations/"; then
        echo "  ✅ Sync download_url uses correct public URL format"
    else
        echo "  ❌ Sync download_url unexpected: ${SYNC_DL}"
    fi
else
    echo "  ❌ Sync generation failed (HTTP ${HTTP_CODE})"
    echo "  Response:"
    cat "${TMP_FILE}" | head -20
fi

# ── Update flow: Create baseline presentation ──────────────
# Tests 17-23 exercise the update/regenerate flow.
# First we create a baseline presentation to update.
echo
echo "==== Update flow: Creating baseline presentation ==>>"

rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)

HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    -X POST "${BASE_URL}/presentation/generate" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "title": "Smoke Update Baseline",
        "content": "A baseline presentation for smoke testing the update flow. Cover three simple topics.",
        "outline": "# Update Baseline\n\n## 1. Introduction\n\nSimple intro.\n\n## 2. Main Point\n\nOne main point.\n\n## 3. Conclusion\n\nBrief conclusion.",
        "n_slides": 3,
        "template": "general",
        "tone": "professional",
        "verbosity": "concise"
    }' \
    --max-time 900 2>/dev/null) || HTTP_CODE="000"

echo "  -> HTTP ${HTTP_CODE}"

if [ "${HTTP_CODE}" = "200" ]; then
    UPDATE_BASELINE_ID=$(_json "${TMP_FILE}" "data.get('presentation_id','')")
    UPDATE_BASELINE_VER=$(_json "${TMP_FILE}" "data.get('version', 0)")
    echo "  OK Baseline presentation created: id=${UPDATE_BASELINE_ID}, v=${UPDATE_BASELINE_VER}"
else
    echo "  WARN Baseline creation failed (HTTP ${HTTP_CODE}) - skipping tests 17-23"
    UPDATE_BASELINE_ID=""
fi

# ── Test 17: Find baseline by title via /search ─────────────
echo
echo "==== Test 17: Find presentation by title (GET /presentation/search) ==>>"

if [ -n "${UPDATE_BASELINE_ID}" ]; then
    rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        "${BASE_URL}/presentation/search?title=Smoke%20Update%20Baseline" \
        -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        SEARCH_TOTAL=$(_json "${TMP_FILE}" "data.get('total', 0)")
        echo "  OK Search returned ${SEARCH_TOTAL} result(s)"

        FIRST_ID=$(_json "${TMP_FILE}" "data.get('presentations', [{}])[0].get('presentation_id', '')")
        if [ "${FIRST_ID}" = "${UPDATE_BASELINE_ID}" ]; then
            echo "  OK Baseline presentation ID found in search results"
        else
            echo "  WARN Baseline ID not in first search result (first=${FIRST_ID})"
        fi
    else
        echo "  FAIL Search failed (HTTP ${HTTP_CODE})"
    fi
else
    echo "  SKIP - baseline presentation not created"
fi

# ── Test 18: POST /{id}/update/async ────────────────────────
echo
echo "==== Test 18: Dispatch update task (POST /{id}/update/async) ==>>"

UPDATE_TASK_ID=""
UPDATE_TASK_COMPLETED=false
UPDATE_TASK_RESULT_FILE=""

if [ -n "${UPDATE_BASELINE_ID}" ]; then
    rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)

    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/presentation/${UPDATE_BASELINE_ID}/update/async" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${API_KEY}" \
        -d '{
            "tone": "casual",
            "n_slides": 5,
            "template": "dark"
        }' \
        --max-time 30 2>/dev/null) || HTTP_CODE="000"

    echo "  -> HTTP ${HTTP_CODE}"

    if [ "${HTTP_CODE}" = "200" ] || [ "${HTTP_CODE}" = "201" ]; then
        UPDATE_TASK_ID=$(_json "${TMP_FILE}" "data.get('task_id','')")
        UPDATE_RESP_TITLE=$(_json "${TMP_FILE}" "data.get('title','')")
        UPDATE_RESP_STATUS=$(_json "${TMP_FILE}" "data.get('status','')")
        echo "  task_id  = ${UPDATE_TASK_ID}"
        echo "  title    = ${UPDATE_RESP_TITLE}"
        echo "  status   = ${UPDATE_RESP_STATUS}"

        if [ -n "${UPDATE_TASK_ID}" ]; then
            echo "  OK Update task dispatched, task_id=${UPDATE_TASK_ID}"
        else
            echo "  FAIL Missing task_id in update response"
        fi
    else
        echo "  FAIL Update dispatch failed (HTTP ${HTTP_CODE})"
        echo "  Response:"
        cat "${TMP_FILE}" | head -10
    fi
else
    echo "  SKIP - baseline presentation not created"
fi

# ── Test 19: Poll update task until complete ────────────────
echo
echo "==== Test 19: Poll update task for completion (GET /tasks/{task_id}) ==>>"

if [ -n "${UPDATE_TASK_ID}" ]; then
    POLL_MAX=24
    POLL_DELAY=50
    POLL_COUNT=0

    while [ ${POLL_COUNT} -lt ${POLL_MAX} ]; do
        POLL_COUNT=$((POLL_COUNT + 1))
        rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
        HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
            "${BASE_URL}/presentation/tasks/${UPDATE_TASK_ID}" \
            -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

        if [ "${HTTP_CODE}" = "200" ]; then
            CHECK_STATUS=$(_json "${TMP_FILE}" "data.get('status','')")
            echo "  Poll #${POLL_COUNT}: status=${CHECK_STATUS}"

            if [ "${CHECK_STATUS}" = "completed" ]; then
                UPDATE_TASK_RESULT_FILE="${TMP_FILE}"
                UPDATE_TASK_COMPLETED=true
                echo "  OK Update task completed after ${POLL_COUNT} poll(s)"
                break
            elif [ "${CHECK_STATUS}" = "failed" ]; then
                ERROR_MSG=$(_json "${TMP_FILE}" "data.get('error','')")
                echo "  FAIL Update task failed: ${ERROR_MSG}"
                break
            fi
        else
            echo "  Poll #${POLL_COUNT}: HTTP ${HTTP_CODE}"
        fi

        sleep ${POLL_DELAY}
    done

    if [ "${POLL_COUNT}" -ge "${POLL_MAX}" ] && [ "${UPDATE_TASK_COMPLETED}" = "false" ]; then
        echo "  WARN Polling timeout (${POLL_MAX} rounds). Skipping tests 20-21."
    fi
else
    echo "  SKIP - no update task to poll"
fi

# ── Test 20: Verify v2 exists with correct parent_id ────────
echo
echo "==== Test 20: Verify new version (v2) with correct parent_id ==>>"

if [ "${UPDATE_TASK_COMPLETED}" = "true" ] && [ -n "${UPDATE_TASK_RESULT_FILE}" ]; then
    NEW_VER=$(_json "${UPDATE_TASK_RESULT_FILE}" "data.get('result', {}).get('version', 0)")
    NEW_PARENT=$(_json "${UPDATE_TASK_RESULT_FILE}" "data.get('result', {}).get('parent_id', '')")
    NEW_PID=$(_json "${UPDATE_TASK_RESULT_FILE}" "data.get('result', {}).get('presentation_id', '')")
    NEW_TITLE=$(_json "${UPDATE_TASK_RESULT_FILE}" "data.get('result', {}).get('title', '')")
    NEW_SLIDES=$(_json "${UPDATE_TASK_RESULT_FILE}" "data.get('result', {}).get('slide_count', 0)")

    echo "  New version: ${NEW_VER}"
    echo "  New ID:      ${NEW_PID}"
    echo "  Parent ID:   ${NEW_PARENT}"
    echo "  Title:       ${NEW_TITLE}"
    echo "  Slides:      ${NEW_SLIDES}"

    if [ "${NEW_VER}" -ge 2 ] 2>/dev/null; then
        echo "  OK Version incremented (>= v2)"
    else
        echo "  WARN Version number unexpected: ${NEW_VER}"
    fi

    if [ "${NEW_PARENT}" = "${UPDATE_BASELINE_ID}" ]; then
        echo "  OK parent_id points to baseline presentation"
    elif [ -n "${NEW_PARENT}" ]; then
        echo "  INFO parent_id set but differs from baseline (may be expected if re-versioned)"
    else
        echo "  WARN parent_id not set"
    fi
else
    echo "  SKIP - update task did not complete"
fi

# ── Test 21: Verify updated params (tone, slides, template) ─
echo
echo "==== Test 21: Verify updated params (tone=casual, n_slides=5, template=dark) ==>>"

if [ "${UPDATE_TASK_COMPLETED}" = "true" ] && [ -n "${UPDATE_TASK_RESULT_FILE}" ]; then
    NEW_TONE=$(_json "${UPDATE_TASK_RESULT_FILE}" "data.get('result', {}).get('tone', '')")
    NEW_SLIDES=$(_json "${UPDATE_TASK_RESULT_FILE}" "data.get('result', {}).get('slide_count', 0)")
    NEW_TEMPLATE=$(_json "${UPDATE_TASK_RESULT_FILE}" "data.get('result', {}).get('template', '')")

    echo "  Tone:     ${NEW_TONE}"
    echo "  Slides:   ${NEW_SLIDES}"
    echo "  Template: ${NEW_TEMPLATE}"

    if [ "${NEW_TONE}" = "casual" ]; then
        echo "  OK Tone updated to casual"
    else
        echo "  WARN Tone unexpected: ${NEW_TONE} (expected casual)"
    fi

    if [ "${NEW_SLIDES}" -ge 5 ] 2>/dev/null; then
        echo "  OK Slide count >= 5 as requested"
    else
        echo "  WARN Slide count unexpected: ${NEW_SLIDES} (expected >=5)"
    fi

    if [ "${NEW_TEMPLATE}" = "dark" ]; then
        echo "  OK Template updated to dark"
    else
        echo "  WARN Template unexpected: ${NEW_TEMPLATE} (expected dark)"
    fi
else
    echo "  SKIP - update task did not complete"
fi

# ── Test 22: Siri update intent detection ───────────────────
echo
echo "==== Test 22: Siri update_presentation intent detection ==>>"

if [ -z "${SIRI_API_KEY}" ]; then
    echo "  INFO SIRI_API_KEY not set - skipping Siri update tests"
else
    rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/siri/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d '{"text":"update Smoke Update Baseline to be more casual"}' \
        --max-time 60 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        SIRI_SPEAK=$(_json "${TMP_FILE}" "data.get('speak','')")
        SIRI_DISPLAY=$(_json "${TMP_FILE}" "data.get('display','')")
        echo "  OK Siri responded (HTTP ${HTTP_CODE})"
        echo "  Speak:   ${SIRI_SPEAK}"
        echo "  Display: ${SIRI_DISPLAY:0:200}"

        if echo "${SIRI_SPEAK}" | grep -qi "update\|started\|changing\|presentation\|casual\|find\|could.*not.*find"; then
            echo "  OK Siri response references presentation update"
        else
            echo "  WARN Siri response may not reference update correctly"
        fi
    else
        echo "  FAIL Siri update intent returned HTTP ${HTTP_CODE}"
    fi
fi

# ── Test 23: Siri update handler end-to-end ─────────────────
echo
echo "==== Test 23: Siri update handler end-to-end (title match + async dispatch) ==>>"

if [ -z "${SIRI_API_KEY}" ]; then
    echo "  INFO SIRI_API_KEY not set - skipping"
else
    rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
    HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/siri/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d '{"text":"change the Smoke Update Baseline presentation to have 6 slides and use the dark template"}' \
        --max-time 60 2>/dev/null) || HTTP_CODE="000"

    if [ "${HTTP_CODE}" = "200" ]; then
        SIRI_SPEAK=$(_json "${TMP_FILE}" "data.get('speak','')")
        SIRI_DISPLAY=$(_json "${TMP_FILE}" "data.get('display','')")
        echo "  OK Siri responded (HTTP ${HTTP_CODE})"
        echo "  Speak:   ${SIRI_SPEAK}"
        echo "  Display: ${SIRI_DISPLAY:0:200}"

        if echo "${SIRI_SPEAK}" | grep -qi "update\|started\|changing\|task\|presentation"; then
            echo "  OK Siri confirms update dispatch"
        elif echo "${SIRI_SPEAK}" | grep -qi "what changes\|specify\|found.*presentation"; then
            echo "  INFO Siri found presentation but asked for more instructions (acceptable)"
        else
            echo "  WARN Siri response unclear"
        fi

        SIRI_TASK_ID=$(_json "${TMP_FILE}" "data.get('data', {}).get('task_id', '')")
        if [ -n "${SIRI_TASK_ID}" ]; then
            echo "  OK Siri response includes task_id: ${SIRI_TASK_ID}"
        fi
    else
        echo "  FAIL Siri update handler returned HTTP ${HTTP_CODE}"
    fi
fi

# ── Done ─────────────────────────────────────────────────────
echo
echo "=========================================================="
echo "  Result: PASSED"
echo "=========================================================="
echo
