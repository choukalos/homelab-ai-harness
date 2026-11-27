# P12-B + P12-C deploy runbook — `mcp_filebridge` (thor)

**Date:** 2026-11-26 · **Written by:** pi-long-task run `10f37f65` (TODO 7)
**Status:** **EXECUTED 2026-11-27 02:05–02:15 UTC (pi, thor)** — all steps green:
bridge recreate (env gate 0, no host ports, healthy, boot lint OK in-container),
litellm restart (15th server registered; note: the access-group API 405'd
intermittently during the proxy's MCP-client init window post-restart —
transient, cleared within minutes; curl was reliable throughout), access group
14 → 15 servers (fetch-union-PUT), public E2E battery all green (4.1 1b token:
mint → public 200 + sha256 identical + DYNAMIC + Range 206 + bad-token 404 +
both hosts; 4.2 P12-A regression: dl sha256 match + Range 206 + bad-token 404
+ upload 401/401/200 + /media/files policy both hosts + pipeline admin 404s +
DYNAMIC; 4.3 MCP via litellm: 5 tools visible to chuck + dylan, `file_work_areas`
returned the registry, D13 negatives rejected — dest=siri_outputs + siri-file
client-token; 4.4 publish wrapper hot: real skill run published + served 200
+ idempotent republish no-op; 4.5 kill switch 502s with Matrix/skill-runner
200 + clean recovery + `ss` diff no new host port). One runbook correction:
the step-1 standalone lint check (`docker run --rm --entrypoint python … lint`)
cannot pass without the work-area mounts — verify with `docker exec
mcp_filebridge python app.py lint` instead (the live container's boot lint is
the real gate). One battery correction: 4.1's mint source must be under a
registered work area (used `pipeline_fetch`); the runbook's example path
(`/home/chuck/data/media/generated/…`) is not a work area. **Base:** `main` @
`b8d615f` (P12-B/C committed 2026-11-26; this runbook was written against the
pre-commit tree — `git status` is clean at deploy time). **Design:**
`docs/filebridge_p12bc.md` · **Decisions:** 1b / 2a / 3a /
4-published (user-approved 2026-11-26).

## What this deploys

| Piece | Where | Effect |
|---|---|---|
| New bridge image | `mcp/servers/filebridge/` (registry + boot lint, 1b signed tokens, FastMCP face + 5 tools, publish engine, `POST /publish`) | recreated live container `mcp_filebridge` (same name, same image tag `ai-mcp-mcp_filebridge`) |
| 6 compose mounts | `compose/compose.mcp.yml` (work areas rw/ro + blog publish root rw + workspace ro) | applied by the recreate |
| litellm `mcp_servers` entry | `litellm/config.yml` (15th server, `http://mcp_filebridge:8000/mcp`) | applied by the litellm restart (step 2) |
| `family-mcp-full` access group | LiteLLM API `PUT /v1/access_group/{id}` (step 3) | chuck/dylan keys see the 5 file tools |
| publish-file skill | `skills/publish_file/skill.py` thin wrapper (ro bind-mounted into skill-runner) | **hot — no skill-runner restart** (the runner re-imports the skill module per invocation, `skills/runner/main.py:1048-1056`) |

**NOT touched by this deploy (by construction):**

- **Caddy / Caddyfile** — zero changes. The 1b token URL
  (`/media/files/dl/{token}`) rides the existing `/media/files/*` →
  `mcp_filebridge:8000` routes (both hosts). No Caddy step, no Caddy
  rollback (see Rollback D).
- **Matrix** (192.168.4.55) — zero changes (1b is thor-only, §1 of the
  design doc).
- **`mcp_media`** — zero changes (its tools are NOT removed; cross-area
  cases route via the bridge).
- **skill-runner** — no restart needed (wrapper is hot via the ro bind
  mount; verify in step 5).

**Standing rule:** the litellm restart (step 2) is **Chuck's step** — it
severs active proxy sessions (in-flight chat/tool sessions through
`llm.choukalos.com` drop and must reconnect). Run it at a time with no
active proxy sessions.

## Preflight (all verified 2026-11-26 in this run — read-only)

