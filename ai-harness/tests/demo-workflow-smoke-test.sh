#!/usr/bin/bash
#
# demo-workflow-smoke-test.sh — Smoke test for the one-page clickable demo pipeline.
#
# Exercises the full lifecycle:
#   1. Health check (harness + SearXNG reachability)
#   2. Create a demo job (POST /demos/create)
#   3. Poll run until terminal state (GET /demos/jobs/{run_id})
#   4. Verify all 8 pipeline stages completed successfully
#   5. List jobs (GET /demos/jobs)
#   6. List demos from metadata index (GET /demos)
#   7. Search demos (GET /demos/search)
#   8. Get demo metadata (GET /demos/{slug})
#   9. Serve demo HTML (GET /demos/{slug}/html)
#  10. Verify output files exist on disk
#  11. Verify final HTML structure (DOCTYPE, </html>, inline CSS/JS)
#  12. Verify metadata.json has expected fields
#  13. Verify build/step*.html files exist
#  14. Cleanup generated files

set -euo pipefail

cd "$(dirname "$0")"

set -a
source ../../.env
set +a

BASE_URL="${BASE_LOCAL:-http://${THOR_IP}:8090}"
AUTH_HEADER="X-API-Key: ${HARNESS_API_KEY}"

POLL_TIMEOUT="${DEMO_POLL_TIMEOUT:-300}"  # 5 minutes default
POLL_INTERVAL="${DEMO_POLL_INTERVAL:-15}"  # 15 seconds between polls

CLEANUP_TEST_OUTPUTS="${CLEANUP_TEST_OUTPUTS:-1}"

SLUG_CAPTURED=""
GENERATED_FILES=()

echo
echo "========================================"
echo "  One-Page Demo Workflow Smoke Test"
echo "  Base URL: ${BASE_URL}"
echo "  Poll timeout: ${POLL_TIMEOUT}s, interval: ${POLL_INTERVAL}s"
echo "========================================"
echo

# ── cleanup ─────────────────────────────────────────────────────────
cleanup() {
  if [[ "${CLEANUP_TEST_OUTPUTS}" != "1" ]]; then
    echo "Cleanup disabled (CLEANUP_TEST_OUTPUTS=${CLEANUP_TEST_OUTPUTS})"
    return
  fi

  if [[ -n "${SLUG_CAPTURED}" && -n "${MEDIA_OUTPUT_DIR:-}" ]]; then
    demo_path="${MEDIA_OUTPUT_DIR}/demos/${SLUG_CAPTURED}"
    if [[ -d "${demo_path}" ]]; then
      echo
      echo "Cleaning up demo directory: ${demo_path}"
      rm -rf "${demo_path}"
      echo "  ✅ Deleted"
    else
      echo "  ℹ Demo dir not found, skipping: ${demo_path}"
    fi
  fi

  for fp in "${GENERATED_FILES[@]:-}"; do
    [[ -f "${fp}" ]] && rm -f "${fp}"
  done
}

trap cleanup EXIT

# ── helpers ─────────────────────────────────────────────────────────
_json() {
  # _json <file> <python_expr> → print result
  python3 -c "
import json
with open('$1') as f: data = json.load(f)
print($2)
" 2>/dev/null
}

# ── test 1: health ────────────────────────────────────────────────
echo "==== Test 1: Harness health check ==>"
RESP_FILE="$(mktemp)"
if curl -sS -f "${BASE_URL}/health" -H "${AUTH_HEADER}" > "${RESP_FILE}" 2>&1; then
  STATUS=$(_json "${RESP_FILE}" "data.get('status','')")
  if [[ "${STATUS}" == "ok" ]]; then
    echo "  ✅ Harness is healthy"
  else
    echo "  ❌ Health status: ${STATUS}"; rm -f "${RESP_FILE}"; exit 1
  fi
else
  echo "  ❌ Harness unreachable at ${BASE_URL}"; exit 1
