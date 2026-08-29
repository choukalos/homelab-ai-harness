---
name: research-brief
description: Lightweight web research — generates sub-queries from a topic, searches via SearXNG/MCP, and summarizes findings.
---

# Research Brief

Lightweight web research — generates sub-queries from a topic, searches via SearXNG/MCP, and summarizes findings.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `research_brief`
- `prompt`: the user's request (auto-mapped to the `topic` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~120s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| topic | string | yes | — | The research topic or question to investigate. |
| num_sub_queries | integer | no | 3 | Number of sub-queries to generate (1-5, default 3). |
| max_results_per_query | integer | no | 5 | Maximum search results per sub-query (default 5, cap 10). |
| include_news | boolean | no | False | Also search news sources (default false). |

## Example

```
/skill:research-brief your topic or request here
```
