---
name: investment-brief
description: Investment brief: portfolio status, dividend highlights, market news. Configurable per user.
---

# Investment Brief

Investment brief: portfolio status, dividend highlights, market news. Configurable per user.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `investment_brief`
- `prompt`: the user's request (auto-mapped to the `user_email` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~300s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| user_email | string | no | choukalos@yahoo.com | InvestorHub user email for portfolio lookup. |
| focus | string | no | dividend | Brief focus: dividend (high-yield picks), growth (tech/IPOs), general (balanced overview). |
| max_holdings | integer | no | 20 | Max holdings to analyze from portfolio. |

## Example

```
/skill:investment-brief your topic or request here
```
