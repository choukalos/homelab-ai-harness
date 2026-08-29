#!/usr/bin/env bash
# =====================================================================
# backup-kb.sh — Family KB backup (kb-todo.md, K6)
# =====================================================================
# Backs up the family KB (Qdrant kb_* collections + source files):
#   1. every kb_* collection -> /home/chuck/data/backups/kb/kb_<slug>-<stamp>.snapshot
#   2. source files          -> /home/chuck/data/backups/kb/kb-sources-<stamp>.tar.gz
#      (ai-kb/raw + media + workspace — the ingest allowlist roots)
#
# This mirrors the kb_backup MCP tool (mcp_knowledge) but is an OPS
# credential holder: it uses the Qdrant ADMIN key directly, so it works
# even if the mcp_knowledge container is down. No source-tar size cap
# (the MCP tool caps at 500 MB per file).
#
# No cron in v1 — run manually: before any KB storage change and at
# phase gates (a few seconds per collection).
#
# Restore (see kb-todo.md K6 + docs/memory/IMPLEMENTATION_STATE.md
# restore notes):
#   docker run -d --name qdrant-kb-restore-test -p 16334:6333 \
#     -v /home/chuck/data/backups/kb/kb_<slug>-<stamp>.snapshot:/qdrant/snapshots/restore.snapshot:ro \
#     qdrant/qdrant:v1.18.1   # match production (pinned, Phase 9)
#   curl -s -X PUT http://localhost:16334/collections/kb_<slug>/snapshots/recover \
#     -H 'Content-Type: application/json' \
#     -d '{"location":"file:///qdrant/snapshots/restore.snapshot","priority":"snapshot"}'
#   docker rm -f qdrant-kb-restore-test
#   (Qdrant >= 1.18: PUT .../snapshots/recover with a file: URI.
#   priority MUST be "snapshot" on an empty node — the default
#   "replica" priority restores an EMPTY collection.)
#
# NOTE: Qdrant writes snapshots to /qdrant/snapshots/ INSIDE the container
# (workdir /qdrant), NOT on the mounted volume — they are ephemeral. This
# script extracts each fresh snapshot via read-only `docker exec qdrant cat`.
#
# Usage: scripts/backup-kb.sh
# Exit codes: 0 = ok, 1 = backup failed
# =====================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="/home/chuck/data/backups/kb"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
STAMP="$(date +%Y%m%d-%H%M)"

# OPS credential: the ADMIN key (full access). From the environment if
# present, else from .env (same pattern as backup-memory.sh).
QDRANT_ADMIN_API_KEY="${QDRANT_ADMIN_API_KEY:-}"
if [[ -z "$QDRANT_ADMIN_API_KEY" && -f "${REPO_ROOT}/.env" ]]; then
  QDRANT_ADMIN_API_KEY="$(grep -E '^QDRANT_ADMIN_API_KEY=' "${REPO_ROOT}/.env" | head -1 | cut -d= -f2- || true)"
fi
if [[ -z "$QDRANT_ADMIN_API_KEY" ]]; then
  echo "ERROR: QDRANT_ADMIN_API_KEY not found (env or ${REPO_ROOT}/.env)" >&2
  exit 1
fi
AUTH=(-H "api-key: ${QDRANT_ADMIN_API_KEY}")

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

echo "==> [1/2] Qdrant snapshots of all kb_* collections"
COLS="$(curl -s "${AUTH[@]}" "${QDRANT_URL}/collections" \
  | jq -r '.result.collections[].name | select(startswith("kb_"))')"
if [[ -z "$COLS" ]]; then
  echo "    no kb_* collections exist — nothing to snapshot."
