# Fix the dead backup upstream: macstudio OMLX (macstudio:8000)

- slug: tier1-macstudio-omlx-restart
- date: 2026-11-19
- status: applied (2026-11-21 — Chuck reloaded the model on the Mac Studio; verified: `GET /v1/models` → 200 with both Gemma-4 models, chat completion through the LiteLLM proxy → 200 in ~4 s ("OMLX OK"). Capability probes run same day: tool calling WORKS, response_format json_schema WORKS, image_url → 500 (text-only) — `litellm/config.yml` flags updated to match (needs a litellm-proxy restart to take effect; staged 2026-11-21).)
- tier: 1
- target user: chuck
- source: workspace/ideas/2026-11-17-litellm-model-info-and-uptime.md (Group 5b)

## What
Restart/fix the OMLX server on the Mac Studio that serves `studio-gemma4-26b` at `http://macstudio:8000/v1` (host 192.168.4.56). Verify `GET /v1/models` returns 200 and a test chat completion works through the LiteLLM proxy.

## Why (evidence)
- Verified live 2026-11-19: `curl http://192.168.4.56:8000/v1/models` → connection refused (upstream down). It was already down at the 2026-11-17 audit (`/health` caught a ConnectionRefusedError; only 13 buried 500s in metrics revealed it).
- The "Backup LLM" is dead, so `matrix-coder` has no real fallback — the `tier1-litellm-model-config-pass` fallback entry is meaningless until this lands.
- The outage was invisible for days because there is no outage alerting without traffic (see `tier2-litellm-health-visibility`).

## Risk + rollback
Host-side work on the Mac Studio; no thor impact. If OMLX is broken beyond a restart, document the repair in `docs/` (OMLX setup notes) so the next outage is faster.

## Files touched
- (none in this repo — host-side on the Mac Studio)

---
_Drafted 2026-11-19 (pi, thor) from the workspace/ideas review. Review with `cli/proposals.sh`; applying is a human decision._
