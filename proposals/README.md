# Proposals — harness change proposals

Durable change proposals for the homelab harness. Created by the weekly
`harness_reflection` run (propose-only) or by humans/pi. Humans drive the
lifecycle; applying is always a human decision.

## Lifecycle

```
open ──> accepted ──> applied
  └────> dismissed   (terminal)
```

Review + transition via the CLI (admin key, talks to skill-runner
`/api/proposals/*`):

```
cli/proposals.sh list [status] [--limit N]
cli/proposals.sh show <slug>
cli/proposals.sh accept <slug>
cli/proposals.sh dismiss <slug>
cli/proposals.sh mark-applied <slug>
```

State lives in two places, keyed by **slug** (canonical):

- **Markdown file** in this directory — the human-readable proposal
  (What / Why / Risk / Files touched).
- **`proposals` table** in the homelab MySQL DB (see
  `skills/runner/proposals.py`) — the durable index the reflection skill
  reads for dedup ("N open before run").

## Layout

- **Top level: active proposals only.** Filename = `YYYY-MM-DD-tierN-<slug>.md`
  where `YYYY-MM-DD` is the creation date and the slug (for files created
  2026-11-19 onward) starts with the tier prefix, e.g.
  `2026-11-19-tier1-cloudflare-524-read-timeout.md` → slug
  `tier1-cloudflare-524-read-timeout`.
- **`archive/`:** closed proposals (applied/dismissed), kept for history.
- Legacy files (pre-2026-11-19) may have a slug that does not match the
  filename (e.g. `2026-11-08-tier3-recent-activity-slow-run-optimization.md`
  has slug `recent-activity-slow-run-optimization`) — the slug in the file
  metadata + DB row is canonical.

## Tiers

| Tier | Meaning |
|---|---|
| **tier1** | Do this week — small, high value (config edits, doc fixes, host-side restarts) |
| **tier2** | Focused session — multi-file, cross-host, or new-surface work |
| **tier3** | Backlog — real but slower-burn |

Tier is a priority bucket, not a reflection-pipeline tier (the
"Tier 1 propose-only / Tier 2 human applies" language in older footers
refers to the reflection pipeline's own roles).

## Current state (2026-11-24)

- **tier1:** (none open — pinned-reference-values +
  reference-json-overwrite-guard applied 2026-11-23: market-research-brief
  reference rebuilds now preserve `pinned`/verified market-size + context
  values across runs, and every `references/<market>.json` write goes through
  a validate-then-atomic-rename guard that refuses profile-block payloads
  (20 new stdlib tests; both live datasets pass the guard). Earlier:
  macstudio-omlx-restart applied 2026-11-21: OMLX
  reloaded on the Mac Studio, `/v1/models` + proxy chat completion verified
  200; capability probes run and `litellm/config.yml` flags updated to match,
  staged pending a litellm-proxy restart)
- **tier2:** (none open — kanban-remote-client-file-intake applied 2026-11-23:
  durable per-project file store `/home/chuck/data/ai-kanban-files` → `/files`
  + `stage_file`/`stage_ref` intake (MCP + REST) + spec-path reachability
  preflight at `move_to_backlog`/`start_task`, so remote clients can author
  specs with client-local file paths; deployed + verified E2E 2026-11-23 —
  see `archive/2026-11-23-tier2-kanban-remote-client-file-intake.md`;
  2026-11-23: kanban-start-task-mysql-returning applied (the `transition()`
  MySQL `.returning()` crash — driver-conditional affectedRows fix +
  driver-realism test, commit 58ba806; deployed with the mcp_kanban rebuild
  2026-11-23 21:43 UTC; live transitions verified in the PWV2 session) and
  tipcalc-ship-docs applied (TipCalc user-facing docs shipped on tipcalc
  task/9; the tipcalc E2E test project was torn down 2026-11-24 — compose
  stack removed, test.choukalos.com reserved for future public-facing tests;
  its proposal file was never committed and was reconstructed from the DB row
  2026-11-24 — see `archive/2026-11-23-tier2-tipcalc-ship-docs.md`))
- **tier3:** housekeeping (in progress — H1 image pins + H2 approval gate
  applied 2026-11-20; H3 `/model/info` restriction left open by chuck
  2026-11-23 after the feature check (v1.104.0: no native per-endpoint key
  roles; only `litellm_settings.custom_auth`, which replaces the whole auth
  flow — options being researched); H4 Dylan scoping deferred by design)
- **archive:** 7 closed 2026-11-08 proposals (window guard, publish-file
  dedup, checkpoint, etc. — the reflection pipeline's first batch) +
  2026-11-19: litellm-model-config-pass, litellm-health-visibility,
  media-film-tool-names, media-film-production-lessons (all applied) +
  cloudflare-524-read-timeout (dismissed — no CF Enterprise plan) +
  pi-subagents-timeout-handling (dismissed) +
  2026-11-20: recent-activity-slow-run-optimization, memory-dedupe-supersede
  (both applied) + 2026-11-21: macstudio-omlx-restart (applied),
  mcp-sessions-remote-ingest (applied — Phase 1),
  matrix-media-pipeline-improvements (applied — M1–M5 landed on matrix,
  thor client layer `7f2d0d3`), media-queue-mcp-tools (applied —
  `media_kill_job` + `media_queue_status` live), and the mcp-kanban series —
  tier2-mcp-kanban (original), tier2-mcp-kanban-mcp-first,
  tier2-mcp-kanban-phase2-user-spend, tier2-mcp-kanban-improvements
  (all applied + verified live; durable content in the kanban README + ops
  docs) + 2026-11-23: pinned-reference-values,
  reference-json-overwrite-guard (both applied — `skills/market_research_brief/
  reference.py`; verified: 20 stdlib tests pass, both live reference datasets
  pass the write guard, skill.py render path exercised end-to-end) +
  2026-11-23: kanban-remote-client-file-intake (applied — durable file store
  + intake + preflight live on mcp_kanban; E2E round-trip + GC verified)
  + 2026-11-24 housekeeping: kanban-start-task-mysql-returning (applied —
  the MySQL transition() fix; file moved from repo root + DB row added) and
  tier2-tipcalc-ship-docs (applied — reconstructed from the DB row; the
  original file was never committed)
