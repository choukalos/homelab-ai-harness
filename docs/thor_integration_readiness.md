# Thor Integration Readiness Review

> Phase 13 — Stop before production integration. Comprehensive checklist.
> Date: 2026-07-04 (historical)
> Status: **Superseded** — integration long since complete. July status kept
> for reference; current-state deltas marked inline.

**Current state (2026-08-28):**
- Skill runner is in production (`THOR_IP:8091`), 13 skills, `/api/chat`
  gateway, long-term memory (Phases 0–9 complete — see
  `docs/memory/IMPLEMENTATION_STATE.md`), admin REST + CLI + `/metrics`.
- 8 MCP servers live in LiteLLM (streamable-http, **41 tools** — was 11/4 servers; 34 → 44 → 40 → 41 on 2026-08-28: media-pipeline tools replaced the legacy media tools, then `mcp_mysql` gained `schema_overview`).
- Images pinned: `litellm:v1.92.0`, `qdrant:v1.18.1` (2026-08-28, Phase 9).
- Qdrant JWT RBAC on; `mcp_knowledge` on a read-only key.
- Backup gap CLOSED: `scripts/backup-memory.sh` (.env + Qdrant snapshot,
  restore-tested) + git for config/code.
- Per-key MCP restrictions: **dropped by decision 2026-08-25** —
  `allow_all_keys: true` is intentional (every valid key may call every tool).
- Caddy/Cloudflare: `siri.choukalos.com` → skill-runner:8091 live; public
  routes stable.

---

## Summary

All documentation, implementation, and containerization phases are complete. MCP servers are live in LiteLLM via SSE containers. All 11 tools are registered and visible. The platform is ready for Chuck's manual Phase 14 verification.

**Readiness: 90%** — Core implementation is done. Phase 14 manual verification items remain.

---

## Checklist

### Foundation

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | Backup exists | ✅ **DONE** (2026-08-26) | `scripts/backup-memory.sh` — `.env` copy + `mem0_memories` Qdrant snapshot to `/home/chuck/data/backups/`; restore tested into a throwaway Qdrant (2026-08-28). Git covers config/code. (July: ⚠️ NOT DONE.) |
| 2 | AI inventory complete | ✅ | `docs/thor_ai_inventory.md` — completed Phase 1 |
| 3 | Channel architecture complete | ✅ | `docs/thor_channels_architecture.md` — 10 channels documented, Phase 2 |
| 4 | Public access model complete | ✅ | `docs/thor_public_access_model.md` — routes, keys, rules, Phase 3 |
| 5 | Model alias registry complete | ✅ | `docs/thor_model_alias_registry.md` — Phase 4.1 |
| 6 | Artifact strategy complete | ✅ | `docs/thor_artifact_strategy.md` — Phase 4.3 |
| 7 | Harness rebuild plan complete | ✅ | `docs/thor_ai_harness_rebuild.md` — Option C, Phase 4.4 |
| 8 | Observability plan complete | ✅ | `docs/thor_observability_plan.md` — Phase 12 |
| 9 | Presenton integration complete | ✅ | `docs/thor_presenton_integration.md` — Phase 11 |
| 10 | Data classification complete | ✅ | `docs/thor_data_classification.md` — 5 curated collections, Phase 4.2 |
| 11 | MCP architecture document complete | ✅ | `docs/thor_mcp_architecture.md` — Phase 4.5 |
| 12 | Skill architecture document complete | ✅ | `docs/thor_skill_architecture.md` — Phase 4.6 |
| 13 | Validation log complete | ✅ | `docs/thor_validation_log.md` — Phase 0 |
| 14 | Manual tasks document complete | ✅ | `docs/thor_manual_tasks.md` — Phase 0 |

