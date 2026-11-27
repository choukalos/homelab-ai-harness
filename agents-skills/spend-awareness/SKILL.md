---
name: spend-awareness
description: Work within LLM cost budgets in the homelab — check the live spend picture (per-key LiteLLM totals + 24h, per-owner kanban usage) before starting a long or expensive job, batch operations, prefer the cheap model for exploration and spend the good model on the hard parts, and checkpoint durable progress so a restart doesn't burn the budget twice. Use at the start of any long task, multi-step job, or anything that will make many LLM calls, and whenever spend looks high. Spend is also a BA KPI source.
---

# Spend Awareness (S7) — work within the LLM cost budget

The homelab's LLM spend is real money with per-key daily limits (Phase 6
spend watch: chuck/dylan $50/day, agent/unknown keys $20/day — breaches alert
to `alerts.log`). This skill is the meta-discipline: **check before you burn,
burn deliberately, checkpoint so a restart doesn't burn twice.**

## Step 1 — check the budget picture (before any long job)

```bash
cd /home/chuck/homelab
python3 agents-skills/spend-awareness/tools/spend_check.py            # 7-day kanban window
python3 agents-skills/spend-awareness/tools/spend_check.py --days 14
```

One JSON object:
- **`keys`** — per-LiteLLM-key `total_usd`, `spend_24h_usd` (Phase 6 rolling
  window, when the watch state exists), and `limit_usd`. A key near its limit
  with a long job ahead = a problem *before* it happens.
- **`kanban_7d`** — the agent org's actual burn: `byOwner` (which agent is
  spending) and `byModel` (which model — `matrix-coder` is the pipeline
  default; `matrix-copywriter` is the strategist/marketing work-type model).

Read it the way a human would:
- An agent key that jumped vs the prior week → find out why before spending
  more (a stuck retry loop is the classic cause — check the board for
  `needs_attention` tasks).
- `spend_24h_usd` near `limit_usd` on a key you're about to use heavily →
  batch or defer; the Phase 6 watch will fire a note/alert if it breaches.

## Step 2 — spend deliberately

- **Batch operations.** One session that does ten lookups beats ten sessions
  that each re-orient (orientation tokens are real spend). Group board reads,
  file reads, and queries into one pass.
- **Cheap model for exploration, good model for the hard parts.** Recon,
  grepping, routine transforms: the small/cheap model. Architecture, the
  novel problem, the QA verdict: the strong model. (Kanban: per-owner models
  already route strategist/marketing work to `matrix-copywriter` — don't
  override it for routine work.)
- **Prefer deterministic tools over LLM turns.** A `docker logs | grep`, a
  SQL query, or a bundled script costs $0. If a fact can be pulled from a
  file, DB, or API, pull it — don't ask the model to remember or derive it.
- **Long tasks: checkpoint durable progress.** Kanban workspaces are swept
  after 7 days; a restart that re-derives completed work burns the budget
  twice. File durable state (reports, decisions, partial artifacts) to the
  repo or a state file as you go — the Phase 10/11/12 deploy runbooks and the
  media-film state-file pattern are the house style.

## Step 3 — report spend with the work

When a task report or board resolution is written, include the spend line if
the job was heavy (many LLM calls, multiple models, or a restart):
`spend: ~$X (Y calls, model Z)` — the `usage` table is the source of truth;
the weekly reviews' spend line and the monthly org review's `byModel` footer
consume it.

## Gotchas

- `/spend/keys` exposes **totals only** — the 24h number is a delta against
  the Phase 6 state file; if that file is missing (watch never ran), the 24h
  field is absent, not zero. Don't read an absent 24h as "no spend today".
- The `usage` table is the kanban org's spend (task/QA sessions) — it does
  NOT cover direct pi sessions or skill-runner jobs. For the whole picture,
  the LiteLLM key totals are the superset.
- Spend alerts (Phase 6) fire at `note` severity during the observation
  window — a note in `alerts.log` is a real signal, not noise to ignore.
