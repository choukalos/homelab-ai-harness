# Housekeeping: image pins, reboot approval gate, /model/info restriction, Dylan MCP scoping

- slug: tier3-housekeeping
- date: 2026-11-19
- status: in progress (2026-11-20: H1+H2 applied; H3 left open by chuck 2026-11-23 — feature check done: v1.104.0 has no native per-endpoint key roles, only `litellm_settings.custom_auth` (replaces the whole auth flow); chuck is researching the options before deciding; H4 deferred by design)
- applied: 2026-11-20 (pi, thor) — H1+H2 only. H1: pinned the three remaining `:latest` images in `compose/compose.ai-core.yml` to the currently running digests — `searxng/searxng@sha256:c642712f…`, `unclecode/crawl4ai@sha256:9021b3cb…`, `ghcr.io/presenton/presenton@sha256:ddf0d1f2…` (digests from `docker inspect` on the running containers; note: Docker 29.9.3 container inspect has no top-level `RepoDigests`, so the repo digests were read from `docker image inspect <image>` and verified to resolve to each running container's image ID; config-only, no restart). H2: new `docs/operations/approval-gates.md` — explicit approval gate for thor host reboots / whole-Docker-stack shutdowns (no reboot or stack shutdown without Chuck's explicit request; extends the standing rule for litellm-proxy / session-carrying services, memory `0b2ff954`), referencing the job-checkpoint mechanism (`docs/operations/job-checkpoints.md`) as the mitigation. H3 remains open (verify v1.104.0 per-endpoint key roles before applying); H4 remains deferred by design.
- tier: 3
- target user: chuck
- source: workspace/ideas/2026-11-17-litellm-model-info-and-uptime.md (5a, 4b) + workspace/ideas/suggested_mcp_improvements.md (item 4) + security_todo.md (Phase 2 decision matrix)

## What
Four small, independent items:
1. **H1 — pin the remaining `:latest` images** (litellm/qdrant were pinned in security Phase 9): `searxng`, `crawl4ai`, `presenton` in `compose/compose.ai-core.yml` (verified still `:latest` 2026-11-19). Pin to the currently running digests (`docker inspect` on the hosts).
2. **H2 — explicit approval gate for thor host reboots / Docker stack shutdowns.** Extend the standing rule (never restart litellm-proxy / session-carrying services without Chuck's explicit request, memory `0b2ff954`) to the host and the whole stack. A thor reboot at 19:57 on 2026-11-01 interrupted in-flight tab production and destroyed the agent's session context — the work had to be redone from scratch. (The in-flight job checkpoint endpoint, `2026-11-08-add-inflight-job-checkpoint`, is applied; this is the process half.)
3. **H3 — restrict `/model/info` to master/admin keys** if v1.104.0 supports per-endpoint key roles. Verified 2026-11-17: reachable with any valid key (chuck's virtual key, not master) and it exposes internal topology (upstream `api_base`, upstream model names) on the public domain. Low risk (key-gated) — verify the feature exists before applying.

   **Feature check result (2026-11-23, on the running v1.104.0 container):** the
   condition is **not met natively**.
   - `/model/info`, `/v1/model/info`, `/v2/model/info` (and `/model_group/info`)
     are all declared `dependencies=[Depends(user_api_key_auth)]` in
     `proxy_server.py` — any valid key passes; role checks on admin endpoints
     are hardcoded per handler, not config-driven.
   - No per-endpoint key-role config exists in v1.104.0 (`_types.py` has no
     route/endpoint permission model; `admin_allowed_routes` is JWT-auth-only
     and we use virtual keys).
   - Only supported mechanism: `litellm_settings.custom_auth` — a script that
     **replaces** the default `user_api_key_auth` for ALL endpoints (feasible:
     delegate to the default, then 403 non-master keys on `/model/info*`
     routes; but a broken script locks out every key, so it needs careful
     testing).
   - Decision (chuck, 2026-11-23): **leave H3 open** — no `custom_auth`
     implementation for now; the options (wait for native per-endpoint roles
     in a future LiteLLM release vs a `custom_auth` script) are being
     researched before any implementation.
4. **H4 — Dylan MCP scoping (deferred).** Per the 2026-11-15 decision, both family keys get all 12 MCP servers via `family-mcp-full`. Revisit when desired: create a second group `dylan-mcp-scoped` (search, knowledge, memory, homelab_status, vision, filesystem_readonly, skills — **no** mysql, datahub, filesystem-write) with Dylan's key only. Note: a key in two groups gets the union — use exactly one group per key (remove Dylan from `family-mcp-full` when switching).

## Why (evidence)
- H1: supply-chain/upgrade drift on three unpinned images (standard hardening; Phase 9 precedent).
- H2: data loss already happened (2026-11-01 reboot); the fix is mostly process + the checkpoint convention, so it's cheap relative to the cost of the next incident.
- H3/H4: low-risk least-privilege tightening left open by the 2026-11-15 security work.

## Risk + rollback
Low per item. H1 rollback = unpin; H2 is policy; H3/H4 rollback = remove the restriction / restore group membership. Apply H4 incrementally and test Dylan's tools end-to-end after (a scoping misconfiguration could lock an agent out of tools it needs).

## Files touched
- `compose/compose.ai-core.yml` (H1)
- `docs/` (H2 policy note — e.g. `docs/thor_public_access_model.md` or the standing-rules doc)
- LiteLLM config/API (H3, H4 — mechanism per v1.104.0 feature check)

---
_Drafted 2026-11-19 (pi, thor) from the workspace/ideas review. Review with `cli/proposals.sh`; applying is a human decision._