```bash
cd /home/chuck/homelab
git status --short          # 12 modified + 10 new files (P12-B/C set)
# registry lint green (standalone):
PYTHONPATH=/home/chuck/homelab/tmp/pydeps python3 mcp/servers/filebridge/app.py lint
# → registry lint: OK (5 work areas, 2 publish targets)  (exit 0)
# unit suites green:
PYTHONPATH=/home/chuck/homelab/tmp/pydeps python3 -m pytest mcp/servers/filebridge/tests/ -q
# → 107 passed (existing 22 P12-A + 59 P12-B + 26 P12-C)
PYTHONPATH=/home/chuck/homelab/tmp/pydeps python3 skills/publish_file/test_skill.py
# → PASS: 32  FAIL: 0 (wrapper contract)
# no secrets in the final diff:
{ git diff; git diff --cached; } | grep -E 'sk-[A-Za-z0-9]{8,}'   # → no matches
git status --porcelain | awk '{print $2}' | xargs grep -lE 'sk-[A-Za-z0-9]{8,}' 2>/dev/null   # → nothing
# Caddyfile untouched:
git diff --name-only | grep -c caddy   # → 0
# side test container E2E (TODO 6): 43/43 green, container torn down,
# test image mcp_filebridge_p12bc_test kept (unused by this runbook)
```

## Step 0 — Baselines + rollback anchors (BEFORE touching anything)

```bash
cd /home/chuck/homelab
# Phase 0 convention: back up .env (public-surface change)
cp .env /home/chuck/data/backups/env-$(date +%F).bak && chmod 600 /home/chuck/data/backups/env-$(date +%F).bak
# host-port baseline (rollback check R9):
ss -tlnp | sort > /tmp/ss-baseline-p12bc.txt
# fast rollback anchor: tag the running (pre-P12-B/C) image
docker tag ai-mcp-mcp_filebridge:latest mcp_filebridge_pre_p12bc_$(date +%F)
# access-group snapshot (rollback anchor C):
set -a && . ./.env && set +a
GROUP=07c1acf8-ffb6-4dbc-918d-9c7199f76fa1   # family-mcp-full (Phase 2, created 2026-11-15)
curl -s -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  "http://192.168.4.54:4000/v1/access_group/${GROUP}" > /tmp/access_group_family_mcp_full_before.json
python3 -m json.tool /tmp/access_group_family_mcp_full_before.json | grep -c '"'   # sanity: JSON saved
```

Expected: the snapshot's `access_mcp_server_ids` does NOT contain
`mcp_filebridge` (12–13 servers, depending on prior kanban-era updates).

## Step 1 — Build + recreate `mcp_filebridge` (live)

```bash
cd /home/chuck/homelab
docker compose -f compose/compose.mcp.yml --env-file .env up -d --build mcp_filebridge
```

Verify (all four must pass before moving on):

```bash
docker inspect mcp_filebridge --format '{{.Config.User}}'          # → 1000:1000
# env gate (hard rule — must be 0):
docker inspect mcp_filebridge --format '{{json .Config.Env}}' | grep -ciE 'litellm|memory|master|api_key'   # → 0
# no published host ports (hard rule):
docker port mcp_filebridge                                          # → (empty)
# healthy + pipeline reachable:
docker run --rm --network ai-net curlimages/curl -s http://mcp_filebridge:8000/health
# → {"status":"ok", ... "pipeline_reachable":true ...}
# registry boot-lint inside the live container (fail-fast proof):
docker run --rm --network ai-net --entrypoint python ai-mcp-mcp_filebridge app.py lint
# → registry lint: OK (5 work areas, 2 publish targets)
# MCP face answers on ai-net (Host header required — DNS-rebinding protection):
docker run --rm --network ai-net --entrypoint python ai-mcp-mcp_filebridge -c '
import json, http.client
c = http.client.HTTPConnection("mcp_filebridge", 8000, timeout=15)
c.putrequest("POST", "/mcp", skip_host=True)
c.putheader("Host", "mcp_filebridge:8000")
body = json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"deploy","version":"1"}}}).encode()
c.putheader("Content-Type","application/json"); c.putheader("Content-Length",str(len(body)))
c.putheader("Accept","application/json, text/event-stream")
c.endheaders(message_body=body)
r = c.getresponse(); raw = r.read().decode()
print("status:", r.status, "| serverInfo:", "mcp_filebridge" in raw)'
# → status: 200 | serverInfo: True
```

Note: the Dockerfile `HEALTHCHECK` hardcodes port 8000 — correct for the
live container (which runs on 8000); side test containers on other ports
need a `--health-cmd` override (TODO 6 finding; no action here).

