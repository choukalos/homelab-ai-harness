# market_research_brief

Generic **market research brief** engine, driven by market profiles.

For a market profile (`profiles/<market>.yml`) it gathers, all through
LiteLLM (never direct MCP access):

1. **Per-competitor news** for the last `period_days` (default 30) —
   `mcp_search.search_news`, freshness-filtered; a competitor may declare
   alternate search terms (e.g. a rebrand).
2. **Seed queries** — broad market-level news sweep defined by the profile.
3. **Market size & share** — `mcp_search.search_web` (free sources only).
4. **Owner context** — long-term memory (`memory.jobctx`, Phase 7) + family
   KB (`mcp_knowledge.kb_search`). Both non-fatal; scheduled runs (service
   identity) get no personal memory.

An LLM (default alias `matrix-coder`) synthesizes a structured brief —
executive summary, market size & share, per-competitor scan (last month's
moves + one-line trend), analyst watch, trends & outlook — with strict
rules: only facts from the provided material, inline `[Publisher](url)`
citations with exact URLs, "no significant news" stated explicitly when a
competitor has none, and paywalled analyst figures flagged (never
fabricated).

## Retention & cadence

- **Artifacts kept**: timestamped `.md` + `.html` in
  `/home/chuck/data/media/market_research_briefs/` (no pruning) so a few
  years of monthly briefs accumulate for trend analysis.
- **Yearly summary**: on the run whose UTC month == the profile's
  `yearly_month` (default 1), the last `yearly_min_briefs` (default 12)
  distinct monthly briefs are synthesized into a yearly summary
  (`.md` + `.html` artifacts, published when `publish: true`).

## Publishing (`publish: true`)

- **Latest**: `<public>/briefs/<slug>.html` (overwritten each run).
- **Dated**: `<public>/briefs/market_research/<slug>_YYYY-MM.html` — last
  `DATED_RETENTION` (default 3) copies retained per market.
- **Yearly**: `<public>/briefs/<slug>_yearly_<label>.html` (all retained).

Public root: `/home/chuck/data/media/public` →
`https://choukalos.com/files/`.

## Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `market` | string | *(required)* | Profile name under `profiles/` |
| `period_days` | integer | `30` | Lookback window (7–365) |
| `max_items` | integer | `5` | Max items per query (hard cap 10) |
| `publish` | boolean | `false` | Publish to the blog drop zone |
| `publish_path` | string | `<public>/briefs/<slug>.html` | Override the "latest" path |

## Output

```json
{
  "summary": "…",
  "report": "<markdown brief>",
  "artifact_path": "…/market_research_brief_<market>_<ts>.md",
  "html_artifact_path": "…/market_research_brief_<market>_<ts>.html",
  "published_path": "…/public/briefs/<slug>.html",
  "published_url": "https://choukalos.com/files/briefs/<slug>.html",
  "dated_publish_path": "…/public/briefs/market_research/<slug>_YYYY-MM.html",
  "dated_publish_url": "https://choukalos.com/files/briefs/market_research/<slug>_YYYY-MM.html",
  "yearly": null,
  "market": "<market>",
  "period_days": 30,
  "competitors_scanned": 11,
  "competitors_with_news": 3,
  "items_found": 15,
  "memory_used": false,
  "kb_used": false
}
```

`yearly` is `{label, months, artifact_path, html_artifact_path,
published_path, published_url}` when a yearly summary was generated.

## Adding a market

Drop a profile file in `profiles/` — no code changes:

```yaml
market: my_market
title: "My Market"
description: "…"
segments:
  - id: core
    label: "Core"
    competitors: [Acme, Beta]          # or {name, search: [...], note}
  - id: up_and_comers
    label: "Up-and-Comers"
    competitors: [Gamma]
analyst_firms:
  - name: "Some Analyst Firm"
    note: "Most data paywalled — use free coverage."
seed_queries:
  - "my market news"
market_size_queries:
  - "my market market size"
yearly_month: 1
yearly_min_briefs: 12
publish:
  slug: my_market_brief
```

## Constraints

- **Max runtime: 600 s.**
- **Free sources only** — paywalled analyst data is flagged, never
  fabricated.
- **Artifacts**: `/home/chuck/data/media/market_research_briefs/`.

## CLI (standalone)

```bash
python3 skill.py --dry-run
python3 skill.py --market smarthome_homesecurity --period-days 30
python3 skill.py --market smarthome_homesecurity --publish
```

## Files

- `skill.py` — engine (stdlib only; markdown→HTML renderer included)
- `skill.yml` — manifest
- `profiles/` — market profiles
- `README.md` — this file