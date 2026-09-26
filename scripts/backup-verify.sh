#!/usr/bin/env bash
# =====================================================================
# backup-verify.sh — disposable restore tests (plan §3.6)
# =====================================================================
# Runs backup-restore.sh --test against the latest committed run for a
# set of key items. Never touches live state: each test loads the
# backup into a throwaway docker container and runs a smoke query.
#
# Usage:
#   backup-verify.sh [item ...]     # default items: mysql/homelab,
#                                   #   qdrant/mem0_memories,
#                                   #   litellm-postgres
#   backup-verify.sh --root DIR     # local testing (no mount)
#   backup-verify.sh --host ID
#   backup-verify.sh --config FILE
#
# Exit: 0 all pass · 1 any failure
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DEFAULT_ITEMS=(mysql/homelab qdrant/mem0_memories litellm-postgres)
ITEMS=()
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root|--host|--config) EXTRA_ARGS+=("$1" "${2:?}"); shift 2 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) ITEMS+=("$1"); shift ;;
  esac
done
if [[ ${#ITEMS[@]} -eq 0 ]]; then
  ITEMS=("${DEFAULT_ITEMS[@]}")
fi

echo "backup-verify: testing ${#ITEMS[@]} item(s) against latest run (disposable containers)…"
rc=0
for item in "${ITEMS[@]}"; do
  echo "--- $item"
  if bash "$SCRIPT_DIR/backup-restore.sh" --item "$item" --test "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"; then
    echo "PASS: $item"
  else
    echo "FAIL: $item"
    rc=1
  fi
done
exit "$rc"