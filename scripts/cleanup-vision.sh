#!/usr/bin/env bash
# cleanup-vision.sh — housekeeping for mcp_vision artifacts (manual; no cron).
#
# Artifacts live in /home/chuck/data/workspace/vision/<slug>/ (frames,
# reports, chapter maps). They are ephemeral, NON-public data. The LLM can
# also clean via the vision_cleanup MCP tool; this script is the host-side
# equivalent.
#
# Usage:
#   ./scripts/cleanup-vision.sh --dry-run            # list what would be deleted
#   ./scripts/cleanup-vision.sh                      # delete dirs older than 7 days
#   ./scripts/cleanup-vision.sh --days 30            # custom age threshold
#   ./scripts/cleanup-vision.sh --all                # delete everything
#   ./scripts/cleanup-vision.sh --slug <slug>        # delete one artifact dir
set -euo pipefail

ROOT="/home/chuck/data/workspace/vision"
DAYS=7
DRY_RUN=false
DO_ALL=false
SLUG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --all) DO_ALL=true; shift ;;
    --days) DAYS="$2"; shift 2 ;;
    --slug) SLUG="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -d "$ROOT" ]] || { echo "nothing to do ($ROOT missing)"; exit 0; }

deleted=0
freed=0
for d in "$ROOT"/*/; do
  [[ -d "$d" ]] || continue
  name=$(basename "$d")
  if [[ -n "$SLUG" ]]; then
    [[ "$name" == "$SLUG" ]] || continue
  elif $DO_ALL; then
    :
  else
    # skip dirs modified within DAYS
    if [[ $(find "$d" -maxdepth 0 -mtime -"$DAYS" 2>/dev/null) ]]; then
      continue
    fi
  fi
  size=$(du -sb "$d" 2>/dev/null | cut -f1)
  if $DRY_RUN; then
    echo "would delete: $name (${size:-0} bytes)"
  else
    rm -rf "$d"
    echo "deleted: $name (${size:-0} bytes)"
  fi
  deleted=$((deleted + 1))
  freed=$((freed + ${size:-0}))
done

echo "done: $deleted dir(s), $((freed / 1024 / 1024)) MB freed$([[ $DRY_RUN == true ]] && echo ' (dry run)')"