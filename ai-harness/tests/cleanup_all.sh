#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# AI Harness — Combined Cleanup
#
# Pre-test cleanup: removes demo + presentation test artifacts,
# then optionally resets persistent state (workflow checkpoints).
#
#   bash tests/cleanup_all.sh                     # cleanup artifacts only
#   bash tests/cleanup_all.sh --with-state-reset  # + reset workflow checkpoints
#   bash tests/cleanup_all.sh --dry-run            # preview without deleting
#   bash tests/cleanup_all.sh --help               # show usage
# ─────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Load environment ────────────────────────────────────────
if [[ ! -f "${SCRIPT_DIR}/../../.env" ]]; then
    echo "❌ .env file not found at ${SCRIPT_DIR}/../../.env"
    exit 1
fi
set -a
source "${SCRIPT_DIR}/../../.env"
set +a

# ── Helpers ──────────────────────────────────────────────────

show_help() {
    cat <<EOF
Usage: bash tests/cleanup_all.sh [OPTIONS]

Options:
  --with-state-reset   Also reset workflow checkpoints (Celery + Redis)
  --dry-run            Preview what would be deleted without making changes
  --help               Show this help message

This script combines:
  • cleanup_demos.sh          (demo artifacts from /data/media/demos/)
  • cleanup_presentations.sh  (presentation artifacts from harness + Presenton)

Optional state reset removes:
  • Workflow job checkpoints from Redis (demo workflow + deep research)
  • Celery task results cache

For fine-grained control, use run-cleanup.sh directly.
EOF
}

# ── Argument parsing ────────────────────────────────────────
DRY_RUN_ARGS=""
STATE_RESET=false

for arg in "$@"; do
    case "$arg" in
        --dry-run)
            DRY_RUN_ARGS="--dry-run"
            ;;
        --with-state-reset)
            STATE_RESET=true
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo "❌ Unknown option: $arg"
            show_help
            exit 1
            ;;
    esac
done

# ── Banner ───────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  AI Harness — Combined Cleanup"
[[ -n "$DRY_RUN_ARGS" ]] && echo "  ⚠ DRY RUN — no changes will be made"
[[ "$STATE_RESET" == "true" ]] && echo "  🔄 State reset: workflow checkpoints + Celery results"
echo "========================================"

# ── Run artifact cleanup ─────────────────────────────────────
echo ""
echo "── Artifact cleanup ─────────────────────────────"
if bash "${SCRIPT_DIR}/run-cleanup.sh" $DRY_RUN_ARGS; then
    echo "[OK]   Artifact cleanup completed"
else
    echo "[WARN] Artifact cleanup had errors — continuing..."
fi

# ── Optional state reset ─────────────────────────────────────
if [[ "$STATE_RESET" == "true" ]]; then
    echo ""
    echo "── State reset ──────────────────────────────────"

    BASE_URL="${BASE_LOCAL:-http://${THOR_IP:-192.168.4.54}:8090}"
    API_KEY="${HARNESS_API_KEY:-}"
    CONTAINER_NAME="ai-harness"

    # ── Flush Celery results via API ────────────────────────────
    if curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/health" 2>/dev/null | grep -q "200"; then
        # Delete all workflow checkpoints via the workflow endpoint
        echo "  Clearing workflow checkpoints..."

        # Get all demo workflow jobs and clear their checkpoints
        JOBS=$(curl -s "${BASE_URL}/demos/jobs" -H "X-API-Key: ${API_KEY}" 2>/dev/null \
            | jq -r '.jobs[]? | .thread_id // empty' 2>/dev/null || true)

        if [[ -n "$JOBS" ]]; then
            while IFS= read -r thread_id; do
                if [[ "$DRY_RUN_ARGS" == "--dry-run" ]]; then
                    echo "    [DRY RUN] Would delete checkpoint for thread: $thread_id"
                else
                    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
                        -X DELETE "${BASE_URL}/demos/jobs/${thread_id}/checkpoint" \
                        -H "X-API-Key: ${API_KEY}" 2>/dev/null) || HTTP_CODE="000"
                    if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "204" ]]; then
                        echo "    ✅ Cleared checkpoint: $thread_id"
                    else
                        echo "    ⚠ Failed to clear checkpoint $thread_id (HTTP $HTTP_CODE)"
                    fi
                fi
            done <<< "$THREADS"
        else
            echo "    ℹ  No workflow threads found to clear"
        fi
    else
        echo "  ⚠ Harness not reachable — skipping state reset"
    fi

    # ── Flush Redis Celery results via docker exec ──────────────
    echo "  Clearing Celery task results cache..."
    if [[ "$DRY_RUN_ARGS" == "--dry-run" ]]; then
        echo "    [DRY RUN] Would flush Redis celery results keys"
    else
        if docker exec "$CONTAINER_NAME" redis-cli KEYS "celery*" 2>/dev/null | grep -q .; then
            docker exec "$CONTAINER_NAME" redis-cli KEYS "celery*" 2>/dev/null \
                | xargs -r docker exec -i "$CONTAINER_NAME" redis-cli DEL 2>/dev/null
            echo "    ✅ Redis celery results flushed"
        else
            echo "    ℹ  No celery keys in Redis"
        fi
    fi

    echo "[OK]   State reset completed"
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  ✅ Cleanup complete"
echo "========================================"
