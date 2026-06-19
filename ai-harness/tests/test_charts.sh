#!/usr/bin/env bash
# Smoke test for the Charts module (HTTP endpoints).
#
# Exercises the chart generation pipeline through the API:
#   1.  Health check
#   2.  Line chart (PNG)            POST /chart/line
#   3.  Line chart (HTML fragment)  POST /chart/line
#   4.  Bar chart (PNG, stacked)    POST /chart/bar
#   5.  Pie chart (SVG, donut)      POST /chart/pie
#   6.  Unified endpoint (line)     POST /chart/any
#   7.  Unified endpoint (bar)      POST /chart/any
#   8.  Unified endpoint (pie)      POST /chart/any
#   9.  Verify generated files on disk
#  10.  Cleanup generated files
#
# Usage:
#   bash tests/test_charts.sh
#
# Environment (loaded from ../../.env or must be set manually):
#   BASE_LOCAL    — harness base URL (default: http://thor.local:8090)
#   HARNESS_API_KEY
#   MEDIA_OUTPUT_DIR   (default: /data/media)

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

# --- Pre-flight: check for jq ---
if ! command -v jq &>/dev/null; then
    echo "Error: jq is required but not found. Install it (e.g. apt install jq)."
    exit 1
fi

# --- Configuration ---
BASE_URL="${BASE_LOCAL:-http://${THOR_IP:-thor.local}:8090}"
API_KEY="${HARNESS_API_KEY:-}"
MEDIA_DIR="${MEDIA_OUTPUT_DIR:-/data/media}"
# The test may run on the host (where files live at the Docker mount point)
# or inside the container (where files live at /data/media/).
# Derive the correct path for file I/O.
# NOTE: /data/media/charts may exist on the host as an empty dir,
# so we can't rely on -d alone. Check for the Docker mount first.
if [[ "${MEDIA_DIR}" == /data/media ]] && [[ -d "/home/chuck/data/media/charts" ]]; then
    # Running on the host where Docker maps /home/chuck/data/media -> /data/media
    MEDIA_HOST_DIR="/home/chuck/data/media"
elif [[ -d "${MEDIA_DIR}/charts" ]]; then
    # Running inside the container or MEDIA_OUTPUT_DIR is already a valid host dir
    MEDIA_HOST_DIR="${MEDIA_DIR}"
else
    # Fallback: try prepending /home/chuck
    MEDIA_HOST_DIR="/home/chuck${MEDIA_DIR}"
fi
CHARTS_DIR="${MEDIA_HOST_DIR}/charts"
TMP_FILE=$(mktemp)
GENERATED_FILES=()
PASSED=0
SKIPPED=0
FAILED=0
KALEIDO_AVAILABLE=true

