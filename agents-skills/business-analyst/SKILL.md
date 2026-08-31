---
name: business-analyst
description: "Business/product data analyst — answers natural-language questions against MySQL (mcp_mysql): translates the question to SQL, executes it, synthesizes insights (key takeaways, interpretation, follow-ups, Grafana suggestions) and produces a Markdown report with the SQL and results."
---

# Business / Product Analyst

Answers natural-language questions against the existing MySQL databases by
translating the question to SQL, executing it, and synthesizing insights via
the LLM. Produces a Markdown report with the SQL, results, key insights,
follow-up suggestions, and suggested Grafana queries.

Uses the existing databases **as-is** — no new schema is designed.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `business_analyst`
- `prompt`: the natural-language question (auto-mapped to the `prompt` input)
- `params`: (optional) `database`

The call blocks until the skill completes (up to its `max_runtime`, ~300s).
If it's still running when the call returns, you get a `job_id` — retrieve it
with the `get_skill_job` MCP tool.

## Inputs

| Input    | Type   | Required | Default   | Description                              |
|----------|--------|----------|-----------|------------------------------------------|
| prompt   | string | yes      | —         | Natural-language question to answer.     |
| database | string | no       | auto-detect | Target DB (`investorhub`, `homelab`). |

## Available databases

- **investorhub** — financial data (stocks, portfolios, dividends, index
  membership, price history, fundamentals, returns).
- **homelab** — operational data (skill jobs, workflows, workflow runs,
  checkpoints).

## Outputs

- `summary` — short summary of the analysis.
- `report` — full analysis report in Markdown.
- `sql` — the SQL that was executed.
- `row_count` — number of result rows.
- `rows` — result rows (capped at 50).
- `database` — the database queried.
- `query_method` — which mcp_mysql method produced the data.
- `query_error` — query error, if any.
- `artifact_path` — path to the saved `.md` artifact.

## Report sections

Query (SQL) · Results (table) · Key Insights · Interpretation · Suggested
Follow-ups · Grafana Suggestions.

## Example

```
/skill:business-analyst What are the top 5 stocks by market cap?
```