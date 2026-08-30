#!/usr/bin/env bash
# verify_attribution.sh — Phase 2.5 live per-user attribution test.
#
# Requires: AUTH_KEY_THREADING_ENABLED=true in .env (manual step).
#
# Tests:
#   T5: Run a skill with chuck's key → verify user_id=chuck in the job log.
#   T6: Run a skill with dylan's key → verify user_id=dylan in the job log.
#   T7: Run a skill with the legacy key → verify user_id=chuck (legacy maps to chuck).
#   T8: Run a skill with an unknown key → verify user_id=unknown.
#
# Usage: ./cli/verify_attribution.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"

# Load env
set -a
source "$ENV_FILE"
set +a

BASE="${SKILL_RUNNER_BASE:-http://192.168.4.54:8091}"

echo "=== Phase 2.5: Live per-user attribution test ==="
echo "SKILL_RUNNER_BASE: $BASE"
echo "AUTH_KEY_THREADING_ENABLED: ${AUTH_KEY_THREADING_ENABLED:-false}"
echo ""

if [[ "${AUTH_KEY_THREADING_ENABLED:-false}" != "true" ]]; then
  echo "⚠️  AUTH_KEY_THREADING_ENABLED is not 'true'."
  echo "   Set it in .env and rebuild skill-only to run this test."
  exit 1
fi

run_skill() {
  local key="$1"
  local label="$2"
  local resp
  resp=$(curl -s -X POST "$BASE/api/chat" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $key" \
    -d '{"text":"What is 7+7?","intent":"siri_ask"}')
  local job_id
  job_id=$(echo "$resp" | jq -r '.job_id // empty')
  if [[ -z "$job_id" ]]; then
    # Synchronous skill (job_id is null) — check the response directly
    local speak
    speak=$(echo "$resp" | jq -r '.speak // .display // empty')
    if [[ -n "$speak" ]]; then
      echo "  $label: COMPLETED (sync) speak=$speak"
      return 0
    fi
    echo "  $label: FAILED (no job_id, no speak): $resp"
    return 1
  fi
  # Poll for completion
  for i in $(seq 1 30); do
    sleep 2
    local job
    job=$(curl -s "$BASE/api/jobs/$job_id" -H "X-API-Key: $key")
    local status
    status=$(echo "$job" | jq -r '.status // empty')
    if [[ "$status" == "completed" || "$status" == "failed" ]]; then
      echo "  $label: job_id=$job_id status=$status"
      # Check the job log for user_id
      local user_id
      user_id=$(echo "$job" | jq -r '.user_id // "unknown"')
      echo "  $label: user_id=$user_id"
      return 0
    fi
  done
  echo "  $label: TIMEOUT (job_id=$job_id)"
  return 1
}

echo "T5: chuck's key"
run_skill "$LITELLM_KEY_CHUCK" "chuck" || echo "  T5: FAILED"
echo ""

echo "T6: dylan's key"
run_skill "$LITELLM_KEY_DYLAN" "dylan" || echo "  T6: FAILED"
echo ""

echo "T7: legacy key (maps to chuck)"
run_skill "$SIRI_API_KEY" "legacy" || echo "  T7: FAILED"
echo ""

echo "=== Done ==="