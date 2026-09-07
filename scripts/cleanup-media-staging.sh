#!/usr/bin/env bash
# cleanup-media-staging.sh — housekeeping for the media-pipeline staging area
# (manual; no cron — same pattern as cleanup-vision.sh).
#
# Staging lives in /home/chuck/workspace/media (the mcp_media container's
# MEDIA_STAGING_DIR): scratch files for media_put / trim / freeze / caption
# local inputs. Ephemeral, NON-public. The mcp_media container rw-mounts it,
# so files here are visible to the pipeline as local sources.
#
# Age threshold: MEDIA_STAGING_MAX_AGE_DAYS from /home/chuck/homelab/.env
# (default 7).
#
# Usage:
#   ./scripts/cleanup-media-staging.sh --dry-run    # list what would be deleted
#   ./scripts/cleanup-media-staging.sh              # delete files older than the threshold
#   ./scripts/cleanup-media-staging.sh --days 30    # custom age threshold
#   ./scripts/cleanup-media-staging.sh --all        # delete everything
set -euo pipefail

ROOT="/home/chuck/workspace/media"
ENV_FILE="/home/chuck/homelab/.env"
DAYS=7
DRY_RUN=false
DO_ALL=false

# .env-configurable default (MEDIA_STAGING_MAX_AGE_DAYS), overridable via --days.
if [[ -f "$ENV_FILE" ]]; then
  v=$(grep -E '^[[:space:]]*MEDIA_STAGING_MAX_AGE_DAYS=' "$ENV_FILE" | tail -1 | cut -d= -f2 | tr -d '"' | tr -d "'" || true)
  [[ "$v" =~ ^[0-9]+$ ]] && DAYS="$v"
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --all) DO_ALL=true; shift ;;
    --days) DAYS="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -d "$ROOT" ]] || { echo "nothing to do ($ROOT missing)"; exit 0; }

deleted=0
freed=0
# Files and subdirs older than DAYS (top-level entries, like the vision script).
while IFS= read -r -d '' entry; do
  name=$(basename "$entry")
  size=$(du -sb "$entry" 2>/dev/null | cut -f1 || echo 0)
  if $DRY_RUN; then
    echo "would delete: $name (${size:-0} bytes)"
  else
    rm -rf "$entry"
    echo "deleted: $name (${size:-0} bytes)"
  fi
  deleted=$((deleted + 1))
  freed=$((freed + ${size:-0}))
done < <(
  if $DO_ALL; then
    find "$ROOT" -mindepth 1 -maxdepth 1 -print0
  else
    find "$ROOT" -mindepth 1 -maxdepth 1 -mtime +"$DAYS" -print0
  fi
)

echo "done: $deleted item(s), $((freed / 1024 / 1024)) MB freed$([[ $DRY_RUN == true ]] && echo ' (dry run)')"