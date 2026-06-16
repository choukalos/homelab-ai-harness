#!/usr/bin/env bash
# Test script for the Deep Research module.
#
# Usage:
#   bash tests/test_deep_research.sh
#
# This script automatically sources ../../.env for configuration.

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
# Use INTERNAL_BASE_URL (from compose) or HARNESS_URL, default to thor.local:8090
BASE_URL="${BASE_LOCAL:-http://${THOR_IP}:8090}"
API_KEY="${HARNESS_API_KEY:-}"
URL="${BASE_URL}/workflows/deep-research/run"
TMP_FILE=$(mktemp)

# Cleanup temp file on exit
trap 'rm -f "${TMP_FILE}"' EXIT

echo "=========================================================="
echo "  Deep Research Integration Test"
echo "=========================================================="
echo "  Base URL: ${BASE_URL}"
echo "  API Key:  ${API_KEY:+set (${#API_KEY} chars)}"
echo "----------------------------------------------------------"

# Health check
echo -n "Checking app health... "
HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${BASE_URL}/health" 2>/dev/null) || HEALTH_STATUS="000"

if [ "${HEALTH_STATUS}" -eq 200 ] 2>/dev/null; then
    echo "OK"
else
    echo "FAILED (HTTP ${HEALTH_STATUS})"
    echo "App is not reachable at ${BASE_URL}/health. Aborting."
    echo "Make sure ai-harness is running and INTERNAL_BASE_URL is correct."
    exit 1
fi

# Deep research
echo ""
echo "POST ${URL}"
echo "  Body: {\"query\": \"What is 2+2?\"}"

HTTP_STATUS=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" -X POST "${URL}" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"query":"What is 2+2?"}' \
  --max-time 180 2>/dev/null) || HTTP_STATUS="000"

echo "  -> HTTP ${HTTP_STATUS}"

if [ "${HTTP_STATUS}" -eq 200 ] 2>/dev/null; then
    echo "  ✅ Success!"
    echo ""
    cat "${TMP_FILE}"
    echo ""
    echo "=========================================================="
    echo "  Result: PASSED"
    echo "=========================================================="
    exit 0
else
    echo "  ❌ Failed!"
    echo ""
    cat "${TMP_FILE}" 2>/dev/null || echo "(no response body)"
    echo ""
    echo "=========================================================="
    echo "  Result: FAILED"
    echo "=========================================================="
    exit 1
fi
