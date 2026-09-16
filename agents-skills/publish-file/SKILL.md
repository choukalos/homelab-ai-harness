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
| subdirectory | string | no | ai | Drop-zone subdirectory to publish into. One of: `ai`, `images`, `audio`, `video`. **Never `files`** — the drop zone is already served at `/files/`, so it would produce a `/files/files/...` URL. |
| overwrite | boolean | no | False | Replace an existing file with the same name (default: fail on collision). |

## URL formula

The final URL is always `https://choukalos.com/files/{subdirectory}/{name}` — the subdirectory is appended to the `/files/` base, it is not the base itself.

| subdirectory | Resulting URL |
|---|---|
| `ai` (default) | `https://choukalos.com/files/ai/<name>` |
| `images` | `https://choukalos.com/files/images/<name>` |
| `audio` | `https://choukalos.com/files/audio/<name>` |
| `video` | `https://choukalos.com/files/video/<name>` |

## Example

```
/skill:publish-file your topic or request here
```
