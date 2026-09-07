# Thor Manual Tasks

> Tasks that require Chuck's manual intervention.
> Updated: 2026-08-28 (backup + skill-runner /metrics marked DONE; remaining
> items still open)

---

## Phase 0 - Backup

```text
MANUAL TASK FOR CHUCK:
Reason:
A real backup requires preserving production config and data before structural changes.
Command:
DONE (2026-08-26/28): scripts/backup-memory.sh — copies .env + snapshots the
mem0_memories Qdrant collection to /home/chuck/data/backups/; restore tested
into a throwaway Qdrant (2026-08-28). Git covers config/code; .env is copied
into the archive.
Expected impact:
None if done as copy/archive only.
Rollback:
Restore from backup archive.
Validation:
Confirmed: .env + mem0_memories snapshot present; restore round-trip verified
(points_count matches, payloads readable). Other collections (family_kb,
mem0migrations) are not in scope for this script — family_kb has no
production data (18 curated docs, re-ingestable).
```

---

## Phase 3 - Public Access Changes

```text
MANUAL TASK FOR CHUCK:
Reason:
Changing public access can expose private services or interrupt existing public apps.
Command:
TBD after Qwen drafts Caddy/Cloudflare changes.
Expected impact:
Could affect the blog portal, Invest Hub, Siri, or LiteLLM access.
Rollback:
Restore previous Caddyfile and Cloudflare Tunnel config.
Validation:
Confirm the blog portal, Invest Hub, Siri, and LiteLLM still work and no admin endpoints are exposed.
```

---

## Phase 10 - LiteLLM MCP Config

```text
MANUAL TASK FOR CHUCK:
Reason:
Registering MCP tools in LiteLLM may require LiteLLM config reload or proxy restart.
Command:
Review litellm/draft/*.yaml files. Copy approved sections into live litellm/config.yml. Restart/reload LiteLLM.
Expected impact:
LiteLLM may briefly interrupt active clients during restart.
Rollback:
Restore previous LiteLLM config and restart/reload LiteLLM.
Validation:
LiteLLM health works, existing model aliases work, Open WebUI can chat, and MCP discovery works for a test key only.
```

---

## Phase 10 - Model Aliases & Per-Key Restrictions

```text
MANUAL TASK FOR CHUCK:
Reason:
Adding model aliases (local/*) and per-key model allowlists changes how clients access models. Existing clients using matrix-coder etc. should continue to work during transition.
Command:
Review litellm/draft/model-aliases.example.yaml. Add local/* aliases alongside existing model names. Configure per-key allowlists in LiteLLM.
Expected impact:
New aliases available. Old names still work. Clients can migrate at their own pace.
Rollback:
Remove new aliases from LiteLLM config and reload.
Validation:
curl with each key to verify allowed/denied model access is correct.
```

---

## Phase 11 - Presenton Auth Hardening

> **SUPERSEDED 2026-09-04** — Presenton is now passwordless + LAN-only
> (`DISABLE_AUTH=true`, no public route, port bound to `${THOR_IP}:5000`).
> `PRESENTON_AUTH_PASSWORD` removed from `.env`; this task no longer applies.
> Family access: `http://thor.local:5000`.

```text
MANUAL TASK FOR CHUCK:
Reason:
Presenton uses HTTP Basic auth. Set `PRESENTON_AUTH_PASSWORD` in `.env` before enabling remote skill access.
Command:
Edit Presenton environment variables in compose/compose.ai-core.yml (PRESENTON_AUTH_USERNAME, PRESENTON_AUTH_PASSWORD). Restart Presenton container only.
Expected impact:
Brief Presenton downtime during restart. Skill runner will reconnect on next request.
Rollback:
Restore previous credentials in compose file and restart Presenton.
Validation:
Presenton UI loads with new credentials. Skill runner generates presentations successfully.
```

---

## Phase 12 - Enable Skill Runner Prometheus Metrics

```text
MANUAL TASK FOR CHUCK:
Reason:
Skill runner needs to expose /metrics for Victoria Metrics scraping.
Command:
Add prometheus_client FastAPI middleware to skills/runner/main.py (implementation to be provided). Restart skill runner.
Expected impact:
New /metrics endpoint on port 8091. No impact on existing endpoints.
Rollback:
Remove middleware from main.py. Restart skill runner.
Validation:
curl http://localhost:8091/metrics returns prometheus-formatted metrics.
```

---

## Phase 12 - Extend Victoria Metrics Scraping

```text
MANUAL TASK FOR CHUCK:
Reason:
Victoria Metrics needs to scrape new endpoints: skill runner, Qdrant, and optionally Caddy.
Command:
Add scrape targets to Victoria Metrics config (draft in thor_observability_plan.md). Restart Victoria Metrics.
Expected impact:
New metrics collected. No impact on existing scrapes.
Rollback:
Remove new scrape targets from Victoria Metrics config. Restart Victoria Metrics.
Validation:
Victoria Metrics API returns data for new job names.
```

---

## Phase 12 - Create Grafana Dashboards

```text
MANUAL TASK FOR CHUCK:
Reason:
New dashboards needed for Skill Runner, MCP Tools, Public Endpoints, and Platform Health.
Command:
Create Grafana dashboard JSON files in the provisioned dashboards directory. Reload Grafana provisioning.
Expected impact:
New dashboards visible in Grafana on port 3001.
Rollback:
Delete dashboard JSON files and reload Grafana provisioning.
Validation:
Dashboards render with data from Victoria Metrics.
```

---

## Phase 14 - Skill Runner Caddy Routing

