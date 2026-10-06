# smarthome_homesecurity_brief

Monthly market research brief for the **Smart Home & Home Security**
market — the specialty subskill for that market.

Thin wrapper around the generic [market_research_brief](../market_research_brief/)
engine: it pins the `smarthome_homesecurity` profile and delegates
everything else (research, synthesis, HTML rendering, retention,
publishing, yearly summary) to the engine.

**Market profile**
(`../market_research_brief/profiles/smarthome_homesecurity.yml`):

- **Home Security** — Ring, SimpliSafe, ADT, Brinks, Xfinity Home
- **Smart Home** — Xfinity Shield (formerly Xfinity Smart Home), Nest, Arlo
- **Up-and-Comers** — Wyze, Eufy, Blink
- **Analyst firms** — Parks Associates (leading smart home / home security
  analyst firm), Gartner; most data is paywalled → free press coverage only,
  paywalled figures flagged.
- **Seed queries** — the home-security interests that used to live in the
  daily morning brief (moved here 2026-10-05).

**Cadence:** scheduled monthly — `monthly-smarthome-homesecurity-brief`,
`0 9 1 * *` (America/Chicago), `publish: true`.

**Publishing** (`publish: true`):

- Latest: **https://choukalos.com/files/briefs/smarthome_homesecurity_brief.html**
  (overwritten each run)
- Dated: `https://choukalos.com/files/briefs/market_research/smarthome_homesecurity_brief_YYYY-MM.html`
  (last 3 dated copies retained)
- Yearly (January run, last 12 monthly briefs):
  `https://choukalos.com/files/briefs/smarthome_homesecurity_brief_yearly_<label>.html`

**Artifacts** (kept, multi-year):
`/home/chuck/data/media/market_research_briefs/market_research_brief_smarthome_homesecurity_*.md|.html`

## Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `period_days` | integer | `30` | Lookback window (7–365) |
| `max_items` | integer | `5` | Max items per query (hard cap 10) |
| `publish` | boolean | `true` | Publish to the blog drop zone |
| `publish_path` | string | `…/public/briefs/smarthome_homesecurity_brief.html` | Override the "latest" path |

## CLI (standalone)

```bash
python3 skill.py --dry-run
python3 skill.py --period-days 30 --max-items 5
python3 skill.py --publish
```