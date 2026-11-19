# Housekeeping: image pins, reboot approval gate, /model/info restriction, Dylan MCP scoping

- slug: tier3-housekeeping
- date: 2026-11-19
- status: open
- tier: 3
- target user: chuck
- source: workspace/ideas/2026-11-17-litellm-model-info-and-uptime.md (5a, 4b) + workspace/ideas/suggested_mcp_improvements.md (item 4) + security_todo.md (Phase 2 decision matrix)

## What
Four small, independent items:
1. **H1 — pin the remaining `:latest` images** (litellm/qdrant were pinned in security Phase 9): `searxng`, `crawl4ai`, `presenton` in `compose/compose.ai-core.yml` (verified still `:latest` 2026-11-19). Pin to the currently running digests (`docker inspect` on the hosts).
2. **H2 — explicit approval gate for thor host reboots / Docker stack shutdowns.** Extend the standing rule (never restart litellm-proxy / session-carrying services without Chuck's explicit request, memory `0b2ff954`) to the host and the whole stack. A thor reboot at 19:57 on 2026-11-01 interrupted in-flight tab production and destroyed the agent's session context — the work had to be redone from scratch. (The in-flight job checkpoint endpoint, `2026-11-08-add-inflight-job-checkpoint`, is applied; this is the process half.)
3. **H3 — restrict `/model/info` to master/admin keys** if v1.104.0 supports per-endpoint key roles. Verified 2026-11-17: reachable with any valid key (chuck's virtual key, not master) and it exposes internal topology (upstream `api_base`, upstream model names) on the public domain. Low risk (key-gated) — verify the feature exists before applying.
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
