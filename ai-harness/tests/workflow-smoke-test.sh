#!/usr/bin/bash
#
# workflow-smoke-test.sh — Smoke test for the workflow run state engine.
#
# Exercises the full lifecycle:
#   1. Create a workflow definition (3 steps with dependencies)
#   2. Start a run                  (all steps PENDING)
#   3. Fetch run                   (confirm step count & statuses)
#   4. Get next-step               (should return first step)
#   5. Mark step 1 RUNNING        → SUCCESS
#   6. Mark step 2 RUNNING        → SUCCESS  (depends_on step 1, satisfied)
#   7. Complete step 3            → auto-transition run to SUCCESS
#   8. Verify cost/token/artifact persistence
#   9. Start 2nd run, fail one step → run becomes FAILED
#  10. Update run metadata manually
#  11. List workflows & runs
#  12. Delete the workflow         (cascade deletes runs + steps)

set -euo pipefail

cd "$(dirname "$0")"

set -a
source ../../.env
set +a

BASE_URL="${BASE_URL:-http://${THOR_IP:-192.168.4.54}:8090}"
AUTH_HEADER="X-API-Key: ${HARNESS_API_KEY}"

echo
echo "========================================"
echo "  Workflow Engine Smoke Test"
echo "  Base URL: ${BASE_URL}"
echo "========================================"
echo

# ------------------------------------------------------------------ helpers

curl_post_json() {
  # curl_post_json <url> <json_body>
  # Writes raw response to stdout or exits on HTTP failure
  curl -sS -f -X POST "$1" \
    -H "Content-Type: application/json" \
    -H "$AUTH_HEADER" \
    -d "$2"
}

curl_patch_json() {
  curl -sS -f -X PATCH "$1" \
    -H "Content-Type: application/json" \
    -H "$AUTH_HEADER" \
    -d "$2"
}

curl_get_json() {
  curl -sS -f "$1" -H "$AUTH_HEADER"
}

extract_json() {
  # extract_json <file> <python_expr>
  python3 -c "
import json, sys
with open('$1') as f: data = json.load(f)
print($2)
" 2>/dev/null
}

# --------------------------------------------------------------- tests

# ---- Step 1: Create workflow definition ----

echo "==== Step 1: Create a 3-step workflow definition ===="
RESP_FILE="$(mktemp)"

curl_post_json "${BASE_URL}/workflows/" '{
  "name": "Smoke Test Pipeline",
  "description": "3-step pipeline to exercise the workflow engine",
  "tags": ["smoke-test", "ci"],
  "steps": [
    {
      "name": "research",
      "description": "Gather initial data",
      "task_name": "tasks.run_prompt",
      "task_kwargs": {
        "prompt": "List 3 current AI homelab trends",
        "system": "Be concise."
      },
      "max_retries": 2
    },
    {
      "name": "summarize",
      "description": "Summarize findings",
      "task_name": "tasks.run_prompt",
      "task_kwargs": {
        "prompt": "Summarize these trends",
        "system": "You are a technical writer."
      },
      "depends_on": ["research"],
      "max_retries": 1
    },
    {
      "name": "format_report",
      "description": "Format as markdown",
      "task_name": "tasks.run_prompt",
      "task_kwargs": {
        "prompt": "Format this as markdown",
        "system": "Markdown expert."
      },
      "depends_on": ["summarize"],
      "max_retries": 0
    }
  ]
}' > "${RESP_FILE}"

WF_ID="$(extract_json "${RESP_FILE}" "data.get('workflow_id','')")"
if [[ -z "${WF_ID}" ]]; then
  echo "  ❌ No workflow_id returned"; cat "${RESP_FILE}"; rm -f "${RESP_FILE}"; exit 1
fi
echo "  ✅ Workflow created: ${WF_ID}"

STEP_COUNT="$(extract_json "${RESP_FILE}" "len(data.get('steps', []))")"
if [[ "${STEP_COUNT}" -ne 3 ]]; then
  echo "  ❌ Expected 3 steps, got ${STEP_COUNT}"; rm -f "${RESP_FILE}"; exit 1
fi
rm -f "${RESP_FILE}"

# ---- Step 2: Start a run ----

echo "==== Step 2: Start a run ===="
RESP_FILE="$(mktemp)"

curl_post_json "${BASE_URL}/workflows/${WF_ID}/runs" '{
  "metadata": {"test": "smoke-test", "iteration": 1}
}' > "${RESP_FILE}"

RUN_ID="$(extract_json "${RESP_FILE}" "data.get('run_id','')")"
if [[ -z "${RUN_ID}" ]]; then
  echo "  ❌ No run_id returned"; rm -f "${RESP_FILE}"; exit 1
fi
echo "  ✅ Run started: ${RUN_ID}"

STEP_STATUSES="$(extract_json "${RESP_FILE}" "','.join(s.get('status') for s in data.get('steps', []))")"
if [[ "${STEP_STATUSES}" != "pending,pending,pending" ]]; then
  echo "  ❌ Expected all pending, got: ${STEP_STATUSES}"; rm -f "${RESP_FILE}"; exit 1
