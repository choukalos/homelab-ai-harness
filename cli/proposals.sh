#!/usr/bin/env bash
# =====================================================================
# proposals.sh — CLI for harness change proposals (Phase 3,
# experience_improvement_todo.md).
#
# The weekly harness_reflection skill (Tier 1, PROPPOSE ONLY) creates
# `open` proposals (markdown in proposals/ + a row in the `proposals`
# MySQL table). Humans drive the lifecycle:
#   open -> accepted | dismissed -> applied
# via this CLI (admin-key protected, talks to the skill-runner
# /api/proposals/* endpoints — same pattern as cli/memory-admin.sh).
#
# Config (env vars, all optional with sensible defaults):
#   SKILL_RUNNER_URL     base URL (default http://192.168.4.54:8091)
#   MEMORY_ADMIN_API_KEY the admin key (or read from MEMORY_ADMIN_KEY_FILE)
#   MEMORY_ADMIN_KEY_FILE path to a file containing the admin key
#
# Usage:
#   proposals.sh list [status] [--limit N]
#   proposals.sh show <slug>
#   proposals.sh accept <slug>
#   proposals.sh dismiss <slug>
#   proposals.sh mark-applied <slug>
#
# Exit codes: 0 = ok, 1 = usage/config error, 2 = API error.
# =====================================================================
set -euo pipefail

SKILL_RUNNER_URL="${SKILL_RUNNER_URL:-http://192.168.4.54:8091}"

# Resolve the admin key: env var wins, else the key file, else error.
ADMIN_KEY="${MEMORY_ADMIN_API_KEY:-}"
if [[ -z "$ADMIN_KEY" && -n "${MEMORY_ADMIN_KEY_FILE:-}" && -f "${MEMORY_ADMIN_KEY_FILE}" ]]; then
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
  local args=(-s -w '\n%{http_code}' -X "$method" -H "X-API-Key: $ADMIN_KEY" -H "Content-Type: application/json")
  if [[ -n "$body" ]]; then
    args+=(-d "$body")
  fi
  curl "${args[@]}" "${SKILL_RUNNER_URL}${path}"
}

die_api() {
  # die_api HTTP_CODE BODY
  local code="$1" body="$2"
  if [[ "$code" -ge 200 && "$code" -lt 300 ]]; then
    echo "$body" | json
    return 0
  fi
  echo "ERROR (HTTP $code): $body" >&2
  exit 2
}

usage() {
  sed -n '3,24p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

cmd="${1:-}"
case "$cmd" in
  list)
    shift
    status="" limit=50
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --limit) limit="$2"; shift 2;;
        open|accepted|dismissed|applied) status="$1"; shift;;
        *) status="$1"; shift;;
      esac
    done
    path="/api/proposals"
    sep="?"
    if [[ -n "$status" ]]; then
      path="${path}?status=${status}"
      sep="&"
    fi
    path="${path}${sep}limit=${limit}"
    out="$(call GET "$path")"
    code="${out##*$'\n'}"; body="${out%$'\n'*}"
    die_api "$code" "$body"
    ;;
  show)
    shift
    slug="${1:-}"; [[ -n "$slug" ]] || usage
    out="$(call GET "/api/proposals/$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=""))' "$slug")")"
    code="${out##*$'\n'}"; body="${out%$'\n'*}"
    die_api "$code" "$body"
    ;;
  accept|dismiss|mark-applied)
    shift
    slug="${1:-}"; [[ -n "$slug" ]] || usage
    case "$cmd" in
      accept) new_status="accepted";;
      dismiss) new_status="dismissed";;
      mark-applied) new_status="applied";;
    esac
    out="$(call POST "/api/proposals/$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=""))' "$slug")/${new_status}")"
    code="${out##*$'\n'}"; body="${out%$'\n'*}"
    die_api "$code" "$body"
    ;;
  *)
    usage
    ;;
esac