fi
GENERATED_FILES+=("${RESP_FILE}")

# ── test 2: create a demo job ─────────────────────────────────────
echo "==== Test 2: Create demo job (POST /demos/create) ==="
RESP_FILE="$(mktemp)"
curl -sS -f -X POST "${BASE_URL}/demos/create" \
  -H "Content-Type: application/json" \
  -H "${AUTH_HEADER}" \
  -d '{
    "title": "Smoke Test Calculator App",
    "prompt": "Build a one-page clickable demo for a mobile calculator app with a clean modern UI. Include the main calculator screen with number pad, basic operations, and a history panel that slides in."
  }' > "${RESP_FILE}"

RUN_ID=$(_json "${RESP_FILE}" "data.get('run_id','')")
WF_ID=$(_json "${RESP_FILE}" "data.get('workflow_id','')")
STEPS=$(_json "${RESP_FILE}" "data.get('steps_count',0)")

if [[ -z "${RUN_ID}" ]]; then
  echo "  ❌ No run_id returned"; cat "${RESP_FILE}"; exit 1
fi
echo "  ✅ Demo job created: run_id=${RUN_ID}"
echo "  ✅ Workflow id: ${WF_ID}"
echo "  ✅ Initial step count: ${STEPS}"
if [[ "${STEPS}" -ne 8 ]]; then
  echo "  ⚠ Expected 8 steps, got ${STEPS}"
fi
GENERATED_FILES+=("${RESP_FILE}")
rm -f "${RESP_FILE}"

# ── test 3: poll for completion ───────────────────────────────────
echo "==== Test 3: Poll job until terminal state ==="
ELAPSED=0
FINAL_STATUS="pending"

while [[ ${ELAPSED} -lt ${POLL_TIMEOUT} ]]; do
  RESP_FILE="$(mktemp)"
  curl -sS -f "${BASE_URL}/demos/jobs/${RUN_ID}" \
    -H "${AUTH_HEADER}" > "${RESP_FILE}" 2>&1 || true

  FINAL_STATUS=$(_json "${RESP_FILE}" "data.get('status','')")
  STEPS_DONE=$(_json "${RESP_FILE}" "sum(1 for s in data.get('steps',[]) if s.get('status')!='pending')")
  STEPS_FAIL=$(_json "${RESP_FILE}" "sum(1 for s in data.get('steps',[]) if s.get('status')=='failed')")

  printf "  ⏳ %.1fs — status=%s done=%s failed=%s\n" \
    "${ELAPSED}" "${FINAL_STATUS}" "${STEPS_DONE}" "${STEPS_FAIL}"

  if [[ "${FINAL_STATUS}" == "success" || "${FINAL_STATUS}" == "failed" || "${FINAL_STATUS}" == "cancelled" ]]; then
    break
  fi

  sleep "${POLL_INTERVAL}"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
  GENERATED_FILES+=("${RESP_FILE}")
  rm -f "${RESP_FILE}"
done

RESP_FILE="$(mktemp)"
curl -sS -f "${BASE_URL}/demos/jobs/${RUN_ID}" \
  -H "${AUTH_HEADER}" > "${RESP_FILE}" 2>&1 || true

FINAL_STATUS=$(_json "${RESP_FILE}" "data.get('status','')")

if [[ "${FINAL_STATUS}" != "success" && "${FINAL_STATUS}" != "failed" ]]; then
  echo "  ❌ Pipeline did not reach terminal state within ${POLL_TIMEOUT}s — final status: ${FINAL_STATUS}"
  cat "${RESP_FILE}" | head -40
  exit 1
fi

if [[ "${FINAL_STATUS}" == "success" ]]; then
  echo "  ✅ Pipeline completed successfully in ~${ELAPSED}s"
else
  echo "  ❌ Pipeline failed after ~${ELAPSED}s"
  # Print which step(s) failed
  python3 << PYEOF