## Step 2 — litellm-proxy restart (USER TIMING — severs active proxy sessions)

> ⚠️ **Run at a time with no active proxy sessions** (in-flight
> `llm.choukalos.com` chat/tool sessions are severed by the restart —
> clients must reconnect). The bind-mounted config
> (`litellm/config.yml` → `/app/config.yaml:ro`) is re-read at process
> start; a plain `restart` suffices (the compose definition is
> unchanged).

```bash
cd /home/chuck/homelab && docker compose -f compose/compose.ai-core.yml --env-file .env restart litellm
```

Verify the 15th server registered:

```bash
docker logs litellm-proxy --since 2m 2>&1 | grep -i "mcp_filebridge" | head   # registration lines
curl -s -o /dev/null -w "%{http_code}\n" http://192.168.4.54:4000/health/liveliness   # → 200
```

## Step 3 — Access-group API update (exact command — NOT executed in this run)

Mechanism (verified against installed litellm **v1.104.0** source,
`proxy/management_endpoints/access_group_endpoints.py`):
`PUT /v1/access_group/{access_group_id}` with
`{"access_mcp_server_ids": [...]}` — the PUT **replaces the whole server
list**, so the current list must be fetched first and the union sent
(idempotent). Proxy-admin auth (master key). The key cache is patched in
place after the write — **no litellm restart needed** for the grant
itself. (Alias path `PUT /v1/unified_access_group/{id}` is equivalent.)

```bash
cd /home/chuck/homelab && set -a && . ./.env && set +a
GROUP=07c1acf8-ffb6-4dbc-918d-9c7199f76fa1   # family-mcp-full
python3 - <<'PY'
import json, os, urllib.request
key, proxy, group = os.environ["LITELLM_MASTER_KEY"], "http://192.168.4.54:4000", "07c1acf8-ffb6-4dbc-918d-9c7199f76fa1"
def req(method, body=None):
    r = urllib.request.Request(proxy + "/v1/access_group/" + group,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + key,
                 **({"Content-Type": "application/json"} if body is not None else {})})
    with urllib.request.urlopen(r, timeout=15) as resp:
        return json.load(resp)
d = req("GET")
servers = list(d["access_mcp_server_ids"])
if "mcp_filebridge" not in servers:
    servers.append("mcp_filebridge")
    d2 = req("PUT", {"access_mcp_server_ids": servers})
    print("updated: group now has", len(d2["access_mcp_server_ids"]), "servers")
else:
    print("already present:", len(servers), "servers (no-op)")
PY
```

Verify (chuck + dylan keys see the 5 file tools; a key NOT in the group
sees none — default-deny holds):

```bash
for K in LITELLM_KEY_CHUCK LITELLM_KEY_DYLAN; do
  echo "== $K =="
  curl -s -H "Authorization: Bearer ${!K}" https://llm.choukalos.com/v1/mcp/tools \
    | grep -oE '"(mcp_filebridge-)?file_(pull|push|publish|work_areas|targets)"' | sort -u
  # → expect the 5 tools (litellm surfaces MCP tools as mcp_<server>-<tool>,
  #   Phase 2 convention; the bridge face itself exposes them bare)
done
```

## Step 4 — Public E2E battery (full path CF → tunnel → Caddy → bridge)

Run after steps 1–3. All public checks use the two public hosts
(`siri.choukalos.com` + `choukalos.com`). Artifacts use the
`p12bc_deploy_` prefix (clean up after; Matrix-side uploads ride the
14-day auto-retention).

### 4.1 1b token route (new — decision 1b)

Mint is ONLY via the MCP face (`file_push destination="client"`, D10
holds — no public mint endpoint). Mint from ai-net against the live
bridge (Host header required):

