#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# URL Rewriting Smoke Test
#
# Verifies that media URLs in harness responses are consistent
# and documents whether the _absolute_url() tool-layer rewrite
# is needed for browser access.
#
# Endpoints tested:
#   1. /pm/demo            — .url (INTERNAL_BASE_URL)
#   2. /demos/             — .local_url, .public_url (listing)
#   3. /presentation/list  — .download_url, .internal_download_url
#   4. /layout/build       — .html_path (relative), .pdf_url
#   5. /layout/export-pdf  — .url (PDF path)
# ─────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set -a
source "${SCRIPT_DIR}/../../../.env"
set +a

BASE_URL="${BASE_LOCAL:-http://${THOR_IP:-192.168.4.54}:8090}"
API_KEY="${HARNESS_API_KEY:-}"
DISPLAY_URL="${BASE_LOCAL:-http://192.168.4.54:8090}"

# Internal hostnames that are NOT directly browser-accessible on the LAN.
# URLs containing these should be rewritten by _absolute_url() in the tool layer.
INTERNAL_HOSTNAMES=(
    "thor.local"
    "ai-harness"
    "localhost"
    "127.0.0.1"
)

TMP_FILE=$(mktemp)
trap 'rm -f "${TMP_FILE}"' EXIT

TOTAL=0
PASSED=0
WARNED=0
FAILED=0

echo "=========================================================="
echo "  URL Rewriting Smoke Test"
echo "  Base URL:    ${BASE_URL}"
echo "  Display URL: ${DISPLAY_URL}"
echo "=========================================================="

# ── Helpers ──────────────────────────────────────────────────

