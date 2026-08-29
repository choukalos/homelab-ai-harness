---
name: siri-chat
description: Conversational chat with web search, knowledge base, and homelab status tools
---

# Siri Chat

Conversational chat with web search, knowledge base, and homelab status tools

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `siri_chat`
- `prompt`: the user's request (auto-mapped to the `query` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~120s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| query | string | yes | — | The user's question or request. |
| context | string | no | — | Optional previous conversation context for continuity. |
| model | string | no | matrix-coder | Model alias to use (default: matrix-coder). |

## Example

```
/skill:siri-chat your topic or request here
```
