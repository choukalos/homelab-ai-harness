---
name: deep-research
description: Multi-source deep research with citation and artifact generation
---

# Deep Research

Multi-source deep research with citation and artifact generation

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `deep_research`
- `prompt`: the user's request (auto-mapped to the `query` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~900s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| query | string | yes | — | The research topic or question to investigate. |
| depth | string | no | comprehensive | Research depth — quick (few sources), comprehensive (default), or exhaustive (max depth). |
| max_sources | integer | no | 10 | Maximum number of sources to consult. |

## Example

```
/skill:deep-research your topic or request here
```