### MCP Servers

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | MCP search — code complete | ✅ | `mcp/servers/search/` — server.py, tests, Dockerfile, pyproject.toml (Phase 6) |
| 2 | MCP search — live in LiteLLM | ✅ | SSE container on `ai-net`, 3 tools registered (Phase 15) |
| 3 | MCP knowledge — code complete | ✅ | `mcp/servers/knowledge/` — server.py, tests, Dockerfile, pyproject.toml (Phase 7) |
| 4 | MCP knowledge — live in LiteLLM | ✅ | SSE container on `ai-net`, 4 tools registered (Phase 15) |
| 5 | MCP crawl — live in LiteLLM | ✅ | SSE container on `ai-net`, 1 tool registered (Phase 15) |
| 6 | MCP filesystem — live in LiteLLM | ✅ | SSE container on `ai-net`, 3 tools registered (Phase 15) |
| 7 | All 11 tools visible | ✅ | Verified via `GET /v1/mcp/tools` (Phase 15) |
| 8 | MCP crawl — full code | ℹ️ | Container runs. Full implementation TBD. |
| 9 | MCP filesystem — full code | ℹ️ | Container runs. Full implementation TBD. |
| 10 | MCP stocks not implemented | ℹ️ | Placeholder README only. Future work. |
| 11 | MCP homelab status not implemented | ℹ️ | Placeholder README only. Future work. |
| 12 | MCP media not implemented | ℹ️ | Placeholder README only. Future work. |
| 13 | MCP home not implemented | ℹ️ | Placeholder README only. Future work. |

### Skill Runner

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | Skill runner code complete | ✅ | `skills/runner/main.py` — FastAPI app, job lifecycle API (Phase 8) |
| 2 | Skill runner Dockerfile | ✅ | `skills/runner/Dockerfile` (Phase 8) |
| 3 | Skill runner pyproject.toml | ✅ | `skills/runner/pyproject.toml` (Phase 8) |
| 4 | Dev mode script | ✅ | `skills/runner/dev.sh` — laptop dev on port 8091 (Phase 8) |
| 5 | Compose file | ✅ | `compose/compose.skill-runner.yml` — container mode on `ai-net` (Phase 8) |
| 6 | Job lifecycle endpoints | ✅ | POST /skills/{name}, GET /jobs/{id}, GET /jobs/{id}/artifact (Phase 8) |
| 7 | Dry-run mode | ✅ | Supports `dry_run: true` (Phase 8) |
| 8 | Approval gates | ✅ | `family_kb_ingest` and `repo_maintenance` default to awaiting_approval (Phase 8) |

### Skills

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | siri_ask implemented | ✅ | `skills/siri_ask/` — skill.py, skill.yml, README.md (Phase 9) |
| 2 | deep_research implemented | ✅ | `skills/deep_research/` — skill.py, skill.yml, README.md (Phase 9) |
| 3 | presentation_build implemented | ✅ | `skills/presentation_build/` — skill.py, skill.yml, README.md (Phase 9/11) |
| 4 | code_review has README only | ℹ️ | Not yet implemented. Future work. |
| 5 | investment_brief has README only | ℹ️ | Not yet implemented. Future work. |
| 6 | family_kb_ingest has README only | ℹ️ | Not yet implemented. Future work. |
| 7 | morning_brief has README only | ℹ️ | Not yet implemented. Future work. |
| 8 | homelab_report has README only | ℹ️ | Not yet implemented. Future work. |
| 9 | repo_maintenance has README only | ℹ️ | Not yet implemented. Future work. |

### LiteLLM Configuration

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | Draft MCP config exists | ✅ | `litellm/draft/mcp-config.example.yaml` — 8 MCP server definitions (Phase 10) |
| 2 | Draft tool bundles exist | ✅ | `litellm/draft/tool-bundles.example.yaml` — 6 bundles (Phase 10) |
| 3 | Draft model aliases exist | ✅ | `litellm/draft/model-aliases.example.yaml` — 5 aliases + per-key allowlists (Phase 10) |
| 4 | SSE config applied to LiteLLM | ✅ | `litellm/config.yml` updated with SSE transport for 4 MCP servers (Phase 15) |
| 5 | LiteLLM upgraded to 1.92.0 | ✅ | Resolved tool calling issues (Phase 15) |
| 6 | Metrics auth bypass fixed | ✅ | `require_auth_for_metrics_endpoint: false` (Phase 15) |
| 7 | Per-key MCP restrictions | ✅ **Resolved (2026-08-25)** | Decision: `allow_all_keys: true` is intentional — every valid key may call every MCP tool; scoped grants dropped. (July: ⚠️ NEEDED.) |