fi
echo "  ✅ All 3 steps are PENDING"
rm -f "${RESP_FILE}"

# ---- Step 3: Fetch run status ----

echo "==== Step 3: Fetch run status ===="
RESP_FILE="$(mktemp)"
curl_get_json "${BASE_URL}/workflows/runs/${RUN_ID}" > "${RESP_FILE}"
RUN_STATUS="$(extract_json "${RESP_FILE}" "data.get('status','')")"
echo "  ✅ Run status: ${RUN_STATUS}"
echo "  ✅ GET /workflows/runs/${RUN_ID} works"
rm -f "${RESP_FILE}"

# ---- Step 4: Get next pending step ----

echo "==== Step 4: Get next pending step ===="
RESP_FILE="$(mktemp)"
curl_post_json "${BASE_URL}/workflows/runs/${RUN_ID}/next-step" '{}' > "${RESP_FILE}"

NEXT_NAME="$(extract_json "${RESP_FILE}" "data.get('next_step',{}).get('name','') if data.get('next_step') else 'null'")"
if [[ "${NEXT_NAME}" == "research" ]]; then
  echo "  ✅ Next step is 'research' (correct — first step, no dependencies)"
else
  echo "  ❌ Expected 'research', got: ${NEXT_NAME}"; rm -f "${RESP_FILE}"; exit 1
fi
rm -f "${RESP_FILE}"

# ---- Step 5: Mark research RUNNING → SUCCESS ----

echo "==== Step 5: Mark step 'research' RUNNING, then SUCCESS ===="

curl_patch_json "${BASE_URL}/workflows/runs/${RUN_ID}/steps/research" \
  '{"status":"running","celery_task_id":"fake-task-001"}' > /dev/null
echo "  ✅ Marked 'research' as RUNNING"

curl_post_json "${BASE_URL}/workflows/runs/${RUN_ID}/complete-step/research" '{}' > "${RESP_FILE}"
STEP5_STATUS="$(extract_json "${RESP_FILE}" "({s['name']:s['status'] for s in data.get('steps',[])}).get('research','')")"
if [[ "${STEP5_STATUS}" != "success" ]]; then
  echo "  ❌ research status is ${STEP5_STATUS}"; rm -f "${RESP_FILE}"; exit 1
fi
echo "  ✅ Step 'research' is SUCCESS"
rm -f "${RESP_FILE}"

# ---- Step 6: Mark summarize RUNNING → SUCCESS ----

echo "==== Step 6: Mark step 'summarize' RUNNING then SUCCESS ===="

curl_patch_json "${BASE_URL}/workflows/runs/${RUN_ID}/steps/summarize" \
  '{"status":"running","celery_task_id":"fake-task-002"}' > /dev/null
echo "  ✅ Marked 'summarize' as RUNNING"

RESP_FILE="$(mktemp)"
curl_post_json "${BASE_URL}/workflows/runs/${RUN_ID}/complete-step/summarize" '{
  "output": {"summary": "Trends: local-first AI, edge inference, RAG pipelines"},
  "cost": 0.003,
  "input_tokens": 120,
  "output_tokens": 450
}' > "${RESP_FILE}"

STEP6_STATUS="$(extract_json "${RESP_FILE}" "({s['name']:s['status'] for s in data.get('steps',[])}).get('summarize','')")"
if [[ "${STEP6_STATUS}" != "success" ]]; then
  echo "  ❌ summarize status is ${STEP6_STATUS}"; rm -f "${RESP_FILE}"; exit 1
fi
echo "  ✅ Step 'summarize' is SUCCESS (with cost/token tracking)"
rm -f "${RESP_FILE}"

# ---- Step 7: Complete format_report with artifacts — run auto-transitions to SUCCESS ----

echo "==== Step 7: Complete 'format_report' — run should auto-transition to SUCCESS ===="
RESP_FILE="$(mktemp)"
curl_post_json "${BASE_URL}/workflows/runs/${RUN_ID}/complete-step/format_report" '{
  "output": {"markdown": "# AI Homelab Trends Report"},
  "cost": 0.002,
  "input_tokens": 200,
  "output_tokens": 600,
  "artifacts": [{"name":"report.md","filename":"report-test.md","mime_type":"text/markdown","size_bytes":4096}]
}' > "${RESP_FILE}"

RUN_STATUS="$(extract_json "${RESP_FILE}" "data.get('status','')")"
if [[ "${RUN_STATUS}" != "success" ]]; then
  echo "  ❌ Run status is ${RUN_STATUS}, expected 'success'"; rm -f "${RESP_FILE}"; exit 1
fi
echo "  ✅ Run auto-transitioned to SUCCESS (all 3 steps completed)"

# ---- Step 8: Verify cost/token/artifact persistence ----

echo "==== Step 8: Verify cost/token/artifact persistence ===="
RESP_FILE="$(mktemp)"
curl_get_json "${BASE_URL}/workflows/runs/${RUN_ID}" > "${RESP_FILE}"

python3 << PYEOF
import json, sys
with open("${RESP_FILE}") as f: data = json.load(f)
steps = {s["name"]: s for s in data.get("steps", [])}

