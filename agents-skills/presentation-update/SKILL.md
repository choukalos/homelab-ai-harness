---
name: presentation-update
description: Update an existing presentation by title using natural-language instructions
---

# Presentation Update

Update an existing presentation by title using natural-language instructions

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `presentation_update`
- `prompt`: the user's request (auto-mapped to the `presentation_title` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~300s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| presentation_title | string | yes | — | Title (or partial title) of the presentation to update. |
| instructions | string | yes | — | Natural-language update instructions (e.g. 'make it more casual and add 3 slides'). |

## Example

```
/skill:presentation-update your topic or request here
```
