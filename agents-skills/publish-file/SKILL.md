---
name: publish-file
description: Publish a file from an approved source root to the blog's public drop zone (/home/chuck/data/media/public), served at https://choukalos.com/files/. Validated, atomic, size-capped.
---

# Publish File

Publish a file from an approved source root to the blog's public drop zone (/home/chuck/data/media/public), served at https://choukalos.com/files/. Validated, atomic, size-capped.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `publish_file`
- `prompt`: the user's request (auto-mapped to the `source_path` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~60s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| source_path | string | yes | — | Absolute path to the file to publish (must be under /home/chuck/data/media/ or /home/chuck/workspace/). |
| destination_name | string | no | — | Optional target filename (defaults to the source basename). |
| subdirectory | string | no | ai | Drop-zone subdirectory to publish into. |
| overwrite | boolean | no | False | Replace an existing file with the same name (default: fail on collision). |

## Example

```
/skill:publish-file your topic or request here
```
