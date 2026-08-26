#!/usr/bin/env bash
# =====================================================================
# backup-memory.sh — Long-term memory backup (memory_todo.md, Phase 1)
# =====================================================================
# Per decision §0.3, the memory backup is three parts:
#   1. homelab/.env           -> /home/chuck/data/backups/env-<stamp>.env
#      (gitignored secrets; chmod 600)
#   2. Qdrant collection      -> /home/chuck/data/backups/mem0_memories-<stamp>.snapshot
#      (the actual memories — git cannot cover Qdrant data)
#   3. config/code            -> git (this script verifies the working
#      tree is clean so the git backup is complete)
#
# No cron in v1 — run manually: before any storage change and at every
# phase gate (~10s).
#
# Restore (see docs/memory/IMPLEMENTATION_STATE.md phase log):
#   docker run --rm -d --name qdrant-restore-test -p 16333:6333 \
#     -v <snapshot>:/snapshots/restore.snapshot:ro qdrant/qdrant:latest
#   curl -X POST http://localhost:16333/collections/mem0_memories/snapshots/restore \
#     -H 'Content-Type: application/json' -d '{"location":"/snapshots/restore.snapshot"}'
#   docker rm -f qdrant-restore-test
#
# Usage: scripts/backup-memory.sh
# Exit codes: 0 = ok, 1 = backup failed or git tree dirty (backup incomplete)
# =====================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="/home/chuck/data/backups"
QDRANT_DATA="/home/chuck/data/qdrant"
ENV_FILE="${REPO_ROOT}/.env"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
COLLECTION="mem0_memories"
STAMP="$(date +%Y%m%d-%H%M)"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

echo "==> [1/3] .env -> ${BACKUP_DIR}/env-${STAMP}.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found" >&2
  exit 1
fi
ENV_DEST="${BACKUP_DIR}/env-${STAMP}.env"
cp "$ENV_FILE" "$ENV_DEST"
chmod 600 "$ENV_DEST"
echo "    wrote $(stat -c%s "$ENV_DEST") bytes (mode 600)"

echo "==> [2/3] Qdrant snapshot of '${COLLECTION}'"
HTTP_CODE="$(curl -s -o /tmp/qdrant-snap-resp.json -w '%{http_code}' \
  -X POST "${QDRANT_URL}/collections/${COLLECTION}/snapshots")"
if [[ "$HTTP_CODE" == "404" ]]; then
  echo "    WARNING: collection '${COLLECTION}' does not exist yet — skipping snapshot."
  echo "    (Expected before Phase 1 step 4. Re-run after the collection exists.)"
  SNAP_DEST="skipped"
else
  if [[ "$HTTP_CODE" != "200" ]]; then
    echo "ERROR: Qdrant snapshot request failed (HTTP $HTTP_CODE):" >&2
    cat /tmp/qdrant-snap-resp.json >&2
    exit 1
  fi
  SNAP_REL="$(jq -r '.result // empty' /tmp/qdrant-snap-resp.json)"
  if [[ -z "$SNAP_REL" || ! -f "${QDRANT_DATA}/${SNAP_REL}" ]]; then
    echo "ERROR: snapshot response did not yield a readable file: ${SNAP_REL}" >&2
    exit 1
  fi
  SNAP_DEST="${BACKUP_DIR}/${COLLECTION}-${STAMP}.snapshot"
  cp "${QDRANT_DATA}/${SNAP_REL}" "$SNAP_DEST"
  chmod 600 "$SNAP_DEST"
  echo "    wrote $(stat -c%s "$SNAP_DEST") bytes (${SNAP_REL})"
fi
rm -f /tmp/qdrant-snap-resp.json

echo "==> [3/3] git working tree (config/code backup)"
cd "$REPO_ROOT"
DIRTY="$(git status --porcelain)"
if [[ -n "$DIRTY" ]]; then
  echo "ERROR: git working tree is dirty — the git part of the backup is incomplete." >&2
  echo "Uncommitted changes:" >&2
  echo "$DIRTY" >&2
  echo "Commit (or stash) and re-run." >&2
  exit 1
fi
echo "    clean (HEAD $(git rev-parse --short HEAD))"

echo "==> Backup complete: ${BACKUP_DIR}/"
echo "    env:  env-${STAMP}.env"
echo "    qdrant: ${SNAP_DEST}"