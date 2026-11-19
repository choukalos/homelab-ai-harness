#!/usr/bin/env bash
# =====================================================================
# apply-tier1-litellm.sh — atomic apply of the tier1 litellm model-config
# pass (proposals/2026-11-19-tier1-litellm-model-config-pass.md).
#
# WHY A SCRIPT (2026-11-19 incident): a manual multi-command swap failed
# with a postgres/schema error and the failed container's logs were lost
# when the container was recreated. This script:
#   1. preflights (known-good live config, staged files valid, stack healthy)
#   2. swaps BOTH files (config + compose) before touching the container
#   3. applies with `up -d` (recreate — needed for the HF_TOKEN env removal)
#   4. waits for healthy, then runs FUNCTIONAL verification (model set,
#      capability tags, matrix-coder-fast thinking-off, embeddings)
#   5. on ANY failure: captures the failed container's logs to
#      tmp/litellm-apply-FAILED-<ts>.log, auto-rolls back both files,
#      re-applies, and verifies the rollback.
#
# Usage:  bash scripts/apply-tier1-litellm.sh
# Rollback (manual, if you ever need it):
#   mv litellm/config.yml.pre-tier1 litellm/config.yml
#   git checkout compose/compose.ai-core.yml
#   docker compose -f compose/compose.ai-core.yml --env-file .env up -d litellm
# =====================================================================
set -euo pipefail
cd /home/chuck/homelab

COMPOSE="docker compose -f compose/compose.ai-core.yml --env-file .env"
STAGED_CONFIG=litellm/config.yml.tier1
STAGED_COMPOSE=compose/compose.ai-core.yml.tier1
LIVE_CONFIG=litellm/config.yml
BACKUP_CONFIG=litellm/config.yml.pre-tier1
LIVE_COMPOSE=compose/compose.ai-core.yml
TS=$(date +%Y%m%d-%H%M%S)
FAILLOG="tmp/litellm-apply-FAILED-${TS}.log"
mkdir -p tmp

say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

rollback() {
  local reason="$1"
  say "ROLLBACK — ${reason}"
  # Capture the failed container's logs BEFORE recreating (they are lost on recreate)
  if docker ps -a --format '{{.Names}}' | grep -qx litellm-proxy; then
    docker logs litellm-proxy > "$FAILLOG" 2>&1
    echo "  failed-container logs captured -> $FAILLOG"
  fi
  # Restore both files, then re-apply
  # (docker auto-creates a DIRECTORY if the bind source is missing at recreate
  # time — clear that BEFORE the mv, or the backup would land inside it)
  if [ -d "$LIVE_CONFIG" ]; then rmdir "$LIVE_CONFIG"; echo "  removed docker-created $LIVE_CONFIG dir"; fi
  if [ -f "$BACKUP_CONFIG" ]; then
    mv -f "$BACKUP_CONFIG" "$LIVE_CONFIG"
  fi
  if ! git diff --quiet -- "$LIVE_COMPOSE" 2>/dev/null; then
    git checkout -- "$LIVE_COMPOSE"
    echo "  compose restored from git"
  fi
  $COMPOSE up -d litellm
  wait_healthy "rollback" || { echo "FATAL: rollback container not healthy — manual intervention needed" >&2; exit 2; }
  echo "  rollback applied. Inspect: $FAILLOG"
}

wait_healthy() {
  local what="$1" i
  for i in $(seq 1 24); do
    sleep 5
    local st
    st=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' litellm-proxy 2>/dev/null || echo missing)
    if [ "$st" = "healthy" ]; then
      echo "  litellm-proxy healthy after ~$((i*5))s (${what})"
      return 0
    fi
    if [ "$st" = "missing" ] || [ "$st" = "exited" ] || [ "$st" = "dead" ]; then
      echo "  litellm-proxy ${st} — aborting wait"
      return 1
    fi
  done
  echo "  litellm-proxy not healthy after 120s (status: $st)"
  return 1
}

