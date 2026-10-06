---
name: market-research-brief
description: Generic market research brief engine — competitor scan (last month's moves + trend), market size & share, analyst watch, outlook. Driven by market profiles (skills/market_research_brief/profiles/); artifacts retained for multi-year trends, yearly summary on the January run. Free sources only.
---

# Market Research Brief

Generic market research brief engine. For a **market profile** it gathers
per-competitor news for the last N days (default 30), broad market-level
news, market-size/share web findings (free sources only), and owner context
(long-term memory + family KB), then synthesizes a structured brief:

1. **Executive Summary** — the period's most important developments
2. **Market Size & Share** — size, growth, competitive share where
   identifiable; paywalled analyst figures are flagged, never fabricated
3. **Competitor Scan** — per competitor: "last month" moves (with source
   links) + a one-line trend
4. **Analyst Watch** — activity from the profile's analyst firms
5. **Trends & Outlook** — cross-competitor trends, what to watch next

Rendered as a self-contained mobile-friendly HTML page.

**Market profiles** live in `skills/market_research_brief/profiles/`
(`<market>.yml`): market title/description, segments + competitors (with
optional alternate search terms and notes), analyst firms, seed queries,
market-size queries, publish slug, yearly-summary settings. To add a new
market, drop a new profile file — no code changes needed.

**Cadence & retention:** monthly cadence is driven by the scheduler (see
the specialty subskills). Timestamped artifacts (`.md` + `.html`) are
**kept** (no pruning) so a few years of briefs accumulate for trend
analysis. On the January run, a **yearly summary** is synthesized from the
last 12 distinct monthly briefs (needs ≥12; label is the covered year(s)).

**Publishing** (`publish: true`): latest file overwrites
`https://choukalos.com/files/briefs/<slug>.html`; a dated copy is published
to `https://choukalos.com/files/briefs/market_research/<slug>_YYYY-MM.html`
(last 3 dated copies retained per market); yearly summaries publish to
`https://choukalos.com/files/briefs/<slug>_yearly_<label>.html` (all
retained).

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `market_research_brief`
- `params`: `{ "market": "<profile name>", "publish": true }`

The call blocks until the skill completes (up to its `max_runtime`, ~600s).
If it's still running when the call returns, you get a `job_id` — retrieve
it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| market | string | **yes** | — | Market profile name (a file under `profiles/`) |
| period_days | integer | no | 30 | Lookback window in days (7–365) |
| max_items | integer | no | 5 | Max news items per query (hard cap 10) |
| publish | boolean | no | false | Publish the HTML brief to the blog drop zone |
| publish_path | string | no | `…/public/briefs/<slug>.html` | Override the published "latest" file path |

## Output

Result keys: `summary`, `report` (markdown), `artifact_path` (`.md`),
`html_artifact_path` (`.html`), `published_path`, `published_url`,
`dated_publish_path`, `dated_publish_url`, `yearly` (label, months,
artifact + publish paths, or null), `market`, `period_days`,
`competitors_scanned`, `competitors_with_news`, `items_found`,
`memory_used`, `kb_used`.

## Specialty subskills

- [smarthome-homesecurity-brief](../smarthome-homesecurity-brief/SKILL.md)
  — pins the `smarthome_homesecurity` profile (Smart Home & Home Security),
  runs monthly, publishes `smarthome_homesecurity_brief.html`.

## Constraints

- **Max runtime: 600 s** (multi-query research + LLM synthesis + publish).
- **All MCP calls go through LiteLLM** — never direct MCP server access.
- **Free sources only**: paywalled analyst data (e.g. Parks Associates,
  Gartner) is referenced via free press coverage and explicitly flagged —
  never fabricated.
- **Artifacts**: `/home/chuck/data/media/market_research_briefs/` (kept).
- **Public output**: `/home/chuck/data/media/public/briefs/` (latest
  overwritten; last 3 dated copies; yearly summaries retained).