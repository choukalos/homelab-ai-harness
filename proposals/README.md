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

## Current state (2026-11-21)

- **tier1:** (none open — macstudio-omlx-restart applied 2026-11-21: OMLX
  reloaded on the Mac Studio, `/v1/models` + proxy chat completion verified
  200; capability probes run and `litellm/config.yml` flags updated to match,
  staged pending a litellm-proxy restart)
- **tier2:** pi-subagents-timeout-handling (open — source repo not on thor; locate
  first) · matrix-media-pipeline-improvements (in progress — parked on
  matrix cooperation; ⚠️ work host: matrix, not thor; self-contained
  handoff spec at `docs/matrix_media_pipeline_improvements_handoff.md`)
  · mcp-sessions-remote-ingest (applied 2026-11-21 — Phase 1 live + E2E
  verified through the proxy; see archive note)
- **tier3:** housekeeping (in progress — H1 image pins + H2 approval gate
  applied 2026-11-20; H3 `/model/info` restriction open pending feature
  check; H4 Dylan scoping deferred by design) ·
  media-queue-mcp-tools (open — depends on the matrix proposal M2/M3)
- **archive:** 7 closed 2026-11-08 proposals (window guard, publish-file
  dedup, checkpoint, etc. — the reflection pipeline's first batch) +
  2026-11-19: litellm-model-config-pass, litellm-health-visibility,
  media-film-tool-names, media-film-production-lessons (all applied) +
  cloudflare-524-read-timeout (dismissed — no CF Enterprise plan) +
  2026-11-20: recent-activity-slow-run-optimization, memory-dedupe-supersede
  (both applied) + 2026-11-21: macstudio-omlx-restart (applied) +
  mcp-sessions-remote-ingest (applied — Phase 1)