### Rollback & Safety

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | Rollback instructions | ⚠️ **PARTIAL** | `thor_manual_tasks.md` has Phase 0 backup task. Phase 14 rollback needs detail. |
| 2 | Manual LiteLLM tasks documented | ✅ | `TODO.md` Phase 10 and `thor_manual_tasks.md` Phase 0 |
| 3 | Manual Caddy task drafted | ⚠️ **NEEDED** | Required for skill runner routing (`:8091` behind Caddy). |
| 4 | Manual Cloudflare task drafted | ⚠️ **NEEDED** | Required for any new public endpoints. |
| 5 | Manual Victoria Metrics task | ✅ | `thor_observability_plan.md` has scrape config drafts. |

---

## Known Gaps

### Completed in This Run (2026-07-04)

All phases 0–9, 12, and 15 are done:
- ✅ Phase 0: Read-only backup and discovery
- ✅ Phase 1: AI capability inventory
- ✅ Phase 2: Channel architecture
- ✅ Phase 3: Public access model
- ✅ Phase 4: All 6 design documents (4.1–4.6)
- ✅ Phase 5: Skeleton directories created
- ✅ Phase 6: MCP search server built
- ✅ Phase 7: MCP knowledge server built
- ✅ Phase 8: Skill runner skeleton built
- ✅ Phase 9: First 3 skills implemented (siri_ask, deep_research, presentation_build)
- ✅ Phase 10: LiteLLM draft configs created
- ✅ Phase 11: Presenton integration (was done prior)
- ✅ Phase 12: Observability plan
- ✅ Phase 15: All 4 MCP servers containerized with SSE, live in LiteLLM, 11 tools verified

### Blocking for Phase 14

1. **Backup not taken** — Chuck must execute a real backup before any further production changes.
2. **Per-key MCP access restrictions** — Currently `allow_all_keys: true` on all servers. Needs scoped grants per key.
3. **Caddy task not drafted** — Need manual task for routing skill runner (`:8091`) behind Caddy.
4. **Cloudflare task not drafted** — Need manual task if new public endpoints are needed.

### Non-Blocking (Future)

- MCP stocks, homelab_status, media, home servers — not yet implemented
- 6 of 9 skills have READMEs only (no `skill.py`): code_review, investment_brief, family_kb_ingest, morning_brief, homelab_report, repo_maintenance
- Grafana dashboards — not yet created
- Alert rules — not yet defined
- Skill runner not yet running in production (only dev mode / draft compose)

---

## Manual Tasks Pending (Chuck)

### Critical (Before Any Further Changes)

| # | Task | Where | Description |
|---|---|---|---|
| 1 | Execute backup | `thor_manual_tasks.md` / `TODO.md` Phase 0 | Full backup of all production configs and data |
| 2 | Draft Caddy task | — | Route skill runner behind Caddy on LAN (`:8091`) |
| 3 | Draft Cloudflare task | — | Define any new public endpoints (if needed) |
| 4 | Create per-key MCP restrictions | `TODO.md` Phase 14 | Replace `allow_all_keys: true` with scoped grants |

### Phase 14 Verification (After Restart)

| # | Task | Where | Description |
|---|---|---|---|
| 5 | Verify existing services | `TODO.md` Phase 14 | Open WebUI, llm.choukalos.com, siri.choukalos.com all work |
| 6 | Test MCP tool calls | `TODO.md` Phase 14 | Test through `/v1/chat/completions` with tool definitions |
| 7 | Test per-key MCP access | `TODO.md` Phase 14 | Each key against allowed/disallowed MCP servers |
| 8 | Verify /v1/mcp/tools | — | All 11 tools still visible after any config changes |
| 9 | Verify /metrics endpoint | — | Returns 200 with auth bypass |

### Future (Non-Blocking)

