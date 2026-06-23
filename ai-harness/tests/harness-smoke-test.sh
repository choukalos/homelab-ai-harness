#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# AI Harness — Master Smoke Test Orchestrator
#
# Runs all smoke test suites in order:
#   1. Infra     (workflows, tasks, scheduler)
#   2. Research  (web search, deep research, brief)
#   3. Knowledge (family KB ingest, search, ask)
#   4. Creative  (charts, presentations)
#   5. Media     (image gen, clips)
#   6. Apps      (PM demo, demo workflow)
#   7. Filetools (stub for now)
#   8. Channels  (Siri)
# ─────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set -a
source "${SCRIPT_DIR}/../../.env"
set +a

RUN_MEDIA_TESTS="${RUN_MEDIA_TESTS:-0}"
RUN_CHANNEL_TESTS="${RUN_CHANNEL_TESTS:-0}"

echo
echo "========================================"
echo "  AI Harness — Master Smoke Test"
echo "  Base URL: ${BASE_LOCAL:-http://${THOR_IP:-192.168.4.54}:8090}"
echo "  Media tests:  ${RUN_MEDIA_TESTS}"
echo "  Channel tests: ${RUN_CHANNEL_TESTS}"
echo "========================================"
echo

TOTAL=0
PASSED=0
FAILED=0
SKIPPED=0

run_test() {
  local label="$1"
  local script="$2"
  local condition="${3:-}"  # optional: bash condition to skip

  TOTAL=$((TOTAL + 1))

  # Check skip condition
  if [[ -n "${condition}" ]] && ! eval "${condition}"; then
    SKIPPED=$((SKIPPED + 1))
    echo "[SKIP] ${label}"
    return
  fi

  echo "========================================"
  echo "[RUN]  ${label}"
  echo "========================================"

  if bash "${script}"; then
    PASSED=$((PASSED + 1))
    echo "[OK]   ${label}"
  else
    FAILED=$((FAILED + 1))
    echo "[FAIL] ${label}"
  fi
  echo
}

# ── Smoke tests ──────────────────────────────────────────────

run_test "Infra (workflows)"     "${SCRIPT_DIR}/smoke/test_infra.sh"
run_test "Research"              "${SCRIPT_DIR}/smoke/test_research.sh"
run_test "Knowledge"             "${SCRIPT_DIR}/smoke/test_knowledge.sh"
run_test "Creative (charts+pres)" "${SCRIPT_DIR}/smoke/test_creative.sh"
run_test "Media (image+clip)"    "${SCRIPT_DIR}/smoke/test_media.sh"          "[[ '${RUN_MEDIA_TESTS}' == '1' ]]"
run_test "Apps (demo workflow)"  "${SCRIPT_DIR}/smoke/test_apps.sh"
run_test "Filetools (stub)"      "${SCRIPT_DIR}/smoke/test_filetools.sh"

# ── Channel tests ────────────────────────────────────────────

if [[ "${RUN_CHANNEL_TESTS}" == "1" ]]; then
  run_test "Channels (Siri)"       "${SCRIPT_DIR}/channels/test_siri.sh"
  run_test "Channels (OpenWebUI)"  "${SCRIPT_DIR}/channels/test_openwebui.sh"
else
  TOTAL=$((TOTAL + 2))
  SKIPPED=$((SKIPPED + 1))
  echo "[SKIP] Channels (Siri) — set RUN_CHANNEL_TESTS=1 to enable"
  SKIPPED=$((SKIPPED + 1))
  echo "[SKIP] Channels (OpenWebUI) — set RUN_CHANNEL_TESTS=1 to enable"
  echo
fi

# ── Summary ──────────────────────────────────────────────────

echo "========================================"
echo "  Results: ${PASSED} passed, ${FAILED} failed, ${SKIPPED} skipped (total: ${TOTAL})"
if [ "${FAILED}" -eq 0 ]; then
  echo "  ✅ All smoke tests passed"
else
  echo "  ❌ Some tests failed"
fi
echo "========================================"

exit "${FAILED}"
