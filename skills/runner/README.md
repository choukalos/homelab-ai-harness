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
| `POST` | `/api/chat` | Unified chat gateway (intent detection, skill dispatch) |
| `GET` | `/api/jobs/{job_id}` | Poll async job status |
| `POST` | `/api/schedule` | Create a recurring schedule |
| `GET` | `/api/schedule` | List all schedules |
| `DELETE` | `/api/schedule/{id}` | Remove a schedule |
| `POST` | `/api/schedule/{id}/run-now` | Trigger a schedule immediately |
| `POST` | `/skills/{skill_name}` | Launch a skill job |
| `GET` | `/skills/jobs/{job_id}` | Get job status |
| `GET` | `/skills/jobs/{job_id}/artifact` | Retrieve artifact file |
| `POST` | `/skills/jobs/{job_id}/approve` | Approve a job at an approval gate |
| `POST` | `/skills/jobs/{job_id}/cancel` | Cancel a job |
| `GET` | `/media/files/{filepath:path}` | Serve any file under `ARTIFACT_ROOT` |
| `GET` | `/skills/jobs/{job_id}` | Poll async job status (alternative to `/api/jobs/`) |

### Static File Serving

`/media/files/{filepath:path}` serves any file from the artifact root
(`/home/chuck/data/media/`). Path is relative to that root:

- `/media/files/generated/sunset.png` → generated images
- `/media/files/demos/my-demo.html` → demo HTML files
- `/media/files/presentations/deck.pptx` → exported PPTX files
- `/media/files/images/photo.jpg` → images

Proxied publicly via Caddy at `https://siri.choukalos.com/media/files/*`.

Presenton runs passwordless and LAN-only (`http://thor.local:5000`); the
former public `siri.choukalos.com/presentations/*` route was removed
2026-09-04 (see `docs/thor_presenton_integration.md`).

### Chat Gateway — `POST /api/chat`

Unified entry point. Accepts `{"text": "...", "model": "..."}` and auto-detects
the intent. Non-chat intents dispatch asynchronously and return a `job_id`
for polling at `/api/jobs/{job_id}` (or `/skills/jobs/{job_id}`).

**Intents:**

| Intent | Description | Source |
|---|---|---|
| `chat` | Direct chat (no tools) | — |
| `siri-chat` | Siri chat with MCP tool calling | siri_chat |
| `deep-research` | Multi-source cited research | deep_research |
| `research-brief` | Lightweight web research | research_brief |
| `build-presentation` | Create new presentation | presentation_build |
| `update-presentation` | Update existing presentation | presentation_update |
| `find-demos` | Search demos by keyword | demo_browse |
| `list-demos` | List all demos | demo_browse |
| `list-presentations` | List presentations from Presenton | built-in |
| `list-images` | List generated images | built-in |
| `media-generate` | Generate image via ComfyUI | mcp_media |
| `create-demo` | Create a demo workflow | demo_workflow |

**Example — async listing with polling:**
```bash
# Request
RESP=$(curl -s -X POST https://siri.choukalos.com/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SIRI_API_KEY" \
  -d '{"text": "list my images"}')

JOB_ID=$(echo $RESP | jq -r .job_id)

# Poll until complete
curl -s https://siri.choukalos.com/api/jobs/$JOB_ID \
  -H "X-API-Key: $SIRI_API_KEY" | jq .
```

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
- `presentation_update` — Update existing presentations
- `code_review` — Code quality review
- `repo_maintenance` — Repository hygiene (approval gate)
- `morning_brief` — Daily morning briefing
- `homelab_report` — Homelab health report
- `siri_chat` — Enhanced chat with MCP tool access
- `demo_workflow` — Full 8-phase demo pipeline
- `demo_browse` — Search/browse demos by keyword
- `research_brief` — Lightweight web research + summarization

### Built-in Listing Intents (no skill manifest needed)

These are handled directly by the chat gateway via `/api/chat`:

- `list-demos` — Browse demos in `/home/chuck/data/media/demos/`
- `list-presentations` — List presentations from Presenton API
- `list-images` — List generated images from `/media/generated/` + `/media/images/`

All listing intents dispatch asynchronously and return a `job_id` for polling.

Skills with approval gates: `repo_maintenance`

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

The `skills/` directory is mounted read-only at `/app/skills/` so new skills
are picked up without rebuilding. **However, the runner core (`main.py`,
`scheduler.py`) is baked into the image** (`skills/runner/Dockerfile` COPYs
them into `/app/`, which shadows the bind mount on `sys.path`). Core changes
require rebuilding the image:

```bash
# canonical (rebuilds image + recreates container):
./homelab.sh rebuild skill-only
# manual equivalent:
docker build -t skill-runner:local skills/runner/ \
  && docker compose -f compose/compose.skill-runner.yml up -d --force-recreate skill-runner
```

`restart` / `up` do NOT rebuild the image — a stale image silently runs old
core code (2026-09-04 incident: a Sept-1 image shadowed scheduler changes
for days). Verify the running code with
`docker exec skill-runner grep -c save_state /app/scheduler.py`
or check a known-new log line.

### Scheduler

Cron-like scheduler for recurring skill jobs (see `scheduler/README.md`):

- **Definitions** — git-tracked `homelab/scheduler/schedules.json`, mounted
  read-only at `/app/scheduler/schedules.json`
  (`SCHEDULER_CONFIG_PATH`). Hot-reloaded on file change (mtime, ~60s) —
  edit + save, no restart.
- **Run state** — `last_run_at` / `next_run_at` per job id, persisted
  atomically to `/home/chuck/data/scheduler/state.json`
  (`SCHEDULER_STATE_PATH`), outside git.

Current jobs: `daily-recent-activity` (17:00 America/Chicago) and
`weekday-morning-brief` (09:00 America/Chicago Mon–Fri, `publish: true` →
`/home/chuck/data/media/public/briefs/latest.md` →
`https://choukalos.com/files/briefs/latest.md`).

The runtime `POST /api/schedule` / `DELETE /api/schedule/{id}` endpoints
attempt to write the definitions file, which is read-only in production —
they log an error there. The git-tracked file is the source of truth.
`POST /api/schedule/{id}/run-now` records the manual run in state
(`last_run_at` only; the cron grid is unchanged).

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
| `SCHEDULER_CONFIG_PATH` | `~/.thor/schedules.json` | Schedule definitions file (git-tracked, read-only mount in container) |
| `SCHEDULER_STATE_PATH` | `<config dir>/state.json` | Scheduler run-state file (untracked; container: `/app/data/scheduler/state.json`) |
| `PRESENTON_PASSWORDLESS` | `false` | Skip Basic auth for Presenton API calls (passwordless mode) |
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

See [`docs/thor_skill_architecture.md`](../../docs/thor_skill_architecture.md) + [`docs/thor_cross_client_skills.md`](../../docs/thor_cross_client_skills.md) for the full design.
