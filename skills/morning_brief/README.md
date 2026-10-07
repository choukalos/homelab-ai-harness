# morning_brief

Daily **new-stories digest** balanced across the user's interest areas:
**AI**, **Tech (non-AI)**, and **Cars** (sports-car / manual-transmission
reviews).

The skill searches news per interest area (freshness-filtered to the last
month), tracks which stories have already been surfaced so nothing is
repeated, fetches each new story's article content, and synthesizes a
per-story digest — a 1–2 paragraph summary, key data points, and a
tap-friendly link to the source article. The report is published as a
self-contained, mobile-friendly HTML page.

## Default interest areas

| Area | Search queries | Relevance filter |
|---|---|---|
| **AI** | `artificial intelligence news` | — |
| **Tech** | `technology news` | AI-leaning stories excluded (the AI area covers them) |
| **Cars** | `sports car reviews`, `manual transmission car review` | accident/incident/crime stories excluded (no crash reports) |

Selection round-robins across **areas** (not queries), so each area gets an
even share of the digest. An explicit `interests` input overrides the
defaults — each topic becomes its own unfiltered area.

## What it does

1. **Search** — `mcp_search.search_news` per area query with a freshness
   window (`days=max_age_days`, default 30 → SearXNG `time_range`). Only
   stories published within the window are returned. SearXNG news is flaky
   (identical queries can return 0 results and then succeed seconds later),
   so empty results are retried (3 attempts). Per-area relevance filters
   drop off-topic items (e.g. crash reports under Cars, AI stories under
   Tech).
2. **Deduplicate** — across areas by normalized URL.
3. **No-repeat** — a persistent seen-store
   (`/home/chuck/data/media/homelab_reports/morning_brief_seen.json`) tracks
   every story already surfaced; seen stories are skipped, and entries are
   pruned after 60 days.
4. **Select** — up to `max_stories` + 2 buffer NEW candidates (hard cap 10),
   round-robin across interest areas for balance; an area's queries are
   alternated for diversity.
5. **Fetch** — each candidate's article via `mcp_crawl.crawl_page`
   (best-effort; paywalls/anti-bot fall back to the search snippet).
6. **Quality gate** — when the crawler is working (at least one fetch
   succeeded), candidates from aggregator/portal sites (MSN, Yahoo, AOL)
   whose article could not be fetched are dropped: those pages are
   ad-cluttered and a snippet-only card with a junky link is worse than no
   card. Dropped candidates stay eligible for the next run. If the crawler
   is down (zero fetches succeeded) everything is kept with snippet
   fallback. Truncate to `max_stories`.
7. **Synthesize** — LLM (via LiteLLM, `matrix-coder`) writes one section per
   story: `## headline`, `**Source:** [Publisher](url)`, 1–2 paragraph
   summary, `**Key data points:**` bullets (concrete facts only). The LLM
   uses the publisher name provided per story and never writes "unknown"
   when one is given. If the first LLM call returns empty visible content
   (reasoning models can burn the token budget on internal reasoning), the
   call is retried once before falling back to an error report.
8. **Render** — story cards in a self-contained HTML page (embedded CSS,
   dark-mode aware, large "Read the full story →" buttons). Each card shows
   a **publisher badge** (from the search engine's metadata when available,
   else the article's domain with a friendly-name map) and a **date badge**
   (relative, e.g. "3d ago") when the engine reports a publish date.
9. **Publish** — `latest.html` in the public drop zone (single-file
   retention): **https://choukalos.com/files/briefs/latest.html**

## Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `interests` | string | *(areas)* | Comma-separated topics; overrides the default interest areas (AI / Tech / Cars) |
| `max_items` | integer | `6` | News items searched per area query |
| `max_age_days` | integer | `30` | Freshness window — only stories from the last N days |
| `max_stories` | integer | `6` | Max new stories surfaced (hard cap 10) |
| `publish` | boolean | `false` | Publish the HTML digest to the public drop zone |
| `publish_path` | string | `…/public/briefs/latest.html` | Publish destination |

## Output

```json
{
  "summary": "6 new stories: <first headline>",
  "report": "<markdown digest>",
  "artifact_path": "/home/chuck/data/media/homelab_reports/morning_brief_<ts>.md",
  "html_artifact_path": "/home/chuck/data/media/homelab_reports/morning_brief_<ts>.html",
  "published_path": "/home/chuck/data/media/public/briefs/latest.html",
  "published_url": "https://choukalos.com/files/briefs/latest.html",
  "categories": ["AI", "Tech", "Cars"],
  "item_count": 14,
  "stories_surfaced": 6,
  "stories_skipped_seen": 3,
  "max_age_days": 30
}
```

## Constraints

- **Max runtime: 300 s** (search + crawl + LLM + publish).
- **All MCP calls go through LiteLLM** — never direct MCP server access.
- **Freshness**: stories must be from the last `max_age_days` (default 30).
- **No-repeat**: surfaced stories are tracked in the seen-store and not
  resurfaced (retention 60 days). Stories are only marked seen when the
  digest actually rendered them — a broken run leaves them eligible for
  resurfacing.
- **Search metadata**: `mcp_search.search_news` returns `source` (publisher
  from engine metadata or domain fallback) and `published_date` (ISO date
  when the engine reports one) per result.
- **Artifacts**: `/home/chuck/data/media/homelab_reports/` (`.md` raw + `.html` rendered).
- **Public output**: single-file retention — `latest.html` is overwritten each run.

## Schedule

`weekday-morning-brief` — `0 9 * * 1-5` (America/Chicago), `publish: true`.

## CLI (standalone)

```bash
# Show resolved config
python3 skill.py --dry-run

# Test run (no publish)
python3 skill.py --interests "technology news" --max-stories 3

# Test run with publish to a scratch path
python3 skill.py --interests "technology news" --max-stories 3 \
  --publish --publish-path /tmp/mb_test.html
```

## Files

- `skill.py` — implementation (stdlib only; markdown→HTML renderer included)
- `skill.yml` — manifest (inputs, tools, defaults)
- `README.md` — this file