# Cleanup temp file + generated chart files on exit
cleanup() {
    rm -f "${TMP_FILE}"
    if [ ${#GENERATED_FILES[@]} -gt 0 ]; then
        echo ""
        echo "----------------------------------------------------------"
        echo "Cleaning up generated chart files..."
        for f in "${GENERATED_FILES[@]}"; do
            if [ -f "$f" ]; then
                rm -f "$f" 2>/dev/null
                echo "  Deleted: $f"
            fi
        done
    fi
}
trap cleanup EXIT

# ── Helpers ──────────────────────────────────────────────────
pass_test() {
    PASSED=$((PASSED + 1))
    echo "  ✅ $1"
}

skip_test() {
    SKIPPED=$((SKIPPED + 1))
    echo "  ⏭️  $1 (skipped)"
}

fail_test() {
    FAILED=$((FAILED + 1))
    echo "  ❌ $1"
}

post_json() {
    # post_json <name> <path> <json_body>
    local name="$1"
    local path="$2"
    local body="$3"

    echo ""
    echo "→ ${name}"
    echo "  POST ${path}"

    HTTP_STATUS=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" -X POST "${BASE_URL}${path}" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${API_KEY}" \
        -d "${body}" \
        --max-time 30 2>/dev/null) || HTTP_STATUS="000"

    echo "  → HTTP ${HTTP_STATUS}"

    if [ "${HTTP_STATUS}" != "200" ]; then
        fail_test "${name} returned HTTP ${HTTP_STATUS}"
        echo "  Response:"
        cat "${TMP_FILE}" 2>/dev/null | head -30
        return 1
    fi
    return 0
}

# Extract a JSON value from the last response. Usage: jq_val '.field'
jq_val() {
    jq -r "$1 // empty" "${TMP_FILE}" 2>/dev/null
}

skip_kaleido() {
    skip_test "$1 (Kaleido/Chrome not available in container)"
}

# ── Header ───────────────────────────────────────────────────
echo "=========================================================="
echo "  Charts Module Smoke Test (HTTP endpoints)"
echo "=========================================================="
echo "  Base URL:  ${BASE_URL}"
echo "  API Key:   ${API_KEY:+set (${#API_KEY} chars)}"
echo "  Media dir: ${MEDIA_HOST_DIR}"
echo "----------------------------------------------------------"

# ── 1. Health check ──────────────────────────────────────────
echo ""
echo "1. Health check"
HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${BASE_URL}/health" 2>/dev/null) || HEALTH_STATUS="000"

if [ "${HEALTH_STATUS}" -eq 200 ] 2>/dev/null; then
    pass_test "Health check OK"
else
    fail_test "Health check FAILED (HTTP ${HEALTH_STATUS})"
    echo "  App is not reachable at ${BASE_URL}/health. Aborting."
    echo "  Make sure ai-harness is running and BASE_LOCAL is correct."
    exit 1
fi

# ── Pre-flight: check Kaleido/Chrome availability ────────────
# Try a minimal PNG render to see if Kaleido can produce images.
echo ""
echo "0. Checking Kaleido/Chrome availability"
KALEIDO_CHECK=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/chart/line" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{"traces":[{"name":"probe","x":[0],"y":[0]}],"output_format":"png"}' \
    --max-time 30 2>/dev/null)
KALEIDO_HTTP=$(echo "${KALEIDO_CHECK}" | tail -1)
KALEIDO_BODY=$(echo "${KALEIDO_CHECK}" | head -n -1)

if [ "${KALEIDO_HTTP}" = "200" ]; then
    pass_test "Kaleido/Chrome OK — PNG/SVG rendering available"
else
    KALEIDO_AVAILABLE=false
    if echo "${KALEIDO_BODY}" | grep -qi "chrome\|kaleido"; then
        echo "  ⏭️  Kaleido/Chrome not available (requires Chrome installed in container)"
        echo "  Install with: plotly_get_chrome  or  apt-get install chromium"
    else
        echo "  ⏭️  PNG/SVG rendering unavailable (HTTP ${KALEIDO_HTTP})"
    fi
fi

# ── 2. Line chart (PNG) ──────────────────────────────────────
if [ "${KALEIDO_AVAILABLE}" = true ]; then
if post_json "Line chart (PNG)" "/chart/line" '{
  "config": {
    "title": "Revenue Trend",
    "title_x": 0.5,
    "xaxis_title": "Month",
    "yaxis_title": "USD ($k)",
    "template": "plotly_white",
    "width": 800,
    "height": 500
  },
  "traces": [
    {
      "name": "Revenue",
      "x": ["Jan", "Feb", "Mar", "Apr", "May"],
      "y": [120, 135, 128, 160, 175],
      "color": "#3b82f6",
      "line_width": 3,
      "mode": "lines+markers"
    },
    {
      "name": "Cost",
      "x": ["Jan", "Feb", "Mar", "Apr", "May"],
      "y": [80, 85, 90, 105, 110],
      "color": "#ef4444",
      "line_width": 2,
      "mode": "lines"
    }
  ],
  "output_format": "png"
}'; then
    FILENAME=$(jq_val '.filename')
    BYTES=$(jq_val '.bytes_written')

    if [ -n "${FILENAME}" ] && [ "${BYTES}" -gt 5000 ] 2>/dev/null; then
        pass_test "Line chart PNG: ${FILENAME} (${BYTES} bytes)"
        GENERATED_FILES+=("${CHARTS_DIR}/${FILENAME}")
    else
        fail_test "Line chart PNG: filename=${FILENAME}, bytes=${BYTES}"
    fi
fi
else
    echo ""
    skip_kaleido "Line chart (PNG)"
fi

