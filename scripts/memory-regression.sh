#!/usr/bin/env bash
# =====================================================================
# memory-regression.sh — Phase 9 repeatable e2e regression suite
# =====================================================================
# Codifies the memory end-to-end checks as a single re-runnable entry
# point (memory_todo.md Phase 9 item 3). It:
#
#   [0/3] preflight: git tree clean (the mounted code is what gets
#         tested), Qdrant reachable + authorized, host unit tests green.
#   [1/3] spins up a THROWAWAY container on ai-net (skill-runner:local
#         image, live working tree mounted read-only, no published
#         ports) and runs the live integration suite against real
#         Qdrant + LiteLLM. Covers: identity isolation, household
#         scope, secret filtering, prompt-injection boundary, outage
#         degradation, embedding-dim consistency, Qdrant auth/ACL.
#   [2/3] verifies Qdrant is left CLEAN afterwards (mem0_memories=0,
#         family_kb absent — dropped by the KB rebuild 2026-08-29) and
#         removes the throwaway container.
#
# Safe to run repeatedly: uses non-production users (memory_test,
# memory_test_other) and cleans them up. Does NOT touch the running
# skill-runner container.
#
# Usage: scripts/memory-regression.sh
# Exit: 0 = all pass, 1 = any failure
# =====================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
IMAGE="skill-runner:local"
CONTAINER="memory-regression"
NETWORK="ai-net"
QDRANT_HOST_URL="http://localhost:6333"
# KB rebuild (2026-08-29): the old 384-dim family_kb collection was DROPPED
# (snapshot saved to /home/chuck/data/backups/family_kb-<stamp>.snapshot). The
# clean-state expectation is now that family_kb is ABSENT (404), not 18 points.
EXPECTED_FAMILY_KB_ABSENT=1

log() { echo "==> $*"; }

fail() { echo "ERROR: $*" >&2; exit 1; }

# --- [0/3] preflight -------------------------------------------------------
log "[0/3] preflight"
[[ -f "$ENV_FILE" ]] || fail "$ENV_FILE not found"
set -a; source "$ENV_FILE"; set +a
[[ -n "${QDRANT_ADMIN_API_KEY:-}" ]] || fail "QDRANT_ADMIN_API_KEY missing in .env"

# git tree must be clean (the suite tests the mounted working tree).
DIRTY="$(git -C "$REPO_ROOT" status --porcelain | grep -v '__pycache__' || true)"
[[ -z "$DIRTY" ]] || fail "git working tree is dirty — commit first:
$DIRTY"

# Qdrant reachable + authorized (admin key).
CODE="$(curl -s -o /dev/null -w '%{http_code}' \
  -H "api-key: $QDRANT_ADMIN_API_KEY" "$QDRANT_HOST_URL/collections")"
[[ "$CODE" == "200" ]] || fail "Qdrant not reachable/authorized (HTTP $CODE)"

# Host unit tests (fast, no live services).
log "    host unit tests..."
python3 -m pytest "$REPO_ROOT/skills/runner/memory/tests/test_unit.py" \
  "$REPO_ROOT/skills/runner/memory/tests/test_identity.py" -q >/dev/null \
  || fail "host unit tests failed"
echo "    unit tests green"

# --- [1/3] live integration suite in a throwaway container -----------------
log "[1/3] live integration suite (throwaway container on $NETWORK)"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" --network "$NETWORK" \
  -v "${REPO_ROOT}/skills/runner:/app:ro" \
  -e MEMORY_ENABLED=true \
  -e MEMORY_RETRIEVAL_ENABLED=true \
  -e MEMORY_WRITEBACK_ENABLED=true \
  -e MEMORY_LITELLM_BASE_URL="${MEMORY_LITELLM_BASE_URL:-http://litellm-proxy:4000/v1}" \
  -e MEMORY_LITELLM_KEY="$MEMORY_LITELLM_KEY" \
  -e MEMORY_EXTRACTION_MODEL="${MEMORY_EXTRACTION_MODEL:-matrix-coder}" \
  -e MEMORY_EMBED_MODEL="${MEMORY_EMBED_MODEL:-homelab-embedding-v1}" \
  -e MEMORY_QDRANT_URL="${MEMORY_QDRANT_URL:-http://qdrant:6333}" \
  -e MEMORY_QDRANT_API_KEY="${MEMORY_QDRANT_JWT:-}" \
  -e MEMORY_COLLECTION="${MEMORY_COLLECTION:-mem0_memories}" \
  -e MEMORY_EMBED_DIM="${MEMORY_EMBED_DIM:-768}" \
  -e MEMORY_TOP_K="${MEMORY_TOP_K:-6}" \
  -e MEMORY_TIMEOUT_MS="${MEMORY_TIMEOUT_MS:-1500}" \
  -e MEMORY_ADMIN_TIMEOUT_MS="${MEMORY_ADMIN_TIMEOUT_MS:-10000}" \
  -e MEMORY_HOUSEHOLD_ENABLED="${MEMORY_HOUSEHOLD_ENABLED:-true}" \
  -e SKILL_RUNNER_API_KEY="${SKILL_RUNNER_API_KEY:-}" \
  "$IMAGE" sleep infinity >/dev/null || fail "could not start $CONTAINER"

RC=0
docker exec "$CONTAINER" python /app/memory/tests/test_integration.py
RC=$?

# --- [2/3] Qdrant left clean + cleanup --------------------------------------
log "[2/3] verifying Qdrant left clean"
CNT_MEM0="$(curl -s -H "api-key: $QDRANT_ADMIN_API_KEY" \
  "$QDRANT_HOST_URL/collections/mem0_memories" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["points_count"])' 2>/dev/null || echo '?')"
# family_kb should now be ABSENT (dropped by the KB rebuild). 404 = expected.
FKB_HTTP="$(curl -s -o /dev/null -w '%{http_code}' -H "api-key: $QDRANT_ADMIN_API_KEY" \
  "$QDRANT_HOST_URL/collections/family_kb")"
echo "    mem0_memories=$CNT_MEM0 (expect 0)   family_kb HTTP=$FKB_HTTP (expect 404 = absent)"
CLEAN=0
[[ "$CNT_MEM0" == "0" ]] || CLEAN=1
[[ "$FKB_HTTP" == "404" ]] || CLEAN=1

log "[3/3] cleanup + result"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

if [[ $RC -eq 0 && $CLEAN -eq 0 ]]; then
  echo "RESULT: PASS (suite green + Qdrant clean)"
  exit 0
else
  echo "RESULT: FAIL (suite rc=$RC, qdrant_clean=$CLEAN)"
  exit 1
fi