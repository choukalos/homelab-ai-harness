# Thor Skill Runner

Lightweight skill orchestration API — the foundation of the new AI Harness (Phase 8).

Runs on dev port **8091** alongside the current AI Harness (8090). The current Harness is not touched until manual cutover (Phase 14).

## Architecture

```
Skill Runner (container :8091 on Thor)   →  litellm-proxy:4000    (on ai-net)
Skill Runner (laptop :8091 on LAN)       →  http://192.168.4.54:4000  (LAN)
```

The skill runner talks to LiteLLM for:
- **LLM generation** via `/v1/chat/completions`
- **MCP tool calls** via SSE transport to MCP servers on `ai-net`

Skills never touch MCP servers directly — the runner is the single gateway.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/skills/{skill_name}` | Launch a skill job |
| `GET` | `/skills/jobs/{job_id}` | Get job status |
| `GET` | `/skills/jobs/{job_id}/artifact` | Retrieve artifact file |
| `POST` | `/skills/jobs/{job_id}/approve` | Approve a job at an approval gate |
| `POST` | `/skills/jobs/{job_id}/cancel` | Cancel a job |

## Job Model

A job tracks the complete lifecycle of a skill invocation:

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | Unique hex ID (12 chars) |
| `skill` | string | Skill name (e.g. `deep_research`) |
| `status` | enum | `pending`, `running`, `completed`, `failed`, `awaiting_approval`, `cancelled` |
| `created_at` | ISO 8601 | Creation timestamp |
| `completed_at` | ISO 8601 | Completion timestamp (nullable) |
| `summary` | string | Short text summary (nullable) |
| `artifact_path` | string | Path to output artifact (nullable) |
| `requester` | string | Who requested the job |
| `channel` | string | Channel that launched the job |
| `params` | dict | Skill-specific input parameters |
| `dry_run` | bool | Skip actual execution |
| `tool_bundle` | string | Tool bundle name (nullable) |
| `model_alias` | string | Model alias to use (nullable) |
| `error` | string | Error message on failure (nullable) |
| `logs` | list | Timestamped execution log |

## Known Skills

The runner recognizes these skill names (defined in Phase 4.6):

- `siri_ask` — Quick Q&A for Siri/iOS Shortcuts
- `deep_research` — Multi-source research with citations
- `investment_brief` — Investment analysis reports
- `presentation_build` — Generate presentations via Presenton
- `code_review` — Code quality review
- `repo_maintenance` — Repository hygiene (approval gate)
- `family_kb_ingest` — KB ingestion (approval gate)
- `morning_brief` — Daily morning briefing
- `homelab_report` — Homelab health report

Skills with approval gates: `family_kb_ingest`, `repo_maintenance`

## Running Modes

### Container Mode (Thor)

Run the skill runner as a standalone container on Thor:

```bash
cd /home/chuck/homelab
docker compose -f compose/compose.skill-runner.yml up --build -d
```

The container runs on port 8091 and connects to LiteLLM on the `ai-net` network.

Environment variables (set in compose file):
- `LITELLM_BASE_URL=http://litellm-proxy:4000`
- `LITELLM_API_KEY` — from `.env`
- `SKILL_RUNNER_PORT=8091`
- `ARTIFACT_ROOT=/home/chuck/data/media`

The `skills/` directory is mounted read-only at `/app/skills/` so new skills are picked up without rebuilding.

### Laptop Dev Mode (LAN)

Run on your laptop without Docker. Points at LiteLLM on Thor over the LAN:

```bash
cd /home/chuck/homelab/skills/runner
./dev.sh
```

This activates a virtual environment (uses `uv` if available), installs dependencies, and starts uvicorn on port 8091.

Prerequisites on laptop:
- Python 3.10+
- `uv` (preferred) or pip + venv

Override defaults via environment:
```bash
LITELLM_API_KEY=sk-xxx ./dev.sh
```

## Development Workflow

1. Edit a skill's `skill.py` in `skills/<name>/`
2. Start the runner (`./dev.sh` or docker compose)
3. Launch a skill:
   ```bash
   curl -X POST http://localhost:8091/skills/deep_research \
     -H "Content-Type: application/json" \
     -d '{"params":{"query":"test"}}'
   ```
4. Check status:
   ```bash
   curl http://localhost:8091/skills/jobs/<job_id>
   ```
5. Iterate — no Docker, no LiteLLM restarts, no production impact

## Dry Run

Set `dry_run: true` in the request body or set `SKILL_RUNNER_DRY_RUN=true` globally to skip actual execution and log what would happen.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `LITELLM_BASE_URL` | `http://litellm-proxy:4000` (container) / `http://192.168.4.54:4000` (dev) | LiteLLM proxy URL |
| `LITELLM_API_KEY` | `""` | LiteLLM API key |
| `SKILL_RUNNER_PORT` | `8091` | Listen port |
| `SKILL_RUNNER_HOST` | `0.0.0.0` | Bind address |
| `ARTIFACT_ROOT` | `/home/chuck/data/media` | Base directory for artifacts |
| `SKILL_RUNNER_LOG_DIR` | `/home/chuck/homelab/logs/skill_runner` | Log file directory |
| `SKILL_RUNNER_DRY_RUN` | `""` | Global dry-run toggle (`true`/`1`/`yes`) |
| `MCP_SERVER_SEARCH_URL` | `http://mcp_search:8000` | MCP search server URL |
| `MCP_SERVER_KNOWLEDGE_URL` | `http://mcp_knowledge:8000` | MCP knowledge server URL |
| `MCP_SERVER_CRAWL_URL` | `http://mcp_crawl:8000` | MCP crawl server URL |
| `MCP_SERVER_FILESYSTEM_READONLY_URL` | `http://mcp_filesystem_readonly:8000` | MCP filesystem server URL |

## Rules

- Do not bind production port 8090
- Do not replace current AI Harness
- Do not update Caddy
- Do not update Cloudflare
- Do not restart existing services

See [TODO.md](../../TODO.md) Phase 8 for full design specification.