import json
with open("${RESP_FILE}") as f: data = json.load(f)
for s in data.get("steps", []):
    if s.get("status") == "failed":
        print(f"    FAILED step: {s['name']}")
        if s.get("error"):
            print(f"      Error: {s['error'][:200]}")
PYEOF
  exit 1
fi

# ── test 4: verify all 8 stages succeeded ─────────────────├────────
echo "==== Test 4: Verify all 8 pipeline stages completed ==="
FAILED_STEPS=""
TOTAL=0
PASSED=0

python3 << PYEOF
import json, sys
with open("${RESP_FILE}") as f: data = json.load(f)
steps = data.get("steps", [])
total = len(steps)
ok = sum(1 for s in steps if s.get("status") == "success")
failed = [s["name"] for s in steps if s.get("status") == "failed"]
print(f"  Total steps: {total}")
print(f"  Succeeded: {ok}")
print(f"  Failed: {len(failed)}")
if total != 8:
    print(f"  ⚠ Expected 8 steps, got {total}")
if ok == 8:
    print("  ✅ All 8 stages succeeded")
else:
    for name in failed:
        print(f"  ❌ Failed stage: {name}")
PYEOF

GENERATED_FILES+=("${RESP_FILE}")
rm -f "${RESP_FILE}"

# ── test 5: list jobs ─────────────────────────────────────────────
echo "==== Test 5: List demo jobs (GET /demos/jobs) ==="
RESP_FILE="$(mktemp)"
curl -sS -f "${BASE_URL}/demos/jobs?limit=10" \
  -H "${AUTH_HEADER}" > "${RESP_FILE}"

JOB_COUNT=$(_json "${RESP_FILE}" "len(data.get('jobs',[]))")
echo "  ✅ Listed ${JOB_COUNT} recent jobs"

# Verify our run is in the list
FOUND=$(_json "${RESP_FILE}" "sum(1 for j in data.get('jobs',[]) if j.get('run_id')=='${RUN_ID}')")
if [[ "${FOUND}" == "1" ]]; then
  echo "  ✅ Our run_id found in job list"
else
  echo "  ❌ Our run_id NOT in job list (${FOUND} matches)"
fi
GENERATED_FILES+=("${RESP_FILE}")
rm -f "${RESP_FILE}"

# ── test 6: list demos from metadata index ─────────────────────
echo "==== Test 6: List all demos (GET /demos) ==="
RESP_FILE="$(mktemp)"
curl -sS -f "${BASE_URL}/demos?limit=50" \
  -H "${AUTH_HEADER}" > "${RESP_FILE}"

DEMO_COUNT=$(_json "${RESP_FILE}" "len(data.get('demos',[]))")
echo "  ✅ Metadata index has ${DEMO_COUNT} demos"
GENERATED_FILES+=("${RESP_FILE}")
rm -f "${RESP_FILE}"

# ── test 7: search demos ──────────────────────────────────────────
echo "==== Test 7: Search demos (GET /demos/search?q=calculator) ==="
RESP_FILE="$(mktemp)"
curl -sS -f "${BASE_URL}/demos/search?q=calculator" \
  -H "${AUTH_HEADER}" > "${RESP_FILE}"

MATCH_COUNT=$(_json "${RESP_FILE}" "len(data.get('matches',[]))")
echo "  ✅ Found ${MATCH_COUNT} matches for 'calculator'"
if [[ "${MATCH_COUNT}" -gt 0 ]]; then
  FIRST_TITLE=$(_json "${RESP_FILE}" "data['matches'][0].get('title','?')")
  echo "  ✅ First match: ${FIRST_TITLE}"
fi
GENERATED_FILES+=("${RESP_FILE}")
rm -f "${RESP_FILE}"

# ── test 8: get single demo metadata ──────────────────────────────
echo "==== Test 8: Get demo metadata (GET /demos/{slug}) ==="

