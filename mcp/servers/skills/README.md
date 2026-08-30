# mcp_skills

MCP server that exposes the family **skills/agents** to any MCP client through
a tiny "tool gateway" — three always-on tools instead of one per skill, so the
context footprint stays negligible as the skill count grows.

## Tools

| Tool | Description |
|---|---|
| `list_skills()` | List all skills: `name`, `description`, `version`, `model_alias`, `max_runtime`, `channels`, `inputs`. |
| `run_skill(name, prompt?, params?, max_wait?)` | Run a skill by name. `prompt` (short natural-language) is mapped to the skill's primary string input (well-known names → required string → first string); `params` (explicit input dict) wins. `max_wait` defaults to the skill's `max_runtime` (else `SKILL_RUNNER_TIMEOUT`, 180s); httpx timeout = `max_wait + 30`. Blocks until the job finishes (up to `max_wait`) and returns the job (`job_id`, `status`, `summary`, `artifact_path`); on timeout → `RuntimeError` with a `job_id` hint. |
| `get_skill_job(job_id)` | Re-fetch a job's status/result by id (durable — survives a runner restart via the MySQL job index). |

## Execution model

The skill does **not** run on the client. Call path:

```
client (pi/opencode/…) → LiteLLM (:4000) → mcp_skills → skill-runner (:8091)
```

`POST /skills/{name}` on skill-runner is synchronous (blocks until the job
reaches a terminal state or an approval gate), so `run_skill` issues the POST
with a generous timeout and returns the final job.

## Identity threading

The caller's LiteLLM key is forwarded by LiteLLM via the `Authorization`
header (`extra_headers: ["Authorization"]` in `litellm/config.yml`). The server
reads it from the MCP request context (`_caller_key(ctx)`):

- **Execution** (`run_skill`, `get_skill_job`): presents the **caller key** as
  `X-API-Key`, so the job attributes to the right user (`resolve_user_id()`).
  Falls back to the service key when no caller key is present.
- **Discovery** (`list_skills` / internal `GET /skills`): always uses the
  **service key** (`SKILL_RUNNER_API_KEY`) — the caller's key (e.g. the LiteLLM
  master) is not in skill-runner's allow-list. (Fixed 2026-08-29: discovery
  used the caller key → 403.)

## Configuration

| Env var | Default | Description |
|---|---|---|
| `SKILL_RUNNER_URL` | `http://skill-runner:8091` | skill-runner base URL. |
| `SKILL_RUNNER_API_KEY` | *(empty)* | Service key (fallback when no caller key). |
| `SKILL_RUNNER_TIMEOUT` | `180` | Default wait (seconds) when the skill has no `max_runtime`. |
| `MCPS_HOST` | `0.0.0.0` | Bind host. |

## Transport

streamable-http (HTTP), default `0.0.0.0:8000`, path `/mcp`.