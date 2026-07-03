# Thor Manual Tasks

> Tasks that require Chuck's manual intervention.
> Updated: 2026-07-03

---

## Phase 0 - Backup

```text
MANUAL TASK FOR CHUCK:
Reason:
A real backup requires preserving production config and data before structural changes.
Command:
TBD — will be specified after inventory is complete.
Expected impact:
None if done as copy/archive only.
Rollback:
Restore from backup archive.
Validation:
Confirm backup archive contains homelab configs, LiteLLM config/data, Open WebUI data, Qdrant data, Redis data if persistent, Caddy config, Cloudflare config, and relevant .env files.
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
Could affect Ghost, Invest Hub, Siri, or LiteLLM access.
Rollback:
Restore previous Caddyfile and Cloudflare Tunnel config.
Validation:
Confirm Ghost, Invest Hub, Siri, and LiteLLM still work and no admin endpoints are exposed.
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

```text
MANUAL TASK FOR CHUCK:
Reason:
Presenton uses default auth credentials (presenton/changeme123). These should be changed before any remote skill access.
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

## Summary of Pending Manual Tasks

| # | Phase | Task | Priority |
|---|---|---|---|
| 1 | 0 | Execute backup | **CRITICAL** — before any changes |
| 2 | 3 | Review public access changes | High — affects all public services |
| 3 | 10 | Apply LiteLLM MCP config | High — core integration |
| 4 | 10 | Apply model aliases & key restrictions | High — core integration |
| 5 | 11 | Harden Presenton auth | Medium — before remote skill access |
| 6 | 12 | Enable skill runner /metrics | Medium — observability |
| 7 | 12 | Extend Victoria Metrics scraping | Medium — observability |
| 8 | 12 | Create Grafana dashboards | Low — nice to have |
| 9 | 14 | Skill runner Caddy routing | High — LAN access |
| 10 | 14 | Cloudflare tunnel (if needed) | Low — depends on remote needs |