```bash
cd /home/chuck/homelab && set -a && . ./.env && set +a
SRC=/home/chuck/data/media/generated/p12bc_deploy_$(date +%s).txt
echo "p12bc-deploy-battery-$(date +%s)" > "$SRC"
SRC_SHA=$(sha256sum "$SRC" | cut -d' ' -f1); echo "SRC_SHA=$SRC_SHA"
# mint (ttl_hours=1 — the minimum; real expiry is unit-tested with a fake clock)
docker run --rm --network ai-net --entrypoint python ai-mcp-mcp_filebridge > /tmp/p12bc_mint.out <<MINT
import json, http.client
def post(payload):
    c = http.client.HTTPConnection("mcp_filebridge", 8000, timeout=60)
    c.putrequest("POST", "/mcp", skip_host=True)
    c.putheader("Host", "mcp_filebridge:8000")
    body = json.dumps(payload).encode()
    c.putheader("Content-Type", "application/json"); c.putheader("Content-Length", str(len(body)))
    c.putheader("Accept", "application/json, text/event-stream")
    c.endheaders(message_body=body)
    r = c.getresponse(); raw = r.read().decode(); ct = r.getheader("Content-Type", "")
    if "text/event-stream" in ct:
        for line in raw.splitlines():
            if line.startswith("data:"):
                try: return json.loads(line[5:].strip())
                except Exception: pass
    return json.loads(raw)
post({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"battery","version":"1"}}})
res = post({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"file_push","arguments":{"file":"$SRC","destination":"client","ttl_hours":1}}})
out = json.loads(res["result"]["content"][0]["text"])
print(out["url"], flush=True)
print("EXPIRES_AT=" + out["expires_at"], flush=True)
MINT
TOKEN_URL=$(head -1 /tmp/p12bc_mint.out)
echo "TOKEN_URL=$TOKEN_URL"; grep EXPIRES_AT /tmp/p12bc_mint.out
```

Then, publicly (via Caddy):

```bash
# T1 fetch 200 + sha256 identical to the source file + cf-cache-status DYNAMIC:
curl -s -D /tmp/t1.hdrs -o /tmp/t1.bin "$TOKEN_URL"
grep -i '^HTTP' /tmp/t1.hdrs                      # → 200
grep -i cf-cache-status /tmp/t1.hdrs               # → DYNAMIC
sha256sum /tmp/t1.bin                              # → == $SRC_SHA
# T2 Range 206:
curl -s -D - -o /dev/null -H "Range: bytes=0-4" "$TOKEN_URL" | grep -iE '^HTTP|content-range'   # → 206 + bytes 0-4/...
# T3 bad token → 404 (never 403):
curl -s -o /dev/null -w "%{http_code}\n" "https://siri.choukalos.com/media/files/dl/deadbeefdeadbeefdeadbeefdeadbeef"   # → 404
# T4 TTL bounds: EXPIRES_AT ≈ mint + 1 h (min clamp); TTL 0 / 169 h rejected by the tool (unit-tested)
# T5 second host, same token URL:
curl -s -o /dev/null -w "%{http_code}\n" "https://choukalos.com/media/files/dl/$(basename "$TOKEN_URL")"   # → 200
rm -f "$SRC" /tmp/t1.hdrs /tmp/t1.bin
```

### 4.2 P12-A regression battery (unchanged routes must still behave)

