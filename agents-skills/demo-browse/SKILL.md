---
name: demo-browse
description: Scan demos directory and keyword-match demos by title, description, and tags.
---

# Demo Browse

Scan demos directory and keyword-match demos by title, description, and tags.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `demo_browse`
- `prompt`: the user's request (auto-mapped to the `query` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~30s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| query | string | yes | — | Search keywords to match against demo titles, descriptions, and tags. |
| demo_dir | string | no | — | Root demos directory to scan. Defaults to /home/chuck/data/media/demos/. |
| limit | integer | no | — | Maximum number of results to return. Defaults to 20. |

## Example

```
/skill:demo-browse your topic or request here
```
