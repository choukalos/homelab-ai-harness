#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# AI Harness — Selective Test Runner
#
# Run all smoke tests or pick specific groups.
#   bash tests/run-tests.sh                  # default set (excludes slow media)
#   bash tests/run-tests.sh apps             # only apps tests
#   bash tests/run-tests.sh apps,creative    # comma-separated groups
#   bash tests/run-tests.sh --all            # everything including media
#   bash tests/run-tests.sh --list           # show available groups
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

# ── Available test groups and their scripts ─────────────────
# Format: group_name|script_path|description|slow?
#   slow=true means skipped by default (use --all to include)

declare -A GROUP_SCRIPT
declare -A GROUP_DESC
declare -A GROUP_SLOW

GROUP_SCRIPT[infra]="${SCRIPT_DIR}/smoke/test_infra.sh"
GROUP_DESC[infra]="Infra (workflows, tasks, scheduler)"
GROUP_SLOW[infra]=false

GROUP_SCRIPT[research]="${SCRIPT_DIR}/smoke/test_research.sh"
GROUP_DESC[research]="Research (web search, deep research, brief)"
GROUP_SLOW[research]=false

GROUP_SCRIPT[knowledge]="${SCRIPT_DIR}/smoke/test_knowledge.sh"
GROUP_DESC[knowledge]="Knowledge (family KB ingest, search, ask)"
GROUP_SLOW[knowledge]=false

GROUP_SCRIPT[creative]="${SCRIPT_DIR}/smoke/test_creative.sh"
GROUP_DESC[creative]="Creative (charts + presentations)"
GROUP_SLOW[creative]=false

GROUP_SCRIPT[media]="${SCRIPT_DIR}/smoke/test_media.sh"
GROUP_DESC[media]="Media (image gen, clips)"
GROUP_SLOW[media]=true

GROUP_SCRIPT[apps]="${SCRIPT_DIR}/smoke/test_apps.sh"
GROUP_DESC[apps]="Apps (quick demo + workflow demo)"
GROUP_SLOW[apps]=false

GROUP_SCRIPT[filetools]="${SCRIPT_DIR}/smoke/test_filetools.sh"
GROUP_DESC[filetools]="Filetools (stub)"
GROUP_SLOW[filetools]=false

GROUP_SCRIPT[url_rewriting]="${SCRIPT_DIR}/smoke/test_url_rewriting.sh"
GROUP_DESC[url_rewriting]="URL rewriting (cross-module URL verification)"
GROUP_SLOW[url_rewriting]=false

GROUP_SCRIPT[channels]="${SCRIPT_DIR}/channels/test_openwebui.sh"
GROUP_DESC[channels]="Channels (OpenWebUI tool endpoints)"
GROUP_SLOW[channels]=false

# Ordered list for display and default run order
GROUPS_ORDER=(infra research knowledge creative media apps filetools url_rewriting channels)

# ── Helpers ──────────────────────────────────────────────────

list_groups() {
    echo "Available test groups:"
    echo ""
    printf "  %-25s %-40s %s\n" "GROUP" "DESCRIPTION" "SLOW?"
    printf "  %-25s %-40s %s\n" "-----" "-----------" "-----"
    for grp in "${GROUPS_ORDER[@]}"; do
        slow_label="${GROUP_SLOW[$grp]}"
        badge=""
        if [[ "$slow_label" == "true" ]]; then
            badge="slow"
        fi
        printf "  %-25s %-40s %s\n" "$grp" "${GROUP_DESC[$grp]}" "$badge"
    done
    echo ""
    echo "Default run excludes groups marked 'slow'. Use --all to include them."
}

run_test() {
    local grp="$1"
    local script="${GROUP_SCRIPT[$grp]}"
    local desc="${GROUP_DESC[$grp]}"

    echo ""
    echo "========================================"
    echo "[RUN]  ${desc}"
    echo "========================================"

    if bash "${script}"; then
        echo "[OK]   ${desc}"
        return 0
    else
        echo "[FAIL] ${desc}"
        return 1
    fi
}

# ── Argument parsing ────────────────────────────────────────

if [[ $# -eq 0 ]]; then
    # Default: run all non-slow groups
    SELECTED=()
    for grp in "${GROUPS_ORDER[@]}"; do
        if [[ "${GROUP_SLOW[$grp]}" == "false" ]]; then
            SELECTED+=("$grp")
        fi
    done
elif [[ "$1" == "--list" ]]; then
    list_groups
    exit 0
elif [[ "$1" == "--all" ]]; then
    # All groups including slow ones
    SELECTED=("${GROUPS_ORDER[@]}")
    if [[ $# -gt 1 ]]; then
        # --all with extra args: error
        echo "❌ --all cannot be combined with group names"
        exit 1
    fi
else
    # Comma-separated group names
    IFS=',' read -ra SELECTED <<< "$1"
fi

# ── Validate selected groups ────────────────────────────────
for grp in "${SELECTED[@]}"; do
    grp="$(echo "$grp" | tr -d '[:space:]')"  # trim whitespace
    if [[ -z "${GROUP_SCRIPT[$grp]+x}" ]]; then
        echo "❌ Unknown test group: '${grp}'"
        echo "   Run '${0} --list' to see available groups."
        exit 1
    fi
done

# ── Banner ───────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  AI Harness — Test Runner"
echo "  Base URL: ${BASE_LOCAL:-http://${THOR_IP:-192.168.4.54}:8090}"
echo "  Groups:   ${SELECTED[*]}"
echo "========================================"

# ── Run selected groups ──────────────────────────────────────
TOTAL=0
PASSED=0
FAILED=0
SKIPPED=0

for grp in "${SELECTED[@]}"; do
    grp="$(echo "$grp" | tr -d '[:space:]')"
    TOTAL=$((TOTAL + 1))

    run_test "$grp"
    if [[ $? -eq 0 ]]; then
        PASSED=$((PASSED + 1))
    else
        FAILED=$((FAILED + 1))
    fi
done

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  Results: ${PASSED} passed, ${FAILED} failed, ${SKIPPED} skipped (total: ${TOTAL})"
if [[ "${FAILED}" -eq 0 ]]; then
    echo "  ✅ All selected tests passed"
else
    echo "  ❌ Some tests failed"
fi
echo "========================================"

exit "${FAILED}"
