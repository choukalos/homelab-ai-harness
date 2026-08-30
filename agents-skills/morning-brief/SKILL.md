---
name: morning-brief
description: Daily morning brief — news across configurable interest topics, synthesized into a short-and-sweet bullet-point summary.
---

# Morning Brief

Daily morning brief — news across configurable interest topics, synthesized into a short-and-sweet bullet-point summary.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `morning_brief`
- `prompt`: the user's request (auto-mapped to the `interests` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~180s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| interests | string | no | — | Comma-separated list of interest topics. Overrides default_interests if provided. |
| max_items | integer | no | 5 | Maximum number of news items per interest category. |

## Example

```
/skill:morning-brief your topic or request here
```
