#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Cleanup script for test demo artifacts
#
# Usage:
#   bash cleanup_demos.sh                     # delete all test demos
#   bash cleanup_demos.sh "Smoke Test"        # delete only matching titles
#   bash cleanup_demos.sh --dry-run           # preview what would be deleted
#
# Handles:
#   - Flat .html files in /data/media/demos/ (PM quick demos)
#   - Workflow demo subdirectories with metadata.json
#
# Test title patterns (matched case-insensitively):
#   - "Smoke Test"     (from smoke tests)
#   - "OpenWebUI"      (from channel tests)
#   - "Siri Demo"      (from Siri tests)
#
# This script deletes demo files from the harness container's filesystem
# using docker exec since there is no API endpoint for demo deletion.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Load environment ────────────────────────────────────────
if [[ ! -f "$SCRIPT_DIR/../../.env" ]]; then
    echo "❌ .env file not found at $SCRIPT_DIR/../../.env"
    exit 1
fi
set -a; source "$SCRIPT_DIR/../../.env"; set +a

BASE_URL="${BASE_LOCAL:-http://${THOR_IP:-192.168.4.54}:8090}"
API_KEY="${HARNESS_API_KEY:-}"
CONTAINER_NAME="ai-harness"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    shift
fi

# ── Default test title patterns (case-insensitive) ──────────
if [[ $# -gt 0 ]]; then
    PATTERNS=("$@")
else
    PATTERNS=(
        "smoke test"
        "openwebui"
        "siri demo"
    )
fi

echo "==========================================================="
echo "  Demo Cleanup"
echo "==========================================================="
echo "  Harness:     $BASE_URL"
echo "  Container:   $CONTAINER_NAME"
echo "  Patterns:    ${PATTERNS[*]}"
[[ "$DRY_RUN" == "true" ]] && echo "  ⚠ DRY RUN — no changes will be made"
echo "-----------------------------------------------------------"

# ── Health check ────────────────────────────────────────────
echo -n "  Container health... "
HC=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${BASE_URL}/health" 2>/dev/null) || HC="000"
if [[ "$HC" != "200" ]]; then
    echo "❌ Harness not reachable (HTTP $HC)"
    exit 1
fi
echo "✅ OK"

# ── Fetch demo list ─────────────────────────────────────────
TMP=$(mktemp)
HTTP_CODE=$(curl -s -o "$TMP" -w "%{http_code}" \
    "${BASE_URL}/demos/?limit=200" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

if [[ "$HTTP_CODE" != "200" ]]; then
    echo "❌ Failed to fetch demo list (HTTP $HTTP_CODE)"
    rm -f "$TMP"
    exit 1
fi

# ── Identify test demos ─────────────────────────────────────
# The list endpoint returns an array under .demos
# Each demo has: title, slug, filename (for PM demos), local_url, public_url
readarray -t DEMOS < <(
    jq -r '.demos[] | @base64' "$TMP" 2>/dev/null || true
)
rm -f "$TMP"

if [[ ${#DEMOS[@]} -eq 0 ]]; then
    echo "  No demos found."
    exit 0
fi

MATCHED=0
DELETED=0
FAILED=0

for entry in "${DEMOS[@]}"; do
    # Decode JSON
    DECODED=$(echo "$entry" | base64 -d)
    TITLE=$(echo "$DECODED" | jq -r '.title // empty')
    SLUG=$(echo "$DECODED" | jq -r '.slug // empty')
    FILENAME=$(echo "$DECODED" | jq -r '.filename // empty')

    if [[ -z "$TITLE" || -z "$SLUG" ]]; then
        continue
    fi

    # Check if title matches any test pattern
    IS_TEST=false
    for pattern in "${PATTERNS[@]}"; do
        if echo "$TITLE" | grep -iq "$pattern"; then
            IS_TEST=true
            break
        fi
    done

    if [[ "$IS_TEST" != "true" ]]; then
        continue
    fi

    MATCHED=$((MATCHED + 1))

    # Determine what to delete from the container filesystem
    if [[ -n "$FILENAME" ]]; then
        # PM quick demo: flat .html file
        TARGET="data/media/demos/${FILENAME}"
        TARGET_TYPE="PM demo (flat HTML)"
    else
        # Workflow demo: subdirectory with metadata.json
        TARGET="data/media/demos/${SLUG}"
        TARGET_TYPE="Workflow demo (directory)"
    fi

    echo ""
    echo "  🗑  #$MATCHED: $TITLE"
    echo "       Type: $TARGET_TYPE"
    echo "       Path: $TARGET"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "       [DRY RUN] Would delete from container"
        continue
    fi

    # ── Delete from container filesystem ───────────────────
    if docker exec "$CONTAINER_NAME" test -e "/$TARGET" 2>/dev/null; then
        if docker exec "$CONTAINER_NAME" rm -rf "/$TARGET" 2>/dev/null; then
            echo "       ✅ Deleted from container"
            DELETED=$((DELETED + 1))
        else
            echo "       ⚠ Failed to delete from container"
            FAILED=$((FAILED + 1))
        fi
    else
        echo "       ℹ  File not found in container (may already be cleaned)"
        DELETED=$((DELETED + 1))
    fi
done

# ── Summary ─────────────────────────────────────────────────
echo ""
echo "==========================================================="
if [[ "$DRY_RUN" == "true" ]]; then
    echo "  Dry run: found $MATCHED test demo(s) to clean up"
else
    echo "  Matched: $MATCHED  |  Deleted: $DELETED  |  Errors: $FAILED"
fi
echo "==========================================================="
