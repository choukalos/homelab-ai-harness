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
#   docker run -d --name qdrant-restore-test -p 16333:6333 \
#     -v /home/chuck/data/backups/mem0_memories-<stamp>.snapshot:/qdrant/snapshots/restore.snapshot:ro \
#     qdrant/qdrant:v1.18.1   # match production (pinned, Phase 9)
#   curl -s -X PUT http://localhost:16333/collections/mem0_memories/snapshots/recover \
#     -H 'Content-Type: application/json' \
#     -d '{"location":"file:///qdrant/snapshots/restore.snapshot","priority":"snapshot"}'
#   docker rm -f qdrant-restore-test
#   (Qdrant >= 1.18: the endpoint is PUT .../snapshots/recover with a file:
#   URI, NOT POST .../snapshots/restore. priority MUST be "snapshot" on an
#   empty node — the default "replica" priority restores an EMPTY collection.)
#
# NOTE: Qdrant writes snapshots to /qdrant/snapshots/ INSIDE the container
# (workdir /qdrant), NOT on the mounted volume (/qdrant/storage) — they are
# ephemeral. This script extracts the fresh snapshot via read-only
# `docker exec qdrant cat`.
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

# Phase 9 least-privilege: Qdrant now requires an API key. The backup tool is
# an OPS credential holder, so it uses the ADMIN key (full access). Read it
# from the environment if present, else from .env (the file is backed up in
# step 1, so the key is included in the env backup — expected for ops tools).
QDRANT_ADMIN_API_KEY="${QDRANT_ADMIN_API_KEY:-}"
if [[ -z "$QDRANT_ADMIN_API_KEY" && -f "$ENV_FILE" ]]; then
  QDRANT_ADMIN_API_KEY="$(grep -E '^QDRANT_ADMIN_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
fi
# api-key header (empty when unset = pre-hardening / unauthenticated node).
QDRANT_AUTH_HEADER=()
if [[ -n "$QDRANT_ADMIN_API_KEY" ]]; then
  QDRANT_AUTH_HEADER=(-H "api-key: ${QDRANT_ADMIN_API_KEY}")
fi

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
  "${QDRANT_AUTH_HEADER[@]}" \
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
  # Qdrant >= 1.18: {"result": {"name": "...", ...}}; older versions:
  # {"result": "<relative path>"}. Handle both.
  SNAP_NAME="$(jq -r '.result.name // empty' /tmp/qdrant-snap-resp.json)"
  if [[ -z "$SNAP_NAME" ]]; then
    SNAP_NAME="$(basename "$(jq -r '.result | select(type == "string")' /tmp/qdrant-snap-resp.json)")"
  fi
  if [[ -z "$SNAP_NAME" ]]; then
    echo "ERROR: could not parse snapshot name from response" >&2
    cat /tmp/qdrant-snap-resp.json >&2
    exit 1
  fi
  # Snapshot lives inside the container at /qdrant/snapshots/<coll>/<name>
  # (NOT on the mounted volume) — extract via read-only exec.
  SNAP_DEST="${BACKUP_DIR}/${COLLECTION}-${STAMP}.snapshot"
  if ! docker exec qdrant cat "/qdrant/snapshots/${COLLECTION}/${SNAP_NAME}" > "$SNAP_DEST"; then
    echo "ERROR: docker exec qdrant cat failed for ${SNAP_NAME}" >&2
    rm -f "$SNAP_DEST"
    exit 1
  fi
  chmod 600 "$SNAP_DEST"
  if [[ ! -s "$SNAP_DEST" ]]; then
    echo "ERROR: extracted snapshot is empty" >&2
    rm -f "$SNAP_DEST"
    exit 1
  fi
  echo "    wrote $(stat -c%s "$SNAP_DEST") bytes (${SNAP_NAME})"
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