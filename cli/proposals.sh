#!/usr/bin/env bash
# =====================================================================
# proposals.sh — CLI for the harness-change proposal store
# (experience_improvement_todo.md Phase 3).
#
# The harness_reflection job (Tier 1) PROPOSES; this CLI is how Chuck
# reviews. Applying a proposal (Tier 2) is always manual — this tool
# only moves the status:
#
#   open -> accepted | dismissed        (accepted -> applied)
#
# Talks to the skill-runner /api/proposals* endpoints (admin-key
# protected), same pattern as memory-admin.sh.
#
# Config (env vars, all optional with sensible defaults):
#   SKILL_RUNNER_URL     base URL (default http://192.168.4.54:8091)
#   MEMORY_ADMIN_API_KEY the admin key (or read from MEMORY_ADMIN_KEY_FILE)
#   MEMORY_ADMIN_KEY_FILE path to a file containing the admin key
#
# Usage:
#   proposals.sh list [status] [--limit N]
#   proposals.sh show <id>
#   proposals.sh accept <id>
#   proposals.sh dismiss <id>
#   proposals.sh mark-applied <id>
#
# Exit codes: 0 = ok, 1 = usage/config error, 2 = API error.
# =====================================================================
set -euo pipefail

SKILL_RUNNER_URL="${SKILL_RUNNER_URL:-http://192.168.4.54:8091}"

# Resolve the admin key: env var wins, else the key file, else error.
ADMIN_KEY="${MEMORY_ADMIN_API_KEY:-}"
if [[ -z "$ADMIN_KEY" && -n "${MEMORY_ADMIN_KEY_FILE:-}" && -f "${MEMORY_ADMIN_KEY_FILE:-}" ]]; then
  ADMIN_KEY="$(tr -d '[:space:]' < "$MEMORY_ADMIN_KEY_FILE")"
fi
if [[ -z "$ADMIN_KEY" ]]; then
  echo "ERROR: no admin key. Set MEMORY_ADMIN_API_KEY or MEMORY_ADMIN_KEY_FILE." >&2
  exit 1
fi

json() { python3 -m json.tool 2>/dev/null || cat; }

call() {
  # call METHOD PATH [JSON_BODY]
  local method="$1" path="$2" body="${3:-}"
  local args=(-s -X "$method" -H "X-API-Key: $ADMIN_KEY" -H "Content-Type: application/json")
  if [[ -n "$body" ]]; then
    args+=(-d "$body")
  fi
  curl "${args[@]}" "${SKILL_RUNNER_URL}${path}"
}

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

cmd="${1:-}"
shift || true

case "$cmd" in
  list)
    status=""
    limit=50
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --limit)
          limit="${2:?--limit needs a value}"
          shift 2
          ;;
        open|accepted|dismissed|applied)
          status="$1"
          shift
          ;;
        *)
          echo "Unknown argument '$1' (valid: open|accepted|dismissed|applied|--limit N)" >&2
          exit 1
          ;;
      esac
    done
    [[ "$limit" =~ ^[0-9]+$ ]] || { echo "--limit must be a number" >&2; exit 1; }
    path="/api/proposals?limit=${limit}"
    [[ -n "$status" ]] && path="${path}&status=${status}"
    call GET "$path" | json
    ;;
  show)
    id="${1:-}"
    [[ "$id" =~ ^[0-9]+$ ]] || usage
    call GET "/api/proposals/${id}" | json
    ;;
  accept|dismiss|mark-applied)
    id="${1:-}"
    [[ "$id" =~ ^[0-9]+$ ]] || usage
    case "$cmd" in
      accept)        st="accepted" ;;
      dismiss)       st="dismissed" ;;
      mark-applied)  st="applied" ;;
    esac
    call POST "/api/proposals/${id}/transition" "{\"status\":\"${st}\"}" | json
    ;;
  *)
    usage
    ;;
esac