```bash
# R1 dl relay sha256 — fresh Matrix token (LAN), public fetch == direct Matrix fetch:
# (pick the first output of a recent done job via the Matrix LAN job list)
JOBREF=$(curl -s "http://192.168.4.55:8189/jobs?limit=20" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for j in d['jobs']:
    if j.get('status') == 'done' and j.get('outputs'):
        print(j['outputs'][0]); break")
echo "JOBREF=$JOBREF"   # → <job_id>/<file>
TOK=$(curl -s -X POST http://192.168.4.55:8189/dl_token -H "Content-Type: application/json" \
  -d "{\"path\":\"/home/chuck/data/comfyui/run/media_jobs/$JOBREF\",\"ttl_hours\":1}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
curl -s "http://192.168.4.55:8189/dl/$TOK" | sha256sum
curl -s "https://siri.choukalos.com/media/pipeline/dl/$TOK" | sha256sum    # → identical
# R2 Range 206:
curl -s -D - -o /dev/null -H "Range: bytes=0-99" "https://siri.choukalos.com/media/pipeline/dl/$TOK" | grep -iE '^HTTP|content-range'
# R3 bad token 404:
curl -s -o /dev/null -w "%{http_code}\n" "https://siri.choukalos.com/media/pipeline/dl/deadbeef"   # → 404
# R4 upload 401 / 401 / 200 (Caddy key gate) + round-trip:
echo p12bc-upload-test > /tmp/p12bc_up.txt
curl -s -o /dev/null -w "%{http_code}\n" -X POST "https://siri.choukalos.com/media/pipeline/upload" -F "file=@/tmp/p12bc_up.txt"   # → 401 (no key)
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "X-Api-Key: wrong-key" "https://siri.choukalos.com/media/pipeline/upload" -F "file=@/tmp/p12bc_up.txt"   # → 401
UP=$(curl -s -X POST -H "X-Api-Key: ${LITELLM_KEY_CHUCK}" "https://siri.choukalos.com/media/pipeline/upload" -F "file=@/tmp/p12bc_up.txt")
echo "$UP"   # → 200 JSON {"path": "media_jobs/uploads/..."}
# round-trip: re-mint a dl_token for the uploaded path, fetch publicly, compare content
# R5 /media/files policy on BOTH hosts:
for H in siri.choukalos.com choukalos.com; do
  curl -s -o /dev/null -w "$H allowlisted: %{http_code}\n" "https://$H/media/files/generated/<real-file>"        # → 200
  curl -s -o /dev/null -w "$H siri_outputs: %{http_code}\n" "https://$H/media/files/siri_outputs/nope.txt"         # → 404
  curl -s -o /dev/null -w "$H non-allowlisted: %{http_code}\n" "https://$H/media/files/research_reports/nope.txt"   # → 404
  curl -s -o /dev/null -w "$H traversal: %{http_code}\n" "https://$H/media/files/../etc/passwd"                     # → 404
  curl -s -o /dev/null -w "$H traversal-pct: %{http_code}\n" "https://$H/media/files/generated/..%2F..%2Fetc%2Fpasswd" # → 404
  curl -s -o /dev/null -w "$H directory: %{http_code}\n" "https://$H/media/files/generated/"                        # → 404
done
# R6 pipeline admin endpoints stay public-404:
curl -s -o /dev/null -w "%{http_code}\n" "https://siri.choukalos.com/media/pipeline/jobs"    # → 404
curl -s -o /dev/null -w "%{http_code}\n" -X POST "https://siri.choukalos.com/media/pipeline/dl_token"   # → 404
# R7 cf-cache-status DYNAMIC on a public dl response (not edge-cached):
curl -sI "https://siri.choukalos.com/media/pipeline/dl/$TOK" | grep -i cf-cache-status   # → DYNAMIC
rm -f /tmp/p12bc_up.txt
```

### 4.3 MCP face via litellm (public)

```bash
# M1 tools/call end-to-end through the public MCP endpoint (chuck key):
curl -s -X POST https://llm.choukalos.com/mcp \
  -H "Authorization: Bearer ${LITELLM_KEY_CHUCK}" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"mcp_filebridge-file_work_areas","arguments":{}}}'
# → result content = the 5 registered work areas (use the exact tool name
#   from step 3's listing if the prefix differs)
# M2 D13 negative through the public path: file_push destination=siri_outputs → isError
# M3 default-deny negative: a key not in any access group → 0 file tools (step 3 loop)
```

### 4.4 publish-file skill wrapper (hot — no skill-runner restart)

```bash
# one real skill run exercises wrapper → POST /publish → engine (ai-net):
# (via the skill-runner API as usual — e.g. the existing publish-file
#  invocation path; expect the report shape {summary, artifact_path,
#  report:{path,url,size_bytes,sha256,...}} and the file under
#  /home/chuck/data/media/public/<subdir>/)
ls -la /home/chuck/data/media/public/ai/ | tail -3
```

### 4.5 Kill switch + port diff

```bash
# K1 kill switch: stop the bridge → public file routes 502, Matrix + skill-runner untouched:
docker stop mcp_filebridge
curl -s -o /dev/null -w "dl: %{http_code}\n" "https://siri.choukalos.com/media/pipeline/dl/$TOK"     # → 502
curl -s -o /dev/null -w "files: %{http_code}\n" "https://siri.choukalos.com/media/files/generated/<real-file>"  # → 502
curl -s -o /dev/null -w "token: %{http_code}\n" "$TOKEN_URL"                                          # → 502
curl -s -o /dev/null -w "matrix: %{http_code}\n" http://192.168.4.55:8189/health                      # → 200
curl -s -o /dev/null -w "skill-runner: %{http_code}\n" http://192.168.4.54:8091/health                # → 200
docker start mcp_filebridge && sleep 8
curl -s -o /dev/null -w "files after: %{http_code}\n" "https://siri.choukalos.com/media/files/generated/<real-file>"  # → 200
# NOTE: the restart revokes all outstanding 1b tokens (in-process store —
# by design; re-mintable in one tool call).
# K2 no new host port:
ss -tlnp | sort > /tmp/ss-after-p12bc.txt
diff /tmp/ss-baseline-p12bc.txt /tmp/ss-after-p12bc.txt    # → no new listening host port
```

