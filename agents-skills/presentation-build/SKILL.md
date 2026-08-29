---
name: presentation-build
description: Generate presentations from a topic or existing content using Presenton
---

# Presentation Build

Generate presentations from a topic or existing content using Presenton

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `presentation_build`
- `prompt`: the user's request (auto-mapped to the `topic` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~300s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| topic | string | yes | — | The presentation topic or title. |
| slide_count | integer | no | 8 | Number of slides to generate (1-50). |
| style | string | no | modern | Presentation style/theme (modern, minimal, bold, elegant). |
| content_source | string | no | — | Path to an existing artifact file or raw text to use as content source for the presentation. |

## Example

```
/skill:presentation-build your topic or request here
```