# ── 3. Line chart (HTML fragment) ────────────────────────────
if post_json "Line chart (HTML fragment)" "/chart/line" '{
  "config": {
    "title": "Interactive Line",
    "width": 600,
    "height": 400
  },
  "traces": [
    {
      "name": "Series A",
      "x": [1, 2, 3, 4],
      "y": [10, 15, 13, 20],
      "mode": "lines+markers"
    }
  ],
  "output_format": "html_fragment"
}'; then
    FRAG=$(jq_val '.html_fragment')
    FRAG_LEN=${#FRAG}

    if [ -n "${FRAG}" ] && echo "${FRAG}" | grep -q "<div"; then
        pass_test "Line chart HTML fragment (${FRAG_LEN} chars)"
    else
        fail_test "Line chart HTML fragment: missing or invalid"
    fi
fi

# ── 4. Bar chart (PNG, stacked) ──────────────────────────────
if [ "${KALEIDO_AVAILABLE}" = true ]; then
if post_json "Bar chart (stacked PNG)" "/chart/bar" '{
  "config": {
    "title": "Quarterly Comparison",
    "width": 800,
    "height": 480
  },
  "traces": [
    {
      "name": "Product A",
      "x": ["Q1", "Q2", "Q3", "Q4"],
      "y": [45, 60, 55, 70]
    },
    {
      "name": "Product B",
      "x": ["Q1", "Q2", "Q3", "Q4"],
      "y": [30, 40, 50, 45],
      "color": "#f59e0b"
    }
  ],
  "barmode": "stack",
  "orientation": "v",
  "output_format": "png"
}'; then
    FILENAME=$(jq_val '.filename')
    BYTES=$(jq_val '.bytes_written')

    if [ -n "${FILENAME}" ] && [ "${BYTES}" -gt 5000 ] 2>/dev/null; then
        pass_test "Bar chart (stacked): ${FILENAME} (${BYTES} bytes)"
        GENERATED_FILES+=("${CHARTS_DIR}/${FILENAME}")
    else
        fail_test "Bar chart: filename=${FILENAME}, bytes=${BYTES}"
    fi
fi
else
    echo ""
    skip_kaleido "Bar chart (stacked PNG)"
fi

# ── 5. Pie chart (SVG, donut) ────────────────────────────────
if [ "${KALEIDO_AVAILABLE}" = true ]; then
if post_json "Pie chart (donut SVG)" "/chart/pie" '{
  "config": {
    "title": "Market Share",
    "width": 600,
    "height": 500
  },
  "labels": ["Alpha", "Beta", "Gamma", "Others"],
  "values": [35, 25, 20, 20],
  "colors": ["#3b82f6", "#10b981", "#f59e0b", "#6b7280"],
  "hole": 0.45,
  "pull": 0.05,
  "text_info": "label+percent",
  "output_format": "svg"
}'; then
    FILENAME=$(jq_val '.filename')
    BYTES=$(jq_val '.bytes_written')

    if [ -n "${FILENAME}" ] && [ "${BYTES}" -gt 500 ] 2>/dev/null; then
        SVG_FILE="${CHARTS_DIR}/${FILENAME}"
        if [ -f "${SVG_FILE}" ]; then
            FIRST_BYTES=$(head -c 20 "${SVG_FILE}" 2>/dev/null)
            if echo "${FIRST_BYTES}" | grep -q "<svg"; then
                pass_test "Pie chart (donut SVG): ${FILENAME} (${BYTES} bytes)"
                GENERATED_FILES+=("${SVG_FILE}")
            else
                fail_test "Pie chart SVG: file does not start with <svg>"
            fi
        else
            fail_test "Pie chart SVG: file not on disk at ${SVG_FILE}"
        fi
    else
        fail_test "Pie chart: filename=${FILENAME}, bytes=${BYTES}"
    fi
fi
else
    echo ""
    skip_kaleido "Pie chart (donut SVG)"
fi

# ── 6. Unified endpoint — line (PNG) ─────────────────────────
if [ "${KALEIDO_AVAILABLE}" = true ]; then
if post_json "Unified /chart/any (line)" "/chart/any" '{
  "chart_type": "line",
  "output_format": "png",
  "line_traces": [
    {
      "name": "Test Series",
      "x": [1, 2, 3],
      "y": [5, 3, 7]
    }
  ]
}'; then
    FILENAME=$(jq_val '.filename')
    BYTES=$(jq_val '.bytes_written')

    if [ -n "${FILENAME}" ] && [ "${BYTES}" -gt 2000 ] 2>/dev/null; then
        pass_test "Unified line chart: ${FILENAME} (${BYTES} bytes)"
        GENERATED_FILES+=("${CHARTS_DIR}/${FILENAME}")
    else
        fail_test "Unified line chart: filename=${FILENAME}, bytes=${BYTES}"
    fi
