---
name: siri-ask
description: Quick Q&A for Siri/iOS Shortcuts. Short answers, no heavy research.
---

# Siri Ask

Quick Q&A for Siri/iOS Shortcuts. Short answers, no heavy research.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `siri_ask`
- `prompt`: the user's request (auto-mapped to the `query` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~30s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| query | string | yes | — | The question or request to answer. |
| context | string | no | — | Optional previous conversation context for continuity. |

## Example

```
/skill:siri-ask your topic or request here
```
