#!/usr/bin/env bash
# =====================================================================
# memory-admin.sh — CLI wrapper for the skill-runner memory admin API
# (memory_todo.md Phase 8 item 1).
#
# Day-to-day management of long-term memory without opening a browser.
# Talks to the skill-runner /api/memory/* endpoints (admin-key protected).
#
# Config (env vars, all optional with sensible defaults):
#   SKILL_RUNNER_URL     base URL (default http://192.168.4.54:8091)
#   MEMORY_ADMIN_API_KEY the admin key (or read from MEMORY_ADMIN_KEY_FILE)
#   MEMORY_ADMIN_KEY_FILE path to a file containing the admin key
#
# Usage:
#   memory-admin.sh health
#   memory-admin.sh list <user_id> [query] [--scope private|household|all] [--limit N]
#   memory-admin.sh search <user_id> <query>
#   memory-admin.sh update <memory_id> <new text...>
#   memory-admin.sh delete <memory_id>
#   memory-admin.sh delete-user <user_id> [--export]
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
  local args=(-s -X "$method" -H "X-API-Key: $ADMIN_KEY" -H "Content-Type: application/json")
  if [[ -n "$body" ]]; then
    args+=(-d "$body")
  fi
  curl "${args[@]}" "${SKILL_RUNNER_URL}${path}"
}

usage() {
  sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

cmd="${1:-}"
case "$cmd" in
  health)
    call GET "/api/memory/health" | json
    ;;
  list)
    shift
    user="${1:-}"; [[ -n "$user" ]] || usage
    query="" scope="all" limit=50
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --scope) scope="$2"; shift 2;;
        --limit) limit="$2"; shift 2;;
        *) query="$1"; shift;;
      esac
    done
    if [[ -n "$query" ]]; then
      q=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$query")
      call GET "/api/memory/users/${user}?q=${q}&scope=${scope}&limit=${limit}" | json
    else
      call GET "/api/memory/users/${user}?scope=${scope}&limit=${limit}" | json
    fi
    ;;
  search)
    shift
    user="${1:-}"; query="${2:-}"
    [[ -n "$user" && -n "$query" ]] || usage
    q=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$query")
    call GET "/api/memory/users/${user}?q=${q}" | json
    ;;
  update)
    shift
    mid="${1:-}"; shift || true
    text="$*"
    [[ -n "$mid" && -n "$text" ]] || usage
    body=$(python3 -c "import json,sys;print(json.dumps({'text':sys.argv[1]}))" "$text")
    call PATCH "/api/memory/${mid}" "$body" | json
    ;;
  delete)
    shift
    mid="${1:-}"; [[ -n "$mid" ]] || usage
    call DELETE "/api/memory/${mid}" | json
    ;;
  delete-user)
    shift
    user="${1:-}"; [[ -n "$user" ]] || usage
    export_flag=""
    [[ "${2:-}" == "--export" ]] && export_flag="?export=true"
    call DELETE "/api/memory/users/${user}${export_flag}" | json
    ;;
  *)
    usage
    ;;
esac