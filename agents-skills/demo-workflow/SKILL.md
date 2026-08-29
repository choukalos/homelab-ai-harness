---
name: demo-workflow
description: One-page clickable demo via deep agents. Takes a prompt, researches, builds, and verifies an interactive HTML demo.
---

# Demo Workflow

One-page clickable demo via deep agents. Takes a prompt, researches, builds, and verifies an interactive HTML demo.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `demo_workflow`
- `prompt`: the user's request (auto-mapped to the `prompt` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~600s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| prompt | string | yes | — | The demo topic/description. |

## Example

```
/skill:demo-workflow your topic or request here
```
