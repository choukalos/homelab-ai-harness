---
name: smarthome-homesecurity-brief
description: Monthly market research brief for the Smart Home & Home Security market — competitor scan (Ring, SimpliSafe, ADT, Brinks, Xfinity Home, Xfinity Shield, Nest, Arlo + up-and-comers Wyze/Eufy/Blink), market size & share, Parks Associates / Gartner watch, outlook.
---

# Smart Home & Home Security Brief

Monthly market research brief for the **Smart Home & Home Security** market.
This is the specialty subskill for that market: a thin wrapper around the
generic `market_research_brief` engine that pins the
`smarthome_homesecurity` profile.

**Market profile** (`skills/market_research_brief/profiles/smarthome_homesecurity.yml`):

- **Home Security** — Ring, SimpliSafe, ADT, Brinks, Xfinity Home
- **Smart Home** — Xfinity Shield (formerly Xfinity Smart Home), Nest, Arlo
- **Up-and-Comers** — Wyze, Eufy, Blink
- **Analyst firms** — Parks Associates (leading smart home / home security
  analyst firm) and Gartner; most of their data is paywalled, so the brief
  uses free press coverage only and flags paywalled figures.
- **Seed queries** — the home-security interests that used to live in the
  daily morning brief (moved here 2026-10-05).

**What it does** (per run, last 30 days by default): per-competitor news
scan with a "last month's moves" + trend line per competitor, market size &
share findings (free sources only), analyst watch, trends & outlook.
Synthesized via LLM, rendered as a self-contained mobile-friendly HTML page.

**Cadence & publishing:** scheduled monthly (`0 9 1 * *`, America/Chicago).
With `publish: true` it publishes to the blog:

- Latest: **https://choukalos.com/files/briefs/smarthome_homesecurity_brief.html**
  (overwritten each run)
- Dated: `https://choukalos.com/files/briefs/market_research/smarthome_homesecurity_brief_YYYY-MM.html`
  (last 3 dated copies retained)
- Yearly summary (January run, from the last 12 monthly briefs):
  `https://choukalos.com/files/briefs/smarthome_homesecurity_brief_yearly_<label>.html`

All monthly artifacts (`.md` + `.html`) are retained on disk
(`/home/chuck/data/media/market_research_briefs/`) for multi-year trend
tracking.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `smarthome_homesecurity_brief`
- `params`: `{ "publish": true }` (optional; defaults to true in the manifest)

The call blocks until the skill completes (up to its `max_runtime`, ~600s).
If it's still running when the call returns, you get a `job_id` — retrieve
it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| period_days | integer | no | 30 | Lookback window in days for the competitor scan and market data |
| max_items | integer | no | 5 | Max news items collected per query (hard cap 10) |
| publish | boolean | no | true | Publish the HTML brief to the blog drop zone |
| publish_path | string | no | `…/public/briefs/smarthome_homesecurity_brief.html` | Override the published "latest" file path |

## Output

Same result keys as `market_research_brief` (see
[market-research-brief](../market-research-brief/SKILL.md)).

## Schedule

`monthly-smarthome-homesecurity-brief` — `0 9 1 * *` (America/Chicago),
`publish: true`.