## Rollback anchors

Ordered from most-likely to least-likely. Each is independent; the
deploy is a superset of the P12-A live state, so rolling back any piece
restores a known-good state.

**A. Bridge image (rebuild old image from git `79c39d5` + recreate):**

```bash
cd /home/chuck/homelab
rm -rf /tmp/fb-rollback && mkdir -p /tmp/fb-rollback
git archive 79c39d5 mcp/servers/filebridge | tar -x -C /tmp/fb-rollback
docker build -t ai-mcp-mcp_filebridge /tmp/fb-rollback/mcp/servers/filebridge
docker compose -f compose/compose.mcp.yml --env-file .env up -d --no-build --force-recreate mcp_filebridge
```

Fast variant (step 0 tag, no rebuild):
`docker tag mcp_filebridge_pre_p12bc_<date> ai-mcp-mcp_filebridge:latest`
then the same `up -d --no-build --force-recreate`.
The extra compose mounts are harmless to the old image (bind mounts only).
The old image has no `/mcp`, no `/publish`, no token route — the litellm
`mcp_filebridge` entry will then fail to connect (tools unavailable);
revert B + C too if that matters.

**B. litellm config revert (removes the 15th server entry):**

```bash
cd /home/chuck/homelab && git checkout 79c39d5 -- litellm/config.yml
docker compose -f compose/compose.ai-core.yml --env-file .env restart litellm   # user timing
```

**C. Access-group revert (removes `mcp_filebridge` from the grant):**

```bash
cd /home/chuck/homelab && set -a && . ./.env && set +a
python3 - <<'PY'
import json, os, urllib.request
key, proxy, group = os.environ["LITELLM_MASTER_KEY"], "http://192.168.4.54:4000", "07c1acf8-ffb6-4dbc-918d-9c7199f76fa1"
before = json.load(open("/tmp/access_group_family_mcp_full_before.json"))
body = json.dumps({"access_mcp_server_ids": before["access_mcp_server_ids"]}).encode()
r = urllib.request.Request(proxy + "/v1/access_group/" + group, data=body,
    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(r, timeout=15))["access_mcp_server_ids"])
PY
```

**D. Token route: NO Caddy rollback needed** — the Caddyfile is
unchanged by this deploy; the token route is additive under the existing
`/media/files/*` route. Rolling back the bridge image (A) removes the
route; the Caddy rule just 404s unknown `/media/files/...` paths as
before.

**E. publish-file wrapper revert (hot, no restart):**
`git checkout 79c39d5 -- skills/publish_file/`

## Post-deploy (after the battery is green)

1. **Commit** (repo convention `<area> + imperative subject`), e.g.:
   - `mcp: add filebridge P12-B registry + signed tokens + MCP face`
   - `mcp: add filebridge P12-C publish engine + file_publish tool`
   - `compose: add filebridge work-area + publish mounts`
   - `litellm: register mcp_filebridge (15th mcp server)`
   - `skills: make publish-file a thin bridge wrapper`
   - `docs: P12-B/C design + deploy runbook + final report + NAS cleanup`
   - `security: mark P12-B/C deployed (Phase 12)`
2. **`security_todo.md` Phase 12:** flip the P12-B / P12-C lines from
   "PENDING DEPLOY" to "LIVE <date>" with the battery evidence.
3. **Kanban:** close Ideas 29 (P12-B) / 30 (P12-C) in project 12
   (MySQL `ai_kanban` on 192.168.4.54, creds in `.env`).
4. **Clean up battery artifacts** (`p12bc_deploy_*` files; Matrix-side
   uploads ride the 14-day retention).
5. **Outstanding 1b tokens** are revoked by any bridge restart
   (in-process store) — expected, documented in the design doc §4.

## Open items (carried from TODO 6)

- Real TTL expiry (min TTL 1 h) is not E2E-testable publicly — bounds +
  `expires_at` verified; expiry purge covered by unit tests (fake clock).
- Dockerfile `HEALTHCHECK` hardcodes port 8000 — side test containers
  need a `--health-cmd` override; production unaffected.
- `@Recently-Snapshot` (102 B) on the NAS could not be removed from thor
  (CIFS read-only) — optional manual cleanup from the NAS admin UI /
  Windows client (see `docs/nas_cleanup_2026-11-26.md` §4).
