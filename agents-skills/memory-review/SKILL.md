---
name: memory-review
description: Weekly memory review digest — lists the caller's new/updated private + household memories (with IDs + dates) so the user can correct or delete anything wrong. Private artifact, never published.
---

# Memory Review

Weekly memory review digest — lists the caller's new/updated private + household memories (with IDs + dates) so the user can correct or delete anything wrong. Private artifact, never published.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `memory_review`
- `params`: (optional) `{"user": "chuck", "days": 7, "limit": 50}`

Omit `user` for interactive runs (uses the caller's own identity). The job blocks up to 120s and returns the digest as the artifact.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| user | string | no | caller | User to review (scheduled runs must set it) |
| days | integer | no | 7 | Window in days of new/updated memories |
| limit | integer | no | 50 | Max memories to fetch (private + household merged) |

## Example

/skill:memory-review review my memories from the last 7 days