| # | Task | Where | Description |
|---|---|---|---|
| 10 | Enable skill runner /metrics | `thor_observability_plan.md` | Add prometheus_client middleware |
| 11 | Extend Victoria Metrics | `thor_observability_plan.md` | Add scrape targets for skill runner, MCP servers |
| 12 | Create Grafana dashboards | `thor_observability_plan.md` | Dashboards for skill runner, MCP tools |
| 13 | Harden Presenton auth | `thor_presenton_integration.md` | Change default credentials |
| 14 | Implement remaining skills | `TODO.md` Phase 9 | 6 skills currently have READMEs only |

---

## Recommended Phase 14 Sequence

1. **Backup** — Full backup of all production data (CRITICAL, do first)
2. **Verify existing services** — Open WebUI, llm.choukalos.com, siri.choukalos.com all still work
3. **Test MCP tool calls** — Call tools through `/v1/chat/completions` with tool definitions
4. **Verify /v1/mcp/tools** — All 11 tools still visible
5. **Per-key MCP restrictions** — Replace `allow_all_keys: true` with scoped grants
6. **Test per-key access** — Each key against allowed/disallowed MCP servers
7. **Caddy config update** — Route skill runner (`:8091`) behind Caddy (LAN-only)
8. **Skill runner in production** — Start container via `compose/compose.skill-runner.yml`
9. **Observability** — Enable /metrics endpoints, extend Victoria Metrics
10. **Full validation** — Test all keys, all models, all channels
11. **Rollback if needed** — Restore backup if anything breaks

## Current Live State (2026-07-04)

| Component | Status | Details |
|---|---|---|
| mcp_search | ✅ LIVE | SSE container, 3 tools (search_web, search_recent, search_news) |
| mcp_knowledge | ✅ LIVE | SSE container, 4 tools (kb_search, kb_get_document, kb_list_collections, kb_recent_changes) |
| mcp_crawl | ✅ LIVE | SSE container, 1 tool (crawl_page) |
| mcp_filesystem_readonly | ✅ LIVE | SSE container, 3 tools (read_file, list_directory, search_files) |
| LiteLLM version | 1.92.0 | Upgraded to fix tool calling issues |
| Metrics auth | ✅ FIXED | `require_auth_for_metrics_endpoint: false` |
| All 11 tools | ✅ VERIFIED | Via `GET /v1/mcp/tools` |
| Skill runner | 📝 DRAFT | Code complete, not yet running in production |
| Siri skill | 📝 DRAFT | `siri_ask` skill implemented, not yet routed through Caddy |
| Caddy skill route | ⚠️ PENDING | Manual task needed to switch `siri.choukalos.com` from `:8090` to `:8091` |

---

## Conclusion

**All implementation and documentation phases are complete. Production integration and manual verification is a manual task for Chuck.**

- ✅ 14 design/documentation documents complete (Phases 0–4, 12)
- ✅ Skeleton directories created (Phase 5)
- ✅ 2 core MCP servers built and tested (search, knowledge) (Phases 6–7)
- ✅ 4 MCP servers containerized and live in LiteLLM via SSE (Phase 15)
- ✅ All 11 tools verified via `/v1/mcp/tools`
- ✅ Skill runner built with full job lifecycle API (Phase 8)
- ✅ 3 skills implemented (siri_ask, deep_research, presentation_build) (Phase 9)
- ✅ Draft LiteLLM configs for MCP, tool bundles, and model aliases (Phase 10)
- ✅ Observability plan with manual tasks (Phase 12)
- ✅ Presenton integration documented (Phase 11)
- ✅ LiteLLM upgraded to 1.92.0, metrics auth bypass fixed (Phase 15)

**What's pending (manual, for Chuck):**
- Execute a production backup (CRITICAL)
- Verify existing services still work (Open WebUI, llm.choukalos.com, siri.choukalos.com)
- Test MCP tool calls through `/v1/chat/completions`
- Create per-key MCP access restrictions (replace `allow_all_keys`)
- Draft Caddy task for skill runner routing
- Draft Cloudflare task for new public endpoints
- Enable observability (metrics, Victoria Metrics, Grafana dashboards)

**Phase 14 is manual-only — no automated changes to production.**