```text
MANUAL TASK FOR CHUCK:
Reason:
Skill runner needs a Caddy route for LAN access and eventual remote access (Siri channel).
Command:
Add Caddy route for skill runner (e.g., skill.thor.lan or internal path on existing host). Draft Caddyfile snippet to be provided.
Expected impact:
Skill runner accessible via Caddy on LAN. No public exposure initially.
Rollback:
Remove Caddy route. Restart Caddy.
Validation:
Skill runner health endpoint reachable through Caddy. Existing services unaffected.
```

---

## Phase 14 - Cloudflare Tunnel (If Needed)

```text
MANUAL TASK FOR CHUCK:
Reason:
If remote skill access is needed beyond Siri (which goes through existing tunnel), new Cloudflare routes may be needed.
Command:
TBD. Depends on which endpoints need remote access. Current plan: only Siri path through existing siri.choukalos.com route.
Expected impact:
New public endpoint. Must verify no unintended exposure.
Rollback:
Remove Cloudflare Tunnel route.
Validation:
New endpoint works from outside. No admin endpoints exposed.
```

---

## Phase 15 - Media Pipeline Public Route + Portal /files/*: Cloudflare Cache Rules (2026-09-07)

```text
MANUAL TASK FOR CHUCK (Cloudflare dashboard — no API/DNS change needed):
Reason:
Two public paths need correct edge-cache behavior after the 2026-09-07
origin changes:
  1. GET /media/pipeline/dl/<token> on siri.choukalos.com (new public
     signed-URL route, Caddy @siri_pipeline → matrix :8189).
  2. /files/* on choukalos.com (portal T1: origin now sends
     max-age=60, must-revalidate + Last-Modified and answers
     If-Modified-Since with 304 — re-published files were previously
     invisible behind the CF edge for up to 4h).
Dashboard steps:
1. Cloudflare dashboard → choukalos.com → Rules → Cache Rules → Create rule.
2. Rule name: "Media pipeline signed URLs".
3. Expression (host + path prefix):
     host equals siri.choukalos.com AND
     starts_with(http.request.uri.path, "/media/pipeline/dl/")
4. Behavior: "Cache eligible", Edge TTL = 1 hour (or "Default TTL").
   Signed URLs are safe to edge-cache: the token is in the URL and a cached
   copy serves the same bytes. If you prefer zero edge caching, use
   "Bypass cache" instead — downloads still work (slower repeat fetches).
   Do NOT create a rule caching POST /media/pipeline/upload (POSTs are
   never cached by CF; informational).
5. Second rule: name "Portal files drop zone", expression:
     host equals choukalos.com AND
     starts_with(http.request.uri.path, "/files/")
   Behavior: "Cache eligible", Edge TTL = 60 seconds (matches the origin's
   new max-age=60, must-revalidate; the origin answers revalidation with
   304, so it costs bytes, not the full file).
6. Purge the stale edge entry for the video (otherwise the old copy with
   the 4h TTL keeps being served until it expires): Caching → Manage Cache
   → Purge → Custom URL(s):
     https://choukalos.com/files/video/peanut_doc_final.mp4
   (or "Purge everything by hostname" for choukalos.com if you prefer).
7. Save. No tunnel/DNS change required — both routes already exist
   (Caddy @siri_pipeline + portal /files/, verified 2026-09-07).
Expected impact:
  - /media/pipeline/dl/*: repeat fetches served from edge (faster, less
    LAN load). No new exposure: /dl_token and the rest of the pipeline API
    are not proxied publicly (Caddy 404s them).
  - /files/*: re-published files visible at the edge within ~1 min
    (origin revalidates every 60s, 304 when unchanged).
Rollback:
Delete the cache rule(s) in the dashboard. Signed URLs and /files/* keep
working via origin (Caddy → matrix / portal).
Validation:
  # media pipeline (token from mcp_media.media_pull):
  curl -sI "https://siri.choukalos.com/media/pipeline/dl/<token>" | grep -i cf-cache-status
  #   first fetch: MISS/DYNAMIC; second fetch: HIT if the rule is active
  # portal:
  curl -sI "https://choukalos.com/files/video/peanut_doc_final.mp4" | grep -iE "cf-cache-status|content-length"
  #   after the purge: revalidation flow (HIT within 60s, MISS after)
  # T1 acceptance (needs sudo — root-owned file):
  #   sudo cp peanut_doc_final.mp4 /tmp/ ; write a different-sized test
  #   copy; within ~2 min the bare public URL shows the new content-length;
  #   restore the original (sha256-verify).
```

---

## Summary of Pending Manual Tasks

| # | Phase | Task | Priority |
|---|---|---|---|
| 1 | 0 | Execute backup | ✅ DONE 2026-08-26/28 — `scripts/backup-memory.sh`, restore tested |
| 2 | 3 | Review public access changes | High — affects all public services |
| 3 | 10 | Apply LiteLLM MCP config | High — core integration |
| 4 | 10 | Apply model aliases & key restrictions | High — core integration |
| 5 | 11 | Harden Presenton auth | Medium — before remote skill access |
| 6 | 12 | Enable skill runner /metrics | ✅ DONE 2026-08-28 — `/metrics` + VictoriaMetrics job `skill-runner` |
| 7 | 12 | Extend Victoria Metrics scraping | ✅ skill-runner done 2026-08-28 (Qdrant/MCP/Caddy drafts open) |
| 8 | 12 | Create Grafana dashboards | Low — nice to have |
| 9 | 14 | Skill runner Caddy routing | High — LAN access |
| 10 | 14 | Cloudflare tunnel (if needed) | Low — depends on remote needs |
| 11 | 15 | Cloudflare cache rules: `/media/pipeline/dl/*` (siri) + `/files/*` (portal, 60s edge TTL) + purge stale video entry | Medium — dashboard-only; unblocks T1 public acceptance |
