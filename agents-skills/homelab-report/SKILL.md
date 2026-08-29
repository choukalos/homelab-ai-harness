---
name: homelab-report
description: Generate a homelab infrastructure health report. Checks Docker containers, system resources, and service status.
---

# Homelab Report

Generate a homelab infrastructure health report. Checks Docker containers, system resources, and service status.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `homelab_report`
- `prompt`: the user's request (auto-mapped to the `scope` input)
- `params`: (optional) explicit input values — overrides `prompt` when provided

The call blocks until the skill completes (up to its `max_runtime`, ~120s). If it's still running when the call returns, you get a `job_id` — retrieve it with the `get_skill_job` MCP tool.

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| scope | string | no | full | Report scope: full (all), containers (Docker only), system (CPU/RAM/disk only). |

## Example

```
/skill:homelab-report your topic or request here
```
