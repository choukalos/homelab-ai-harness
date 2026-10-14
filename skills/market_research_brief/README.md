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

## Annual reference (competitor comparison + market context)

Profiles may carry a `reference:` block (per-market aspect set, sources,
share-indicator sources, market-size queries). Markets with one get an
**annual reference dataset** — `references/<market>.json`, git-tracked and
hand-editable:

- **Market size & growth** — 2–4 independent free estimates (range +
  per-estimate source/CAGR/horizon) and sourced context bullets.
- **Share indicators** — revenue for public companies (SEC EDGAR / IR),
  labeled proxies for private ones (`survey_share`, `pr_estimate`,
  `install_base`, `other`), each with source + as-of.
- **Competitor comparison** — per-market facts (pricing, features, …) with
  per-field source URL + as-of, LLM rubric ratings (1–5, one-line
  rationale) on the market's rating aspects, and free review-site scores
  (selected set) shown alongside — never averaged into the rubric.

The dataset is built by `reference.py` (crawl vendor/comparison sources →
per-competitor LLM extraction → market-size consolidation → merge into the
JSON; crawl cache `references/<market>.crawls.json`, 24 h freshness):

```bash
python3 reference.py --market <market> [--force] [--retry A,B] \
    [--retry-market] [--populate-cache] [--render-only]
```

Integration:

- **Monthly brief** embeds a **compact** reference section (deterministic
  Python render from the JSON — no LLM, no drift): market-size range, share
  bar chart, top-aspects table + rubric scores. Rendered from the JSON,
  spliced into the HTML before the footer and appended to the `.md`
  artifact as a markdown table. If the reference is older than the
  profile's `stale_after_days` (default 365), a one-line "last updated"
  note is shown.
- **Yearly summary** (January) embeds the **full** reference (detail table
  + ratings heatmap) plus a deterministic year-over-year diff (price /
  feature / share / rating changes) when the prior-year JSON exists.
- **Standalone page**: every published run refreshes
  `<public>/briefs/market_research/<market>_reference.html` (full render),
  shareable independently of the monthly brief.
- **January rebuild**: the `market_research_reference` skill (separate
  scheduler job, 5400 s budget) rebuilds the reference + republishes the
  standalone page before the monthly briefs run. The engine's
  `build_reference: true` input also rebuilds when stale (fits the budget
  only with a warm crawl cache).

## Retention & cadence

- **Artifacts kept**: timestamped `.md` + `.html` in
  `/home/chuck/data/media/market_research_briefs/` (no pruning) so a few
  years of monthly briefs accumulate for trend analysis.
- **Yearly summary**: on the run whose UTC month == the profile's
  `yearly_month` (default 1), the last `yearly_min_briefs` (default 12)
  distinct monthly briefs are synthesized into a yearly summary
  (`.md` + `.html` artifacts, published when `publish: true`).

## Annual reference (competitor comparison)

Profiles may carry a `reference:` block (per-market aspect set, source
list, share-indicator sources, market-size queries). For those markets an
**annual reference dataset** lives at `references/<market>.json` —
competitor comparison facts (each with source URL + as-of date), LLM
rubric ratings (1–5 per aspect), review-site scores, market-size
estimates (2–4 independent free sources, shown as a range), and
share indicators (revenue for public companies; labeled proxies for
private ones). The JSON is git-tracked, human-editable, and diffable —
the yearly diff is a plain JSON diff.

- **Build**: `python3 reference.py --market <market>` (crawl vendor /
  comparison / review pages via LiteLLM `mcp_crawl`, LLM extraction per
  competitor, market-size consolidation). ~15–30 min, so it runs as its
  own scheduled job (`market_research_reference` skill) in January,
  before the monthly brief. CLI ops: `--force`, `--retry <names>`,
  `--retry-market`, `--populate-cache`, `--render-only`.
- **Monthly brief**: embeds a **compact** deterministic section
  (market-size range, share bar chart, top-aspects table, rubric scores)
  rendered from the JSON — no LLM, no drift. If the JSON is missing the
  section is omitted; if older than `stale_after_days` (default 365) a
  one-line "last updated" note is shown.
- **Yearly summary**: embeds the **full** reference + a year-over-year
  diff (price/share changes, feature adds/drops, rating deltas) computed
  deterministically from the current + prior-year JSON.
- **`build_reference: true`** input: builds/refreshes the reference first
  (January runs; only refreshes when stale, and a full build may exceed
  the 600 s brief budget — the standalone `market_research_reference`
  job is the primary path).
- **Publishing**: standalone page
  `<public>/briefs/market_research/<market>_reference.html` (kept fresh by
  every published run; overwritten each build).

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
| `build_reference` | boolean | `false` | Rebuild the annual reference first (January runs) |

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
- `reference.py` — annual reference build + deterministic HTML/MD renderer
- `skill.yml` — manifest
- `profiles/` — market profiles (`reference:` block optional)
- `references/<market>.json` — annual reference datasets (git-tracked;
  `*.crawls.json` 24 h crawl cache is git-ignored)
- `README.md` — this file