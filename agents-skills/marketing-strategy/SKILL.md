---
name: marketing-strategy
description: "Go-To-Market (GTM) strategy generation — researches the market via mcp_search and synthesizes a full launch plan (TAM/SAM/SOM, competitive landscape, personas, positioning, pricing, channels, 30/60/90 launch plan) as a Markdown artifact."
---

# Marketing Content Strategy / GTM

Takes a product or service brief, researches the market (competitors, trends,
sizing, audience) via the `mcp_search` MCP server, then synthesizes a
comprehensive Go-To-Market strategy via the LLM and saves it as a Markdown
artifact.

Design adapted from `langchain-ai/deepagents` `deploy-gtm-agent`.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `marketing_strategy`
- `prompt`: the product/service brief (auto-mapped to the `prompt` input)
- `params`: (optional) `target_market`, `competitors`, `max_research_queries`

The call blocks until the skill completes (up to its `max_runtime`, ~300s).
If it's still running when the call returns, you get a `job_id` — retrieve it
with the `get_skill_job` MCP tool.

## Inputs

| Input                | Type    | Required | Default | Description                                  |
|----------------------|---------|----------|---------|----------------------------------------------|
| prompt               | string  | yes      | —       | Product or service brief.                    |
| target_market        | string  | no       | —       | Target market/segment to focus on.           |
| competitors          | string  | no       | —       | Comma-separated known competitors.           |
| max_research_queries | integer | no       | 4       | Max market-research web searches (1-8).      |

## Outputs

- `summary` — short executive summary.
- `report` — full GTM strategy in Markdown.
- `artifact_path` — path to the saved `.md` artifact.
- `research_count` — number of unique research sources.

## Strategy sections

Executive Summary · Market Overview (TAM/SAM/SOM) · Competitive Landscape
(comparison table) · Target Audience (personas) · Value Proposition &
Positioning · Pricing Strategy · Channel Strategy · 30/60/90 Launch Plan ·
Risks & Mitigations.

## Example

```
/skill:marketing-strategy AI home energy monitor that optimizes solar output
```