verify() {
  say "FUNCTIONAL VERIFICATION (live proxy)"
  set -a; . ./.env; set +a
  docker exec -i -e KEY="$LITELLM_MASTER_KEY" litellm-proxy python3 - <<'PYEOF'
import json, os, sys, urllib.request
KEY = os.environ['KEY']
def get(path):
    req = urllib.request.Request('http://localhost:4000'+path, headers={'Authorization': f'Bearer {KEY}'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())
def post(path, payload):
    req = urllib.request.Request('http://localhost:4000'+path, data=json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())
fails = []
models = [m['id'] for m in get('/v1/models')['data']]
expected = {'studio-gemma4-26b','matrix-coder','matrix-coder-fast','embeddings','homelab-embedding-v1'}
if set(models) != expected:
    fails.append(f'model set {sorted(models)} != expected {sorted(expected)}')
info = {m['model_name']: m.get('model_info',{}) for m in get('/model/info')['data']}
mc = info.get('matrix-coder', {})
for k in ['supports_function_calling','supports_parallel_function_calling','supports_vision','supports_reasoning','supports_response_schema','supports_prompt_caching']:
    if mc.get(k) is not True:
        fails.append(f'matrix-coder {k} != True')
if info.get('embeddings',{}).get('mode') != 'embedding':
    fails.append('embeddings mode != embedding')
if 'matrix-coder-fast' not in info:
    fails.append('matrix-coder-fast missing from /model/info')
try:
    r = post('/v1/chat/completions', {'model':'matrix-coder','messages':[{'role':'user','content':'Reply with exactly: OK'}],'max_tokens':50})
    print(f"  matrix-coder completion: {r['choices'][0]['message'].get('content')!r}")
except Exception as e:
    fails.append(f'matrix-coder completion failed: {e}')
try:
    r = post('/v1/chat/completions', {'model':'matrix-coder-fast','messages':[{'role':'user','content':'What is 17 * 23? Think carefully.'}],'max_tokens':1024})
    rt = r.get('usage',{}).get('completion_tokens_details',{}).get('reasoning_tokens', 0)
    print(f"  matrix-coder-fast completion OK, reasoning_tokens={rt}")
    if rt != 0:
        fails.append(f'matrix-coder-fast reasoning_tokens={rt} (expected 0)')
except Exception as e:
    fails.append(f'matrix-coder-fast completion failed: {e}')
try:
    r = post('/v1/embeddings', {'model':'embeddings','input':'hello'})
    print(f"  embeddings OK (dim {len(r['data'][0]['embedding'])})")
except Exception as e:
    fails.append(f'embeddings failed: {e}')
if fails:
    print('  VERIFICATION FAILURES:')
    for f in fails:
        print(f'   - {f}')
    sys.exit(1)
print('  ALL CHECKS PASSED')
PYEOF
}

# ---------------------------------------------------------------- preflight
say "PREFLIGHT"
[ -f "$LIVE_CONFIG" ] || { echo "FATAL: $LIVE_CONFIG is not a regular file (docker dir footgun?) — fix manually" >&2; exit 2; }
cmp -s "$LIVE_CONFIG" "$BACKUP_CONFIG" || {
  echo "FATAL: live config.yml differs from $BACKUP_CONFIG — the stack is not in the" >&2
  echo "       known-good state. Inspect before running this script." >&2
  exit 2
}
[ -f "$STAGED_CONFIG" ] || { echo "FATAL: staged config $STAGED_CONFIG missing" >&2; exit 2; }
[ -f "$STAGED_COMPOSE" ] || { echo "FATAL: staged compose $STAGED_COMPOSE missing" >&2; exit 2; }
python3 - "$STAGED_CONFIG" <<'PYEOF'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
models = [m['model_name'] for m in d['model_list']]
assert 'matrix-coder-fast' in models and 'hf-sd3' not in models, models
assert 'set_verbose' not in d.get('general_settings', {}), 'set_verbose still present'
print(f"  staged config OK: {models}")
PYEOF
for c in litellm-proxy litellm-db; do
  st=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$c" 2>/dev/null || echo missing)
  [ "$st" = "healthy" ] || { echo "FATAL: $c is $st (want healthy)" >&2; exit 2; }
done
echo "  live config == known-good backup; staged files valid; stack healthy"

# ---------------------------------------------------------------- swap
say "SWAP (both files, before touching the container)"
mv -f "$STAGED_CONFIG" "$LIVE_CONFIG"
mv -f "$STAGED_COMPOSE" "$LIVE_COMPOSE"
[ -f "$LIVE_CONFIG" ] || { echo "FATAL: config.yml vanished during swap" >&2; exit 2; }
echo "  config + compose swapped"

# ---------------------------------------------------------------- apply
say "APPLY (up -d litellm — recreates container with new config + env)"
if ! $COMPOSE up -d litellm; then
  rollback "compose up -d failed"
  exit 1
fi
if ! wait_healthy "apply"; then
  rollback "container not healthy after 120s"
  exit 1
fi

# ---------------------------------------------------------------- verify
if ! verify; then
  rollback "functional verification failed"
  exit 1
fi

# ---------------------------------------------------------------- done
say "SUCCESS — tier1 litellm model-config pass is live"
echo "  next steps:"
echo "    1. bash cli/proposals.sh accept tier1-litellm-model-config-pass"
echo "    2. bash cli/proposals.sh mark-applied tier1-litellm-model-config-pass"
echo "    3. git add litellm/config.yml compose/compose.ai-core.yml && git commit"
echo "    4. optional cleanup: rm litellm/config.yml.bak litellm/config.yml.pre-tier1"