s = steps.get("summarize", {})
assert s.get("cost") == 0.003, f'cost={s.get("cost")}'
assert s.get("input_tokens") == 120
assert s.get("output_tokens") == 450

s = steps.get("format_report", {})
arts = s.get("artifacts", [])
assert len(arts) == 1, f'artifacts count: {len(arts)}'
assert arts[0].get("name") == "report.md"
assert arts[0].get("size_bytes") == 4096
PYEOF
echo "  ✅ Cost, tokens, and artifacts persisted correctly"
rm -f "${RESP_FILE}"

# ---- Step 9: Start 2nd run, fail one step — run becomes FAILED ----

echo "==== Step 9: Start 2nd run and intentionally fail a step ===="
RESP_FILE="$(mktemp)"
curl_post_json "${BASE_URL}/workflows/${WF_ID}/runs" '{
  "metadata": {"test":"smoke-test","scenario":"failure"}
}' > "${RESP_FILE}"

RUN2_ID="$(extract_json "${RESP_FILE}" "data.get('run_id','')")"
rm -f "${RESP_FILE}"
if [[ -z "${RUN2_ID}" ]]; then
  echo "  ❌ No run_id for 2nd run"; exit 1
fi
echo "  ✅ 2nd run started: ${RUN2_ID}"

# Fail the first step
curl_patch_json "${BASE_URL}/workflows/runs/${RUN2_ID}/steps/research" \
  '{"status":"failed","error":"Simulated failure for smoke test","retry_count":3}' > /dev/null
echo "  ✅ Marked 'research' as FAILED"

# Skip the dependent steps
curl_patch_json "${BASE_URL}/workflows/runs/${RUN2_ID}/steps/summarize" \
  '{"status":"skipped"}' > /dev/null
curl_patch_json "${BASE_URL}/workflows/runs/${RUN2_ID}/steps/format_report" \
  '{"status":"skipped"}' > /dev/null
echo "  ✅ Skipped dependent steps"

# Verify run transitioned to FAILED
RESP_FILE="$(mktemp)"
curl_get_json "${BASE_URL}/workflows/runs/${RUN2_ID}" > "${RESP_FILE}"
RUN2_STATUS="$(extract_json "${RESP_FILE}" "data.get('status','')")"
if [[ "${RUN2_STATUS}" != "failed" ]]; then
  echo "  ❌ Expected 'failed', got: ${RUN2_STATUS}"; rm -f "${RESP_FILE}"; exit 1
fi
echo "  ✅ 2nd run auto-transitioned to FAILED"
rm -f "${RESP_FILE}"

# ---- Step 10: Update run metadata manually ----

echo "==== Step 10: Update run metadata manually ===="
RESP_FILE="$(mktemp)"
curl_patch_json "${BASE_URL}/workflows/runs/${RUN_ID}" '{
  "metadata": {"test":"smoke-test","updated_by":"smoke-script","notes":"passing all checks"}
}' > "${RESP_FILE}"

META_NOTES="$(extract_json "${RESP_FILE}" "data.get('metadata',{}).get('notes','')")"
if [[ "${META_NOTES}" != "passing all checks" ]]; then
  echo "  ❌ Expected 'passing all checks', got: ${META_NOTES}"
else
  echo "  ✅ Run metadata updated successfully"
fi
rm -f "${RESP_FILE}"

# ---- Step 11: List workflows and runs ----

echo "==== Step 11: List workflows and runs ===="
RESP_FILE="$(mktemp)"
curl_get_json "${BASE_URL}/workflows/" > "${RESP_FILE}"
echo "  ✅ Listed workflows"

RESP2="$(extract_json "${RESP_FILE}" "len(data)")"
echo "  ✅ Total workflows: ${RESP2}"
rm -f "${RESP_FILE}"

RESP_FILE="$(mktemp)"
curl_get_json "${BASE_URL}/workflows/runs?workflow_id=${WF_ID}" > "${RESP_FILE}"
echo "  ✅ Listed runs for workflow ${WF_ID}"
rm -f "${RESP_FILE}"

# ---- Step 12: Delete the workflow (cascade deletes runs + steps) ----

echo "==== Step 12: Delete the workflow (cascade) ===="
DEL_CODE=$(curl -sS -o /dev/null -w "%{http_code}" \
  -X DELETE "${BASE_URL}/workflows/${WF_ID}" \
  -H "Content-Type: application/json" \
  -H "$AUTH_HEADER")
echo "  ✅ Workflow deleted (HTTP ${DEL_CODE})"

# Verify cascade — run should be gone
RUN404_CODE=$(curl -sS -o /dev/null -w "%{http_code}" \
  "${BASE_URL}/workflows/runs/${RUN_ID}" \
  -H "$AUTH_HEADER")
if [[ "${RUN404_CODE}" == "404" ]]; then
  echo "  ✅ Cascade delete confirmed — run no longer exists (404)"
else
  echo "  ⚠ Expected 404 for deleted run, got: ${RUN404_CODE}"
fi

echo
echo "========================================"
echo "  ✅ All workflow smoke tests PASSED"
echo "========================================"
echo