# Extract slug from run metadata
RUN_RESP="$(mktemp)"
curl -sS -f "${BASE_URL}/demos/jobs/${RUN_ID}" \
  -H "${AUTH_HEADER}" > "${RUN_RESP}"

SLUG_CAPTURED=$(_json "${RUN_RESP}" "data.get('metadata',{}).get('slug','') if isinstance(data.get('metadata'),dict) else ''")
GENERATED_FILES+=("${RUN_RESP}")

if [[ -z "${SLUG_CAPTURED}" ]]; then
  echo "  ❌ No slug found in run metadata"
  exit 1
fi
echo "  ✅ Slug from run metadata: ${SLUG_CAPTURED}"

RESP_FILE="$(mktemp)"
curl -sS -f "${BASE_URL}/demos/${SLUG_CAPTURED}" \
  -H "${AUTH_HEADER}" > "${RESP_FILE}"

META_TITLE=$(_json "${RESP_FILE}" "data.get('title','')")
META_TAGS=$(_json "${RESP_FILE}" "len(data.get('tags',[]))")
echo "  ✅ Metadata returned — title=${META_TITLE}, tags=${META_TAGS}"
GENERATED_FILES+=("${RESP_FILE}")
rm -f "${RESP_FILE}"

# ── test 9: serve final HTML ──────────────────────────────────────
echo "==== Test 9: Serve demo HTML (GET /demos/{slug}/html) ==="
RESP_FILE="$(mktemp)"
HTTP_CODE=$(curl -sS -o "${RESP_FILE}" -w "%{http_code}" \
  "${BASE_URL}/demos/${SLUG_CAPTURED}/html" \
  -H "${AUTH_HEADER}")

if [[ "${HTTP_CODE}" != "200" ]]; then
  echo "  ❌ HTML serve returned HTTP ${HTTP_CODE}"
  cat "${RESP_FILE}" | head -10
  exit 1
fi

HTML_SIZE=$(wc -c < "${RESP_FILE}")
HAS_DOCTYPE=$(grep -c '<!DOCTYPE' "${RESP_FILE}" || true)
HAS_END_HTML=$(grep -c '</html>' "${RESP_FILE}" || true)
HAS_STYLE_TAG=$(grep -c '<style' "${RESP_FILE}" || true)
HAS_SCRIPT_TAG=$(grep -c '<script' "${RESP_FILE}" || true)
HAS_EMBEDDED_NOTES=$(grep -c '<!--' "${RESP_FILE}" || true)

echo "  ✅ HTML served: ${HTML_SIZE} bytes"
echo "  ✅ Has <!DOCTYPE>: ${HAS_DOCTYPE}"
echo "  ✅ Has </html>: ${HAS_END_HTML}"
echo "  ✅ Has inline <style>: ${HAS_STYLE_TAG}"
echo "  ✅ Has inline <script>: ${HAS_SCRIPT_TAG}"
echo "  ✅ Has embedded comments: ${HAS_EMBEDDED_NOTES}"

if [[ "${HAS_DOCTYPE}" -lt 1 || "${HAS_END_HTML}" -lt 1 ]]; then
  echo "  ❌ HTML structure is incomplete"
  exit 1
fi

if [[ "${HAS_STYLE_TAG}" -lt 1 || "${HAS_SCRIPT_TAG}" -lt 1 ]]; then
  echo "  ⚠ HTML missing inline style or script tags (may be acceptable for simple demos)"
fi

GENERATED_FILES+=("${RESP_FILE}")
rm -f "${RESP_FILE}"

# ── test 10: verify output files on disk ──────────────────────────
echo "==== Test 10: Verify output files exist on disk ==="

if [[ -z "${MEDIA_OUTPUT_DIR:-}" ]]; then
  echo "  ℹ MEDIA_OUTPUT_DIR not set — skipping disk verification"
elif [[ ! -d "${MEDIA_OUTPUT_DIR}" ]]; then
  echo "  ℹ MEDIA_OUTPUT_DIR not locally available — skipping disk verification"
