---
name: morning-brief
description: Daily new-stories digest — freshness-filtered news (last month) balanced across AI, tech (non-AI), and sports-car/manual-transmission car reviews; no-repeat via seen-store, per-story summaries with key data points, published as tap-friendly HTML.
---

# Morning Brief

Daily new-stories digest — freshness-filtered news (last month) balanced
across the user's interest areas, no-repeat via seen-store, per-story
summaries with key data points, published as tap-friendly HTML.

The skill searches news per interest area restricted to the last
`max_age_days` (default 30), skips stories already surfaced in a previous
digest (persistent seen-store), fetches each new story's article content,
and synthesizes a per-story digest — a 1–2 paragraph summary plus key data
points. The report is rendered as a self-contained, mobile-friendly HTML
page with large tap-friendly links to each source article and (when
`publish: true`) published to
https://choukalos.com/files/briefs/latest.html (single-file retention).

## Default interest areas

| Area | Search queries | Relevance filter |
|---|---|---|
| **AI** | `artificial intelligence news` | — |
| **Tech** | `technology news` | AI-leaning stories excluded (the AI area covers them) |
| **Cars** | `sports car reviews`, `manual transmission car review` | accident/incident/crime stories excluded (no crash reports) |

Selection round-robins across **areas** (not queries) so each area gets an
even share of the digest. Candidates from aggregator/portal sites (MSN,
Yahoo, AOL) whose article could not be fetched are dropped when the crawler
is working (a snippet-only card with a junky link is worse than no card);
dropped candidates stay eligible for the next run. An explicit `interests`
input overrides the defaults — each topic becomes its own unfiltered area.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `morning_brief`
- `prompt`: the user's request (auto-mapped to the `interests` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~300s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| interests | string | no | — | Comma-separated list of interest topics. Overrides the default interest areas (AI / Tech / Cars) if provided. |
| max_items | integer | no | 6 | Maximum number of news items searched per interest query. |
| max_age_days | integer | no | 30 | Freshness window — only stories published within the last N days. |
| max_stories | integer | no | 6 | Maximum number of NEW stories to surface in the digest (hard cap 10). |
| publish | boolean | no | false | Also publish the HTML digest to the public drop zone (overwrites the target). |
| publish_path | string | no | /home/chuck/data/media/public/briefs/latest.html | Destination file for the published HTML digest. |

## Output

Result keys: `summary`, `report` (markdown digest), `artifact_path`
(`.md`), `html_artifact_path` (`.html`), `published_path`, `published_url`,
`categories`, `item_count`, `stories_surfaced`, `stories_skipped_seen`,
`max_age_days`.

## Example

```
/skill:morning-brief your topic or request here
```