#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Cleanup script for test presentations
#
# Usage:
#   bash cleanup_presentations.sh                    # delete all test presentations
#   bash cleanup_presentations.sh "Smoke Test"       # delete only matching titles
#   bash cleanup_presentations.sh --dry-run          # preview what would be deleted
#
# Test title patterns (matched case-insensitively):
#   - "Smoke Test"               (from test_presentation.sh)
#   - "machine learning"         (from Siri test intent)
#   - "Homelab Infrastructure"   (from outline test)
#
# This script deletes from BOTH the harness (local files + metadata)
# and Presenton (database entries in the web UI).
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Load environment ────────────────────────────────────────
if [[ ! -f "$SCRIPT_DIR/../../.env" ]]; then
    echo "❌ .env file not found at $SCRIPT_DIR/../../.env"
    exit 1
fi
set -a; source "$SCRIPT_DIR/../../.env"; set +a

BASE_URL="${BASE_LOCAL:-http://192.168.4.54:8090}"
API_KEY="${HARNESS_API_KEY}"

# On the host, presenton:80 won't resolve — use port 5000
# Inside the container, presenton:80 works fine
if hostname | grep -q "ai-harness"; then
    PRESENTON_URL="${PRESENTON_BASE_URL:-http://presenton:80}"
else
    PRESENTON_URL="${PRESENTON_HOST_URL:-http://192.168.4.54:5000}"
fi

PRESENTON_USER="${PRESENTON_AUTH_USERNAME:-presenton}"
PRESENTON_PASS="${PRESENTON_AUTH_PASSWORD:-changeme123}"

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
        "machine learning"
        "homelab infrastructure"
    )
fi

echo "==========================================================="
echo "  Presentation Cleanup"
echo "==========================================================="
echo "  Harness:  $BASE_URL"
echo "  Presenton: $PRESENTON_URL"
echo "  Patterns: ${PATTERNS[*]}"
[[ "$DRY_RUN" == "true" ]] && echo "  ⚠ DRY RUN — no changes will be made"
echo "-----------------------------------------------------------"

# ── Fetch presentation list ─────────────────────────────────
TMP=$(mktemp)
HTTP_CODE=$(curl -s -o "$TMP" -w "%{http_code}" \
    "${BASE_URL}/presentation/list" \
    -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"

if [[ "$HTTP_CODE" != "200" ]]; then
    echo "❌ Failed to fetch presentation list (HTTP $HTTP_CODE)"
    rm -f "$TMP"
    exit 1
fi

# ── Identify test presentations ─────────────────────────────
# Extract each presentation as a base64-encoded JSON blob
readarray -t PRESENTATIONS < <(
    jq -r '.presentations[] | @base64' "$TMP" 2>/dev/null || true
)
rm -f "$TMP"

if [[ ${#PRESENTATIONS[@]} -eq 0 ]]; then
    echo "  No presentations found."
    exit 0
fi

MATCHED=0
DELETED=0
FAILED=0

for entry in "${PRESENTATIONS[@]}"; do
    # Decode JSON
    DECODED=$(echo "$entry" | base64 -d)
    TITLE=$(echo "$DECODED" | jq -r '.title // empty')
    PRESENTATION_ID=$(echo "$DECODED" | jq -r '.presentation_id // empty')
    FILENAME=$(echo "$DECODED" | jq -r '.filename // empty')
    VERSION=$(echo "$DECODED" | jq -r '.version // 0')

    if [[ -z "$TITLE" || -z "$PRESENTATION_ID" ]]; then
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
    echo ""
    echo "  🗑  #$MATCHED: $TITLE (v${VERSION})"
    echo "       File: $FILENAME"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "       [DRY RUN] Would delete from harness + Presenton"
        continue
    fi

    # ── Delete from harness (local files + metadata) ───────
    CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X DELETE "${BASE_URL}/presentation/${PRESENTATION_ID}" \
        -H "X-API-Key: ${API_KEY}" 2>/dev/null) || CODE="000"

    if [[ "$CODE" == "200" ]]; then
        echo "       ✅ Harness: deleted local files"
    else
        echo "       ⚠ Harness: HTTP $CODE (files may remain)"
        FAILED=$((FAILED + 1))
    fi

    # ── Delete from Presenton (database) ───────────────────
    CODE2=$(curl -s -o /dev/null -w "%{http_code}" \
        -X DELETE "${PRESENTON_URL}/api/v1/ppt/presentation/${PRESENTATION_ID}" \
        -u "${PRESENTON_USER}:${PRESENTON_PASS}" \
        -H "Accept: application/json" \
        --max-time 15 2>/dev/null) || CODE2="000"

    if [[ "$CODE2" == "204" || "$CODE2" == "200" ]]; then
        echo "       ✅ Presenton: deleted from DB"
    else
        echo "       ⚠ Presenton: HTTP $CODE2 (may still show in UI)"
        FAILED=$((FAILED + 1))
    fi

    DELETED=$((DELETED + 1))
done

# ── Summary ─────────────────────────────────────────────────
echo ""
echo "==========================================================="
if [[ "$DRY_RUN" == "true" ]]; then
    echo "  Dry run: found $MATCHED test presentation(s) to clean up"
else
    echo "  Matched: $MATCHED  |  Deleted: $DELETED  |  Errors: $FAILED"
fi
echo "==========================================================="