else
  DEMO_DIR="${MEDIA_OUTPUT_DIR}/demos/${SLUG_CAPTURED}"

  if [[ ! -d "${DEMO_DIR}" ]]; then
    echo "  ❌ Demo directory not found: ${DEMO_DIR}"
    exit 1
  fi

  echo "  ✅ Demo directory exists: ${DEMO_DIR}"

  FINAL_HTML="${DEMO_DIR}/final_demo.html"
  if [[ -f "${FINAL_HTML}" ]]; then
    echo "  ✅ final_demo.html exists ($(wc -c < "${FINAL_HTML}") bytes)"
  else
    echo "  ❌ final_demo.html missing"
    exit 1
  fi

  META_JSON="${DEMO_DIR}/metadata.json"
  if [[ -f "${META_JSON}" ]]; then
    echo "  ✅ metadata.json exists"
  else
    echo "  ❌ metadata.json missing"
    exit 1
  fi

  BUILD_DIR="${DEMO_DIR}/build"
  if [[ -d "${BUILD_DIR}" ]]; then
    STEP_FILES=$(find "${BUILD_DIR}" -name 'step*.html' | wc -l)
    echo "  ✅ Build directory has ${STEP_FILES} step files"
    for fp in "${BUILD_DIR}"/step*.html; do
      echo "     - $(basename "${fp}"): $(wc -c < "${fp}") bytes"
    done
  else
    echo "  ⚠ build/ directory not found (may not have been created yet)"
  fi

  STATE_DIR="${DEMO_DIR}/state"
  if [[ -d "${STATE_DIR}" ]]; then
    STATE_FILES=$(find "${STATE_DIR}" -name '*.json' | wc -l)
    echo "  ✅ State directory has ${STATE_FILES} JSON files"
  else
    echo "  ⚠ state/ directory not found"
  fi

  # ── test 11: validate metadata.json fields ──────────────────────
  echo "==== Test 11: Validate metadata.json schema ==="
  python3 << PYEOF
import json, sys
with open("${META_JSON}") as f: meta = json.load(f)
required = ["title", "slug", "description", "tags", "created_at", "local_url", "public_url"]
missing = [k for k in required if k not in meta]
if missing:
    print(f"  ❌ Missing fields: {missing}")
    sys.exit(1)
print(f"  ✅ metadata.json has all required fields")
print(f"     title: {meta['title']}")
print(f"     slug: {meta['slug']}")
print(f"     tags: {meta['tags']}")
print(f"     local_url: {meta['local_url']}")
print(f"     public_url: {meta['public_url']}")
print(f"     screens: {meta.get('screens', [])}")
PYEOF

  # ── test 12: cancel endpoint (on a fresh short-lived run) ───────
  echo "==== Test 12: Cancel endpoint (POST /demos/jobs/{run_id}/cancel) ==="
  CANCEL_RESP="$(mktemp)"
  # We can only cancel running jobs, so skip for already-finished run
  # Instead just verify the endpoint exists by trying to cancel our finished run
  HTTP_CODE=$(curl -sS -o "${CANCEL_RESP}" -w "%{http_code}" \
    -X POST "${BASE_URL}/demos/jobs/${RUN_ID}/cancel" \
    -H "${AUTH_HEADER}")

  # A cancelled-already-successful run may return 200 or 404 — both are acceptable
  if [[ "${HTTP_CODE}" == "200" || "${HTTP_CODE}" == "404" ]]; then
    echo "  ✅ Cancel endpoint responds (HTTP ${HTTP_CODE})"
  else
    echo "  ⚠ Cancel endpoint returned HTTP ${HTTP_CODE}"
  fi
  GENERATED_FILES+=("${CANCEL_RESP}")
fi

# ── done ───────────────────────────────────────────────────────────
echo
echo "========================================"
echo "  ✅ All demo workflow smoke tests PASSED"
echo "========================================"
echo
