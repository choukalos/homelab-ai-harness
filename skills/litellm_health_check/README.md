# litellm_health_check — LiteLLM proxy outage poller

Scheduled health probe for the LiteLLM proxy (tier2-litellm-health-visibility,
2026-11-19). Request metrics only show model health while traffic flows, so a
dead upstream (e.g. the macstudio OMLX outage of 2026-11-17+) can sit
undetected for days. This skill closes that gap.

## What it does

Every 5 minutes (schedule `litellm-health-check` in `scheduler/schedules.json`):

1. `GET {proxy}/health` with the LiteLLM key (runner's `LITELLM_API_KEY`).
2. **Healthy** (200 + empty `unhealthy_endpoints`) → silent: removes any
   existing alert file.
3. **Unhealthy** (`unhealthy_endpoints` non-empty, non-200, unparseable
   payload, or proxy unreachable — fail-closed) → writes/refreshes
   `/home/chuck/data/media/public/briefs/litellm-health-alert.md`, served at
   <https://choukalos.com/files/briefs/litellm-health-alert.md> (the existing
   notify path used by morning_brief's publish). The file keeps the FIRST
   detection timestamp and refreshes `last_confirmed` on every unhealthy run.

No LLM, no MCP — stdlib `urllib` only.

## Run manually

```bash
# via the runner (LAN)
curl -s -X POST http://192.168.4.54:8091/api/schedule/litellm-health-check/run-now

# standalone (host) — note the host sees the proxy at 192.168.4.54:4000
python3 skills/litellm_health_check/skill.py --proxy-url http://192.168.4.54:4000
# exit code: 0 = healthy, 1 = unhealthy (alert written)
```

## Rollback

Remove the schedule entry from `scheduler/schedules.json` (hot-reloaded) and
delete `skills/litellm_health_check/` + the alert file.
