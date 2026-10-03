# morning_brief

Daily **new-stories digest** across configurable interest topics.

The skill searches news for each interest topic (freshness-filtered to the
last month), tracks which stories have already been surfaced so nothing is
repeated, fetches each new story's article content, and synthesizes a
per-story digest — a 1–2 paragraph summary, key data points, and a
tap-friendly link to the source article. The report is published as a
self-contained, mobile-friendly HTML page.

## What it does

1. **Search** — `mcp_search.search_news` per interest topic with a
   freshness window (`days=max_age_days`, default 30 → SearXNG `time_range`).
   Only stories published within the window are returned.
2. **Deduplicate** — across topics by normalized URL.
3. **No-repeat** — a persistent seen-store
   (`/home/chuck/data/media/homelab_reports/morning_brief_seen.json`) tracks
   every story already surfaced; seen stories are skipped, and entries are
   pruned after 60 days.
4. **Select** — up to `max_stories` new stories (default 6, hard cap 10),
   round-robin across topics for diversity.
5. **Fetch** — each story's article via `mcp_crawl.crawl_page`
   (best-effort; paywalls/anti-bot fall back to the search snippet).
6. **Synthesize** — LLM (via LiteLLM, `matrix-coder`) writes one section per
   story: `## headline`, `**Source:** [Publisher](url)`, 1–2 paragraph
   summary, `**Key data points:**` bullets (concrete facts only). The LLM
   uses the publisher name provided per story and never writes "unknown"
   when one is given. If the first LLM call returns empty visible content
   (reasoning models can burn the token budget on internal reasoning), the
   call is retried once before falling back to an error report.
7. **Render** — story cards in a self-contained HTML page (embedded CSS,
   dark-mode aware, large "Read the full story →" buttons). Each card shows
   a **publisher badge** (from the search engine's metadata when available,
   else the article's domain with a friendly-name map) and a **date badge**
   (relative, e.g. "3d ago") when the engine reports a publish date.
8. **Publish** — `latest.html` in the public drop zone (single-file
   retention): **https://choukalos.com/files/briefs/latest.html**

## Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `interests` | string | *(config)* | Comma-separated topics; overrides `default_interests` |
| `max_items` | integer | `5` | News items searched per topic |
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
  "categories": ["technology news", "…"],
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