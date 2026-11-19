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

## Current state (2026-11-19)

- **tier1:** cloudflare-524-read-timeout · litellm-model-config-pass ·
  macstudio-omlx-restart · media-film-tool-names
- **tier2:** mcp-sessions-remote-ingest · media-film-production-lessons ·
  pi-subagents-timeout-handling · litellm-health-visibility ·
  matrix-media-pipeline-improvements (⚠️ work host: matrix, not thor)
- **tier3:** recent-activity-slow-run-optimization (open since 2026-11-08) ·
  memory-dedupe-supersede · media-queue-mcp-tools (depends on the matrix
  proposal) · housekeeping
- **archive:** 7 closed 2026-11-08 proposals (window guard, publish-file
  dedup, checkpoint, etc. — the reflection pipeline's first batch)
