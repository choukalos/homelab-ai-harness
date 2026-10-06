---
name: investment-brief
description: Investment brief — portfolio status, dividend highlights, market news. Configurable per user.
---

# Investment Brief

Investment brief — portfolio status, dividend highlights, market news. Configurable per user.

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
| max_holdings | integer | no | 50 | Max distinct holdings to analyze, aggregated across ALL of the user's portfolios. |
| publish | boolean | no | true | Publish the brief as HTML to the public blog drop zone. |

## Output

- Markdown artifact: `/home/chuck/data/media/investment_briefs/` (latest 3 kept per user).
- Public HTML (when `publish=true`): `https://choukalos.com/files/briefs/investment_brief.html`
  — self-contained page with clickable source links and a link back to
  [InvestorHub](https://invest.choukalos.com). Positions are reported as
  portfolio weight % and P&L % (not dollars or share counts), and the total
  portfolio value is never disclosed (the page is public). Holdings render
  as a table (one row per symbol) grouped by category. The Portfolio Summary
  includes YTD / 1Y / 5Y total return vs the S&P 500 (SPY) and the
  portfolio-wide dividend yield; Action Items appear before the holding
  details and are framed against the user's 60% growth / 30% dividend /
  10% bonds target allocation.

## Example

```
/skill:investment-brief your topic or request here
```