else
  for COL in $COLS; do
    HTTP_CODE="$(curl -s -o /tmp/qdrant-kb-snap-resp.json -w '%{http_code}' \
      "${AUTH[@]}" -X POST "${QDRANT_URL}/collections/${COL}/snapshots")"
    if [[ "$HTTP_CODE" != "200" ]]; then
      echo "ERROR: snapshot request for '${COL}' failed (HTTP $HTTP_CODE):" >&2
      cat /tmp/qdrant-kb-snap-resp.json >&2
      exit 1
    fi
    SNAP_NAME="$(jq -r '.result.name // empty' /tmp/qdrant-kb-snap-resp.json)"
    if [[ -z "$SNAP_NAME" ]]; then
      SNAP_NAME="$(basename "$(jq -r '.result | select(type == "string")' /tmp/qdrant-kb-snap-resp.json)")"
    fi
    if [[ -z "$SNAP_NAME" ]]; then
      echo "ERROR: could not parse snapshot name for '${COL}':" >&2
      cat /tmp/qdrant-kb-snap-resp.json >&2
      exit 1
    fi
    SNAP_DEST="${BACKUP_DIR}/${COL}-${STAMP}.snapshot"
    if ! docker exec qdrant cat "/qdrant/snapshots/${COL}/${SNAP_NAME}" > "$SNAP_DEST"; then
      echo "ERROR: docker exec qdrant cat failed for ${COL}/${SNAP_NAME}" >&2
      rm -f "$SNAP_DEST"
      exit 1
    fi
    chmod 600 "$SNAP_DEST"
    if [[ ! -s "$SNAP_DEST" ]]; then
      echo "ERROR: extracted snapshot for '${COL}' is empty" >&2
      rm -f "$SNAP_DEST"
      exit 1
    fi
    echo "    ${COL}: $(stat -c%s "$SNAP_DEST") bytes"
  done
fi
rm -f /tmp/qdrant-kb-snap-resp.json

echo "==> [2/2] source files -> ${BACKUP_DIR}/kb-sources-${STAMP}.tar.gz"
# Tar exactly the source files the KB references (unique payload 'source'
# values across all kb_* collections) — same semantics as the kb_backup
# MCP tool. Container allowlist roots -> host roots:
#   /data/ai-kb/raw  -> /home/chuck/data/ai-kb/raw
#   /data/media      -> /home/chuck/data/media
#   /data/workspace  -> /home/chuck/data/workspace
TAR_DEST="${BACKUP_DIR}/kb-sources-${STAMP}.tar.gz"
SOURCES="$(for COL in $COLS; do
    curl -s "${AUTH[@]}" -X POST "${QDRANT_URL}/collections/${COL}/points/scroll" \
      -H 'Content-Type: application/json' \
      -d '{"limit": 10000, "with_payload": ["source"], "with_vectors": false}' \
      | jq -r '.result.points[].payload.source // empty'
  done | sort -u)"
if [[ -n "$SOURCES" ]]; then
  HOST_FILES=()
  while IFS= read -r SRC; do
    case "$SRC" in
      /data/ai-kb/raw/*)  HOST_FILES+=("/home/chuck/data/ai-kb/raw/${SRC#/data/ai-kb/raw/}") ;;
      /data/media/*)      HOST_FILES+=("/home/chuck/data/media/${SRC#/data/media/}") ;;
      /data/workspace/*)  HOST_FILES+=("/home/chuck/data/workspace/${SRC#/data/workspace/}") ;;
      *) echo "    WARNING: source '${SRC}' outside allowlist roots — skipped" ;;
    esac
  done <<< "$SOURCES"
  EXISTING=()
  for F in ${HOST_FILES[@]+"${HOST_FILES[@]}"}; do
    if [[ -f "$F" ]]; then
      EXISTING+=("$F")
    else
      echo "    WARNING: source file missing on host: $F"
    fi
  done
  if [[ ${#EXISTING[@]} -gt 0 ]]; then
    tar -czf "$TAR_DEST" "${EXISTING[@]}"
  else
    tar -czf "$TAR_DEST" -T /dev/null
  fi
  chmod 600 "$TAR_DEST"
  echo "    $(stat -c%s "$TAR_DEST") bytes (${#EXISTING[@]}/${#HOST_FILES[@]} source files present)"
else
  echo "    no sources referenced — writing empty tarball."
  tar -czf "$TAR_DEST" -T /dev/null
  chmod 600 "$TAR_DEST"
fi

echo "==> KB backup complete: ${BACKUP_DIR}/ (stamp ${STAMP})"