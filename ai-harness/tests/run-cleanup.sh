#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# AI Harness — Selective Cleanup Runner
#
# Run all cleanup scripts or pick specific ones.
#   bash tests/run-cleanup.sh                # run all cleanup
#   bash tests/run-cleanup.sh --dry-run      # preview without deleting
#   bash tests/run-cleanup.sh demos          # just demo cleanup
#   bash tests/run-cleanup.sh presentations  # just presentation cleanup
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

# ── Available cleanup targets ───────────────────────────────
declare -A CLEANUP_SCRIPT
declare -A CLEANUP_DESC

CLEANUP_SCRIPT[demos]="${SCRIPT_DIR}/cleanup_demos.sh"
CLEANUP_DESC[demos]="Demo artifacts (PM quick demos + workflow demos)"

CLEANUP_SCRIPT[presentations]="${SCRIPT_DIR}/cleanup_presentations.sh"
CLEANUP_DESC[presentations]="Presentation artifacts (harness files + Presenton DB)"

CLEANUPS_ORDER=(demos presentations)

# ── Helpers ──────────────────────────────────────────────────

list_targets() {
    echo "Available cleanup targets:"
    echo ""
    printf "  %-25s %s\n" "TARGET" "DESCRIPTION"
    printf "  %-25s %s\n" "------" "-----------"
    for tgt in "${CLEANUPS_ORDER[@]}"; do
        printf "  %-25s %s\n" "$tgt" "${CLEANUP_DESC[$tgt]}"
    done
    echo ""
    echo "Usage: ${0} [--dry-run] [target[,target...]]"
}

run_cleanup() {
    local dry_flag=""
    local tgt
    if [[ "${1:-}" == "--dry-run" ]]; then
        dry_flag="--dry-run"
        shift
    fi
    tgt="$1"
    local script="${CLEANUP_SCRIPT[$tgt]}"
    local desc="${CLEANUP_DESC[$tgt]}"

    echo ""
    echo "========================================"
    echo "[CLEANUP]  ${desc}"
    echo "========================================"

    if [[ -n "$dry_flag" ]]; then
        if bash "${script}" "$dry_flag"; then
            echo "[OK]   ${desc}"
            return 0
        else
            echo "[FAIL] ${desc}"
            return 1
        fi
    else
        if bash "${script}"; then
            echo "[OK]   ${desc}"
            return 0
        else
            echo "[FAIL] ${desc}"
            return 1
        fi
    fi
}

# ── Argument parsing ────────────────────────────────────────
DRY_RUN_ARGS=""
TARGET_ARGS=""

for arg in "$@"; do
    if [[ "$arg" == "--dry-run" ]]; then
        DRY_RUN_ARGS="--dry-run"
    else
        TARGET_ARGS="$arg"
    fi
done

if [[ -z "$TARGET_ARGS" ]]; then
    # Default: run all cleanup targets
    SELECTED=("${CLEANUPS_ORDER[@]}")
elif [[ "$TARGET_ARGS" == "--list" ]]; then
    list_targets
    exit 0
else
    # Comma-separated target names
    IFS=',' read -ra SELECTED <<< "$TARGET_ARGS"
fi

# ── Validate selected targets ────────────────────────────────
for tgt in "${SELECTED[@]}"; do
    tgt="$(echo "$tgt" | tr -d '[:space:]')"  # trim whitespace
    if [[ -z "${CLEANUP_SCRIPT[$tgt]+x}" ]]; then
        echo "❌ Unknown cleanup target: '${tgt}'"
        echo "   Run '${0} --list' to see available targets."
        exit 1
    fi
done

# ── Banner ───────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  AI Harness — Cleanup Runner"
[[ -n "$DRY_RUN_ARGS" ]] && echo "  ⚠ DRY RUN — no changes will be made"
echo "  Targets:  ${SELECTED[*]}"
echo "========================================"

# ── Run selected targets ─────────────────────────────────────
TOTAL=0
PASSED=0
FAILED=0

for tgt in "${SELECTED[@]}"; do
    tgt="$(echo "$tgt" | tr -d '[:space:]')"
    TOTAL=$((TOTAL + 1))

    run_cleanup $DRY_RUN_ARGS "$tgt"
    if [[ $? -eq 0 ]]; then
        PASSED=$((PASSED + 1))
    else
        FAILED=$((FAILED + 1))
    fi
done

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  Results: ${PASSED} passed, ${FAILED} failed (total: ${TOTAL})"
if [[ "${FAILED}" -eq 0 ]]; then
    echo "  ✅ All cleanup targets completed"
else
    echo "  ❌ Some cleanup targets failed"
fi
echo "========================================"

exit "${FAILED}"