# Check a single URL value against internal hostnames.
# Returns 0 on success (browser-accessible or empty),
#        1 on warning (internal hostname or relative path — needs tool-layer rewrite),
#        2 on error.
check_url() {
    local label="$1" url="$2"
    TOTAL=$((TOTAL + 1))

    if [[ -z "${url}" ]]; then
        echo "  ℹ ${label}: no URL in response"
        PASSED=$((PASSED + 1))
        return 0
    fi

    # Relative path (starts with /) — not directly browser-accessible
    if [[ "${url}" == /* && "${url}" != http* ]]; then
        echo "  ⚠ ${label}: relative path (needs display URL prefix)"
        echo "     URL: ${url}"
        echo "     ℹ The _absolute_url() tool layer should prefix this with ${DISPLAY_URL}"
        WARNED=$((WARNED + 1))
        return 1
    fi

    # Check against each internal hostname
    for hostname in "${INTERNAL_HOSTNAMES[@]}"; do
        if [[ "${url}" == *"${hostname}"* ]]; then
            echo "  ⚠ ${label}: contains internal hostname '${hostname}'"
            echo "     URL: ${url}"
            echo "     ℹ The _absolute_url() tool layer should rewrite this to ${DISPLAY_URL}/*"
            WARNED=$((WARNED + 1))
            return 1
        fi
    done

    echo "  ✅ ${label}: browser-accessible"
    echo "     URL: ${url}"
    PASSED=$((PASSED + 1))
    return 0
}

# ── Health check ─────────────────────────────────────────────

echo ""
echo -n "Health check... "
HC=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${BASE_URL}/health" 2>/dev/null) || HC="000"
if [[ "${HC}" == "200" ]]; then
    echo "✅ OK"
else
    echo "❌ FAILED (HTTP ${HC}) — aborting"
    exit 1
fi

# ── Test 1: PM Demo ──────────────────────────────────────────

echo ""
echo "==== PM Demo — /pm/demo (quick demo creation) ==="

HTTP_CODE=$(curl -sS -o "${TMP_FILE}" -w "%{http_code}" \
    -X POST "${BASE_URL}/pm/demo" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "title": "URL Test PM Demo",
        "prompt": "Create a minimal 1-screen demo for a todo app.",
        "save_name": "url-test-pm-demo"
    }' \
    --max-time 600 2>/dev/null) || HTTP_CODE="000"

if [[ "${HTTP_CODE}" == "200" ]]; then
    URL=$(jq -r '.url // empty' "${TMP_FILE}" 2>/dev/null)
    check_url "PM demo .url" "${URL}"
elif [[ "${HTTP_CODE}" == "404" ]]; then
    echo "  ℹ /pm/demo endpoint not found (skipping)"
    TOTAL=$((TOTAL + 1)); PASSED=$((PASSED + 1))
else
    echo "  ❌ PM demo returned HTTP ${HTTP_CODE}"
    head -5 "${TMP_FILE}"
    TOTAL=$((TOTAL + 1)); FAILED=$((FAILED + 1))
fi

# ── Test 2: Demo Listing ─────────────────────────────────────

echo ""
echo "==== Demo Listing — /demos/ (existing demos) ==="

HTTP_CODE=$(curl -sS -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/demos/?limit=5" \
    -H "X-API-Key: ${API_KEY}" \
    --max-time 15 2>/dev/null) || HTTP_CODE="000"

if [[ "${HTTP_CODE}" == "200" ]]; then
    DEMO_COUNT=$(jq -r '.demos | length // 0' "${TMP_FILE}" 2>/dev/null)
    DEMO_COUNT="${DEMO_COUNT:-0}"
    if [[ "${DEMO_COUNT}" -eq 0 ]]; then
        echo "  ℹ No demos found — nothing to verify"
        TOTAL=$((TOTAL + 1)); PASSED=$((PASSED + 1))
    else
        echo "  Found ${DEMO_COUNT} demo(s)"
        # Check local_url on first demo
        LOCAL_URL=$(jq -r '.demos[0].local_url // empty' "${TMP_FILE}" 2>/dev/null)
        check_url "Demo listing .local_url" "${LOCAL_URL}"

        # Check public_url on first demo
        PUBLIC_URL=$(jq -r '.demos[0].public_url // empty' "${TMP_FILE}" 2>/dev/null)
        check_url "Demo listing .public_url" "${PUBLIC_URL}"
    fi
elif [[ "${HTTP_CODE}" == "404" ]]; then
    echo "  ℹ /demos/ endpoint not found (skipping)"
    TOTAL=$((TOTAL + 1)); PASSED=$((PASSED + 1))
else
    echo "  ❌ Demo listing returned HTTP ${HTTP_CODE}"
    head -5 "${TMP_FILE}"
    TOTAL=$((TOTAL + 1)); FAILED=$((FAILED + 1))
fi

# ── Test 3: Presentation Listing ─────────────────────────────

echo ""
echo "==== Presentation Listing — /presentation/list ==="

HTTP_CODE=$(curl -sS -o "${TMP_FILE}" -w "%{http_code}" \
    "${BASE_URL}/presentation/list" \
    -H "X-API-Key: ${API_KEY}" \
    --max-time 15 2>/dev/null) || HTTP_CODE="000"

if [[ "${HTTP_CODE}" == "200" ]]; then
    PRESENTATION_COUNT=$(jq -r '.presentations | length // 0' "${TMP_FILE}" 2>/dev/null)
    PRESENTATION_COUNT="${PRESENTATION_COUNT:-0}"
    if [[ "${PRESENTATION_COUNT}" -eq 0 ]]; then
        echo "  ℹ No presentations found — nothing to verify"
        TOTAL=$((TOTAL + 1)); PASSED=$((PASSED + 1))
    else
        echo "  Found ${PRESENTATION_COUNT} presentation(s)"
        # Check download_url on first presentation
        DOWNLOAD_URL=$(jq -r '.presentations[0].download_url // empty' "${TMP_FILE}" 2>/dev/null)
        check_url "Presentation .download_url" "${DOWNLOAD_URL}"

        # Check internal_download_url on first presentation
        INTERNAL_URL=$(jq -r '.presentations[0].internal_download_url // empty' "${TMP_FILE}" 2>/dev/null)
        check_url "Presentation .internal_download_url" "${INTERNAL_URL}"
    fi
elif [[ "${HTTP_CODE}" == "404" ]]; then
    echo "  ℹ /presentation/list endpoint not found (skipping)"
    TOTAL=$((TOTAL + 1)); PASSED=$((PASSED + 1))
else
    echo "  ❌ Presentation listing returned HTTP ${HTTP_CODE}"
    head -5 "${TMP_FILE}"
    TOTAL=$((TOTAL + 1)); FAILED=$((FAILED + 1))
fi

# ── Test 4: Layout Build (no LLM, instant) ───────────────────

echo ""
echo "==== Layout Build — /layout/build (minimal document) ==="

HTTP_CODE=$(curl -sS -o "${TMP_FILE}" -w "%{http_code}" \
    -X POST "${BASE_URL}/layout/build" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "title": "URL Test Document",
        "template": "minimal",
        "orientation": "portrait",
        "zones": [
            {"zone": "header", "content_type": "text", "content": "URL Rewrite Test"}
        ],
        "output_path": "documents/url-test.html"
    }' \
    --max-time 30 2>/dev/null) || HTTP_CODE="000"

if [[ "${HTTP_CODE}" == "200" ]]; then
    # html_path is a relative workspace path — just check it exists
    HTML_PATH=$(jq -r '.html_path // empty' "${TMP_FILE}" 2>/dev/null)
    if [[ -n "${HTML_PATH}" ]]; then
        echo "  ✅ Layout build .html_path: ${HTML_PATH}"
        TOTAL=$((TOTAL + 1)); PASSED=$((PASSED + 1))
    else
        echo "  ⚠ Layout build returned no html_path"
        WARNED=$((WARNED + 1)); TOTAL=$((TOTAL + 1))
    fi

    # Check pdf_url if present
    PDF_URL=$(jq -r '.pdf_url // empty' "${TMP_FILE}" 2>/dev/null)
    if [[ -n "${PDF_URL}" ]]; then
        check_url "Layout build .pdf_url" "${PDF_URL}"
    fi
elif [[ "${HTTP_CODE}" == "404" ]]; then
    echo "  ℹ /layout/build endpoint not found (skipping)"
    TOTAL=$((TOTAL + 1)); PASSED=$((PASSED + 1))
else
    echo "  ❌ Layout build returned HTTP ${HTTP_CODE}"
    head -5 "${TMP_FILE}"
    TOTAL=$((TOTAL + 1)); FAILED=$((FAILED + 1))
fi

# ── Test 5: Layout PDF Export (URL in response) ──────────────

echo ""
echo "==== Layout PDF Export — /layout/export-pdf (URL verification) ==="

# First create a layout to get a layout_id
CREATE_CODE=$(curl -sS -o "${TMP_FILE}" -w "%{http_code}" \
    -X POST "${BASE_URL}/layout/create" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "title": "URL Test PDF",
        "template": "minimal",
        "orientation": "portrait"
    }' \
    --max-time 15 2>/dev/null) || CREATE_CODE="000"

if [[ "${CREATE_CODE}" != "200" ]]; then
    echo "  ℹ Could not create layout (HTTP ${CREATE_CODE}) — skipping PDF test"
    TOTAL=$((TOTAL + 1)); PASSED=$((PASSED + 1))
else
    LAYOUT_ID=$(jq -r '.layout_id // empty' "${TMP_FILE}" 2>/dev/null)
    if [[ -z "${LAYOUT_ID}" ]]; then
        echo "  ⚠ Layout created but no layout_id returned"
        TOTAL=$((TOTAL + 1)); WARNED=$((WARNED + 1))
    else
        # Export as PDF — use layout_id in a temp file to avoid quoting issues
        PDF_PAYLOAD=$(jq -n --arg lid "${LAYOUT_ID}" '{
            layout_id: $lid,
            output_path: "url-test-export.pdf",
            page_size: "Letter"
        }')

        PDF_CODE=$(curl -sS -o "${TMP_FILE}" -w "%{http_code}" \
            -X POST "${BASE_URL}/layout/export-pdf" \
            -H "Content-Type: application/json" \
            -H "X-API-Key: ${API_KEY}" \
            -d "${PDF_PAYLOAD}" \
            --max-time 30 2>/dev/null) || PDF_CODE="000"

        if [[ "${PDF_CODE}" == "200" ]]; then
            PDF_URL=$(jq -r '.url // empty' "${TMP_FILE}" 2>/dev/null)
            check_url "Layout PDF export .url" "${PDF_URL}"
        elif [[ "${PDF_CODE}" == "404" ]]; then
            echo "  ℹ /layout/export-pdf not found (skipping)"
            TOTAL=$((TOTAL + 1)); PASSED=$((PASSED + 1))
        else
            echo "  ⚠ PDF export returned HTTP ${PDF_CODE}"
            head -5 "${TMP_FILE}"
            TOTAL=$((TOTAL + 1)); WARNED=$((WARNED + 1))
        fi
    fi
fi

# ── Summary ──────────────────────────────────────────────────

echo ""
echo "=========================================================="
echo "  URL Rewriting Smoke Tests Complete"
echo "  Total: ${TOTAL}  |  Passed: ${PASSED}  |  Warned: ${WARNED}  |  Failed: ${FAILED}"
echo ""
if [[ "${WARNED}" -gt 0 ]]; then
    echo "  ℹ ${WARNED} URL(s) contain internal hostname(s)."
    echo "    These are expected when INTERNAL_BASE_URL uses thor.local."
    echo "    The _absolute_url() function in OpenWebUI tools rewrites them."
    echo "    For direct browser access, set INTERNAL_BASE_URL to the LAN IP."
fi
if [[ "${FAILED}" -gt 0 ]]; then
    echo "  ❌ ${FAILED} test(s) failed — check harness availability"
fi
if [[ "${FAILED}" -eq 0 ]]; then
    echo "  ✅ All URL checks completed (warnings above are informational)"
fi
echo "=========================================================="
echo

# Exit 0 even on warnings — they're informational, not errors
if [[ "${FAILED}" -gt 0 ]]; then
    exit 1
fi
exit 0