fi
else
    echo ""
    skip_kaleido "Unified /chart/any (line, PNG)"
fi

# ── 7. Unified endpoint — bar (PNG) ──────────────────────────
if [ "${KALEIDO_AVAILABLE}" = true ]; then
if post_json "Unified /chart/any (bar)" "/chart/any" '{
  "chart_type": "bar",
  "output_format": "png",
  "bar_traces": [
    {
      "name": "Test",
      "x": ["A", "B"],
      "y": [10, 20]
    }
  ]
}'; then
    FILENAME=$(jq_val '.filename')
    BYTES=$(jq_val '.bytes_written')

    if [ -n "${FILENAME}" ] && [ "${BYTES}" -gt 2000 ] 2>/dev/null; then
        pass_test "Unified bar chart: ${FILENAME} (${BYTES} bytes)"
        GENERATED_FILES+=("${CHARTS_DIR}/${FILENAME}")
    else
        fail_test "Unified bar chart: filename=${FILENAME}, bytes=${BYTES}"
    fi
fi
else
    echo ""
    skip_kaleido "Unified /chart/any (bar, PNG)"
fi

# ── 8. Unified endpoint — pie (PNG) ──────────────────────────
if [ "${KALEIDO_AVAILABLE}" = true ]; then
if post_json "Unified /chart/any (pie)" "/chart/any" '{
  "chart_type": "pie",
  "output_format": "png",
  "pie_labels": ["X", "Y"],
  "pie_values": [60, 40],
  "pie_hole": 0.2
}'; then
    FILENAME=$(jq_val '.filename')
    BYTES=$(jq_val '.bytes_written')

    if [ -n "${FILENAME}" ] && [ "${BYTES}" -gt 2000 ] 2>/dev/null; then
        pass_test "Unified pie chart: ${FILENAME} (${BYTES} bytes)"
        GENERATED_FILES+=("${CHARTS_DIR}/${FILENAME}")
    else
        fail_test "Unified pie chart: filename=${FILENAME}, bytes=${BYTES}"
    fi
fi
else
    echo ""
    skip_kaleido "Unified /chart/any (pie, PNG)"
fi

# ── 9. On-disk file verification ─────────────────────────────
if [ "${KALEIDO_AVAILABLE}" = true ] && [ ${#GENERATED_FILES[@]} -gt 0 ]; then
echo ""
echo "9. Verifying generated files on disk"
DISK_OK=0
DISK_FAIL=0

for f in "${GENERATED_FILES[@]}"; do
    if [ -f "$f" ]; then
        SIZE=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null)
        if [ "${SIZE}" -gt 0 ] 2>/dev/null; then
            DISK_OK=$((DISK_OK + 1))
        else
            DISK_FAIL=$((DISK_FAIL + 1))
        fi
    else
        DISK_FAIL=$((DISK_FAIL + 1))
    fi
done

if [ "${DISK_FAIL}" -eq 0 ]; then
    pass_test "All ${DISK_OK} generated chart files verified on disk"
else
    fail_test "On-disk verification: ${DISK_OK} OK, ${DISK_FAIL} missing/empty"
fi
else
    echo ""
    skip_kaleido "On-disk file verification"
fi

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "=========================================================="
TOTAL=$((PASSED + FAILED + SKIPPED))
if [ "${FAILED}" -eq 0 ]; then
    echo "  Result: ${PASSED} passed, ${SKIPPED} skipped, ${FAILED} failed"
else
    echo "  Result: ${PASSED} passed, ${SKIPPED} skipped, ${FAILED} failed"
fi
if [ "${KALEIDO_AVAILABLE}" = false ]; then
    echo ""
    echo "  Note: PNG/SVG tests skipped — Kaleido requires Chrome."
    echo "  Fix: install Chrome in the harness container,"
    echo "  then rebuild the image."
fi
echo "=========================================================="
echo ""

exit ${FAILED}
